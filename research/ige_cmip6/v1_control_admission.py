"""Pre-control source gate: do not reveal targets with no usable R1 forecasts.

Availability-only addendum; primary operators/QC/model and all24 cases stay
unchanged. A blocked target is retained, never replaced by an easier station.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
from hashlib import sha256
import io,json,tempfile,unittest,collections
from pathlib import Path
from v1_prepare import R,REG,LEDGER,SEAL,INPUTS,registered
from v1_acquire import collect,NoRedirect,read_packet
from urllib.request import build_opener
from epw_climate_analyzer.engine.historical import json_bytes
from epw_climate_analyzer.engine.epw import write_exclusive
ADDENDUM='v1_control_admission_addendum_20261026.json'
RECEIPT='v1_control_gate_receipt_20261026.json'


def source_admission(plan,ledger):
    keys=set(plan['target_keys'])
    if len(ledger['cases'])!=24 or {(c['target_key'],c['season']) for c in ledger['cases']}!={(k,w['season']) for k in keys for w in plan['windows']}:
        raise ValueError('V1_CONTROL_GATE_CASE_CENSUS')
    threshold=plan['scoring']['case_admission_minimum_paired_hours']
    admitted={key:any(c['target_key']==key and c['R1_predicted_hours']>=threshold for c in ledger['cases']) for key in keys}
    return {s['url']:{'target_key':s['station_key'],'open':admitted[s['station_key']],
        'reason':None if admitted[s['station_key']] else 'NO_REGISTERED_CASE_HAS_160_PRIMARY_R1_FORECASTS; leave control body unopened'} for s in plan['controls']}


class ForecastGate:
    def __init__(self,admission,opener):
        self.admission=admission;self.opener=opener;self.HTTP_requests=0;self.local_skips=[]
    def open(self,request,**kwargs):
        if request.full_url not in self.admission:raise ValueError('V1_CONTROL_GATE_UNREGISTERED_URL')
        row=self.admission[request.full_url]
        if not row['open']:
            self.local_skips.append(request.full_url)
            raise ValueError('V1_CONTROL_NOT_OPENED_PREDICTOR_QC_GATE:'+row['target_key'])
        self.HTTP_requests+=1
        return self.opener(request,**kwargs)


def checked_addendum():
    plan=registered();ledger=json.loads((R/LEDGER).read_text());a=json.loads((R/ADDENDUM).read_text())
    bodies,manifest,storage=read_packet(R,INPUTS,phase='inputs')
    counts={s['station_key']:dict(collections.Counter(map(str,json.loads(bodies[s['member']])['features'][0]['properties']['parameters']['tl_flag']['data'])))
        for s in manifest['sources'] if s['role']=='donor' and s['station_key'].startswith('AT:') and s['status']=='ORIGINAL_BODY_RECEIVED'}
    if (a['registration_sha256']!=sha256((R/REG).read_bytes()).hexdigest()
            or a['prediction_ledger_sha256']!=sha256((R/LEDGER).read_bytes()).hexdigest()
            or a['gate_module_sha256']!=sha256(Path(__file__).read_bytes()).hexdigest()
            or a['source_admission']!=source_admission(plan,ledger)
            or a['input_original_packet_sha256']!=storage['sha256'] or a['donor_QC_counts']!=counts
            or a['control_bodies_already_opened'] is not False
            or a['primary_QC_or_method_changed'] is not False):
        raise ValueError('V1_PRECONTROL_ADMISSION_ADDENDUM_CHANGED')
    return plan,ledger,a


def guarded_collect(output,commit):
    plan,ledger,a=checked_addendum()
    gate=ForecastGate(a['source_admission'],build_opener(NoRedirect).open)
    # Original collector still verifies the exact remotely published primary
    # seal and every frozen file (including this module/addendum) before I/O.
    m=collect('controls',output,commit,opener=gate.open)
    receipt={'schema':'IGE_V1_ACTUAL_CONTROL_SOURCE_GATE_v1','published_seal_commit':commit,
        'addendum_sha256':sha256((R/ADDENDUM).read_bytes()).hexdigest(),
        'actual_control_HTTP_requests':gate.HTTP_requests,'locally_blocked_control_attempts':len(gate.local_skips),
        'locally_blocked_URLs':gate.local_skips,'AT_control_bodies_opened':False,
        'original_collector_HTTP_attempts_field_counts_acquisition_attempts_including_local_skips':m['HTTP_attempts_this_phase'],
        'all24_registered_cases_retained':True,'primary_QC_or_method_changed':False}
    write_exclusive(output/RECEIPT,json_bytes(receipt));return receipt


class GateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan,cls.ledger,cls.addendum=checked_addendum()
    def test_AT_remains_unopened_before_new_QC_qualification(self):
        for row in self.addendum['source_admission'].values():
            self.assertEqual(row['open'],not row['target_key'].startswith('AT:'))
    def test_case_census_remains24(self):self.assertEqual(len(self.ledger['cases']),24)
    def test_all4032_prediction_rows_are_retained(self):self.assertEqual(self.ledger['requested_reference_hours'],4032)
    def test_no_original_QC_relaxation(self):
        self.assertEqual(self.plan['QC']['AT']['primary'],[22]);self.assertEqual(self.plan['QC']['AT']['secondary'],[12])
    def test_rejected_before_network(self):
        from urllib.request import Request
        gate=ForecastGate({'https://example.invalid/AT':{'open':False,'target_key':'AT:test'}},lambda *a,**k:self.fail('Network invoked'))
        with self.assertRaisesRegex(ValueError,'NOT_OPENED'):gate.open(Request('https://example.invalid/AT'),timeout=1)
        self.assertEqual(gate.HTTP_requests,0);self.assertEqual(len(gate.local_skips),1)
    def test_unregistered_URL_cannot_replace_block(self):
        from urllib.request import Request
        gate=ForecastGate({},lambda *a,**k:self.fail('Network invoked'))
        with self.assertRaisesRegex(ValueError,'UNREGISTERED'):gate.open(Request('https://example.invalid/replacement'))
    def test_missing_cases_cannot_bypass_gate(self):
        with self.assertRaisesRegex(ValueError,'CENSUS'):source_admission(self.plan,{'cases':self.ledger['cases'][:-1]})
    def test_registered_threshold_not_fitted_to_errors(self):
        import copy
        ledger=copy.deepcopy(self.ledger)
        for c in ledger['cases']:c['R1_predicted_hours']=159
        self.assertFalse(any(x['open'] for x in source_admission(self.plan,ledger).values()))
        ledger['cases'][0]['R1_predicted_hours']=160
        admitted=source_admission(self.plan,ledger)
        target=ledger['cases'][0]['target_key']
        self.assertTrue(all(x['open'] for x in admitted.values() if x['target_key']==target))


def verify(output):
    output.mkdir(parents=True,exist_ok=False)
    result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromTestCase(GateTests))
    if not result.wasSuccessful():raise RuntimeError('V1_CONTROL_GATE_TESTS_FAILED')
    plan,ledger,a=checked_addendum()
    seal=json.loads((R/SEAL).read_text())
    for name in ('v1_control_admission.py',ADDENDUM):
        if seal['frozen_files_sha256'].get(name)!=sha256((R/name).read_bytes()).hexdigest():raise ValueError('V1_CONTROL_GATE_NOT_IN_PRECONTROL_SEAL')
    r={'schema':'IGE_V1_CONTROL_GATE_VERIFICATION_v1','tests_run':result.testsRun,'status':'PASS',
        'gate_module_sha256':sha256(Path(__file__).read_bytes()).hexdigest(),
        'addendum_sha256':sha256((R/ADDENDUM).read_bytes()).hexdigest(),
        'AT_controls_unopened':True,'original_primary_QC_unchanged':True,'production_ready':False}
    if (R/RECEIPT).exists():
        actual=json.loads((R/RECEIPT).read_text())
        if actual['AT_control_bodies_opened'] is not False or not 0<=actual['actual_control_HTTP_requests']<=18 or actual['locally_blocked_control_attempts']!=2:raise ValueError('V1_ACTUAL_CONTROL_ADMISSION_CHANGED')
        r['actual_source_gate']=actual
    write_exclusive(output/'v1_control_gate_verification.json',json_bytes(r));print(json.dumps(r),flush=True)
    return r

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--collect',action='store_true');p.add_argument('--published-commit');p.add_argument('--out',type=Path,required=True);a=p.parse_args()
    if a.collect:
        if not a.published_commit:p.error('--published-commit required for collection')
        guarded_collect(a.out,a.published_commit)
    else:verify(a.out)
