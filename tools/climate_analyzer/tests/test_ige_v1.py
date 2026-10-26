"""V1 scientific boundary cases, synthetic observations only before the seal."""
import copy,io,json,sys,tempfile,unittest,zipfile
from dataclasses import replace
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch
import numpy as np
import pandas as pd
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'research/ige_cmip6'));sys.path.insert(0,str(ROOT/'tools/climate_analyzer'))
from v1_prepare import registered,prepare_admission,metadata,EXPOSURE,R,PRODUCT,WINDOWS,TARGETS
from v1_time_admission import operator,selected_dwd,selected_swiss,bind,decode_at,dwd_geometry
from v1_acquire_metadata import metadata_url
from v1_acquire import allowed_spec,publication_gate,store_packet,read_packet,collect
from v1_run import observed_six_mean,summarize_blocks,metrics,model_temperature,score_predictions,quantize
from epw_climate_analyzer.station_reconstruction import StationReference,T,model_reference_operator,reconstruct_temperature
from epw_climate_analyzer.station_admission import admitted_reference
from epw_climate_analyzer.engine.station_year import reconstruct_nodes
A=pd.Timestamp('2018-01-10',tz='UTC');B=A+pd.Timedelta(hours=1)


def swiss(rows,field='tre200h0',sid='STG'):
    return ('station_abbr;reference_timestamp;'+field+'\n'+''.join(f'{sid};{t};{v}\n' for t,v in rows)).encode()


def de(rows,sid='00232'):
    return ('STATIONS_ID;MESS_DATUM;QN;TT_10\n'+''.join(f'{sid};{t};{q};{v}\n' for t,q,v in rows)).encode()


def at(flags):
    return json.dumps({'timestamps':['2018-01-10T00:00:00Z','2018-01-10T01:00:00Z'],
        'features':[{'properties':{'station':5609,'parameters':{'tl':{'unit':'°C','data':[1.,2.]},
            'tl_flag':{'unit':'1','data':flags}}}}]}).encode()


class V1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=registered();cls.admission=prepare_admission();cls.bodies,_=metadata()
        cls.drecord=cls.admission['records']['DE:00232'];cls.dref=admitted_reference(cls.drecord)
        cls.aref=admitted_reference(cls.admission['records']['AT:5609'])

    def test_DE_TT10_admitted_as_published_instant(self):
        o=operator('DE',*PRODUCT['DE'],A,B)
        self.assertEqual(o.model_node_weights,(0.,1.));self.assertFalse(o.instrument_filter_period_certified)

    def test_old_DE_TTTU_not_retroactively_admitted(self):
        with self.assertRaisesRegex(ValueError,'NOT_ADMITTED'):operator('DE','climate-hourly-air_temperature','TT_TU',A,B)

    def test_urban_TT_definition_not_imported(self):
        with self.assertRaises(ValueError):operator('DE','urban-hourly','TT_10',A,B)

    def test_DE_pre2000_MEZ_epoch_blocked(self):
        with self.assertRaisesRegex(ValueError,'MEZ'):operator('DE',*PRODUCT['DE'],A.replace(year=1999),B)

    def test_CH_pre2018_operator_blocked(self):
        with self.assertRaisesRegex(ValueError,'PRE_2018'):operator('CH',*PRODUCT['CH'],A.replace(year=2017),B)

    def test_naive_timestamps_blocked(self):
        with self.assertRaisesRegex(ValueError,'AWARE'):operator('AT',*PRODUCT['AT'],A.tz_localize(None),B)

    def test_AT_version_chain_remains_declared_inference(self):
        o=operator('AT',*PRODUCT['AT'],A,B)
        self.assertTrue(o.inference);self.assertFalse(o.instrument_filter_period_certified)

    def test_CH_six_nodes_operator_derivation(self):
        clock=pd.date_range(A,periods=2,freq='h');nodes=pd.Series([0.,12.,24.],index=clock.insert(0,A-pd.Timedelta(hours=1)))
        nodes.attrs['unit']='°C';actual=model_reference_operator(nodes,clock,'mean_six_10min_nominal_nodes')
        np.testing.assert_allclose(actual,[7.,19.]);self.assertNotEqual(actual.iloc[0],6.)

    def test_nominal_node_is_not_sensor_filter_certificate(self):
        o=operator('CH','ogd-smn-t','tre200s0',A,B)
        self.assertEqual(o.nominal_offsets_minutes,(0,));self.assertFalse(o.instrument_filter_period_certified)

    def test_all24_metadata_cases_ready_but_not_accuracy(self):
        self.assertEqual(self.admission['ready_cases'],24);self.assertFalse(self.admission['independent_accuracy_qualified'])

    def test_targets_and_physical_aliases_excluded_from_every_donor(self):
        ids={self.admission['records'][k]['resolved_identity_group'] for k in TARGETS}
        for g in self.admission['groups']:
            self.assertGreaterEqual(len(g['donors']),2)
            for d in g['donors']:
                self.assertNotIn(d,TARGETS);self.assertNotIn(self.admission['records'][d]['resolved_identity_group'],ids)

    def test_metadata_height_and_relocation_blocks_retained(self):
        for key in ('CH:SAE','CH:WFJ','CH:BIZ','DE:00142'):
            self.assertFalse(self.admission['records'][key]['temperature_source_eligible'])

    def test_DE_parameter_is_dated_TT10_not_only_generic_PDF(self):
        g,_=dwd_geometry(self.bodies['DE_10min_meta_00232.zip'],'00232',A,B)
        self.assertEqual(g['parameter_row']['Parameter'],'TT_10');self.assertIn('momentane',g['parameter_row']['Parameterbeschreibung'])

    def test_DE_full_hour_selection_not_ten_minute_average(self):
        b=selected_dwd(de([('201801100000','3','2'),('201801100010','3','50'),('201801100100','3','4')]),self.dref,A,B)
        np.testing.assert_array_equal(b.data[T],[2.,4.])

    def test_DE_QN3_not_replaced_by_hourly_QN10(self):
        b=selected_dwd(de([('201801100000','3','2'),('201801100100','10','4')]),self.dref,A,B)
        self.assertEqual(b.data['quality_accepted__'+T].tolist(),[True,False])

    def test_DE_cross_station_records_blocked(self):
        with self.assertRaisesRegex(ValueError,'CROSS_STATION'):selected_dwd(de([('201801100000','3','2')],sid='01270'),self.dref,A,B)

    def test_DE_duplicate_hour_blocked(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):selected_dwd(de([('201801100000','3','2')]*2),self.dref,A,B)

    def test_field_mismatch_cannot_cross_V1_admission(self):
        b=selected_dwd(de([('201801100000','3','2')]),self.dref,A,B)
        with self.assertRaisesRegex(ValueError,'FIELD_OPERATOR'):bind(b,self.drecord,provider_field='TT_TU')

    def test_AT_QC_integer_encoding_preserves_original_SHA(self):
        raw=at([22.0,12.0]);b=decode_at(raw,self.aref)
        self.assertEqual(b.source_sha256,sha256(raw).hexdigest())
        self.assertEqual(b.data['quality_accepted__'+T].tolist(),[True,False])
        self.assertEqual(b.data['secondary_quality__'+T].tolist(),[False,True])

    def test_AT_fractional_QC_not_rounded(self):
        with self.assertRaisesRegex(ValueError,'NONINTEGER'):decode_at(at([21.9,22]),self.aref)

    def test_AT_bool_QC_not_treated_as_integer(self):
        with self.assertRaisesRegex(ValueError,'NONINTEGER'):decode_at(at([True,22]),self.aref)

    def test_CH_missing_value_remains_missing_not_zero(self):
        v,q=selected_swiss(swiss([('10.01.2018 00:00',''),('10.01.2018 01:00','4')]),'STG',A,B)
        self.assertTrue(pd.isna(v.iloc[0]));self.assertEqual(q.tolist(),[False,True])

    def test_CH_t_endpoint_is_not_ten_minute_mean(self):
        v,q=selected_swiss(swiss([('10.01.2018 00:00','2'),('10.01.2018 00:10','60'),('10.01.2018 01:00','4')],field='tre200s0'),'STG',A,B,field='tre200s0')
        self.assertEqual(v.tolist(),[2.,4.])

    def test_CH_six_samples_no_missing_sample_infill(self):
        idx=pd.date_range(A-pd.Timedelta(minutes=50),A,freq='10min');v=pd.Series(range(6),index=idx,dtype=float)
        self.assertEqual(observed_six_mean(v,pd.DatetimeIndex([A]))[0],2.5)
        v.iloc[1]=np.nan;self.assertTrue(np.isnan(observed_six_mean(v,pd.DatetimeIndex([A]))[0]))

    def test_CH_cross_station_rejected(self):
        with self.assertRaisesRegex(ValueError,'CROSS_STATION'):selected_swiss(swiss([('10.01.2018 00:00','2')],sid='SCU'),'STG',A,B)

    def test_CH_duplicate_reference_rejected(self):
        with self.assertRaisesRegex(ValueError,'DUPLICATE'):selected_swiss(swiss([('10.01.2018 00:00','2')]*2),'STG',A,B)

    def test_CH_invented_QC_column_rejected(self):
        raw=b'station_abbr;reference_timestamp;tre200h0;tre200h0_qc\n'
        with self.assertRaisesRegex(ValueError,'UNDOCUMENTED'):selected_swiss(raw,'STG',A,B)

    def test_provider_product_cannot_enter_metadata_fetch(self):
        self.assertFalse(metadata_url('https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/stg/ogd-smn_stg_h_historical_2010-2019.csv'))
        self.assertFalse(metadata_url('https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/historical/10minutenwerte_TU_00232_20100101_20191231_hist.zip'))

    def test_standalone_DE_metadata_ZIP_allowed(self):
        self.assertTrue(metadata_url('https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/10_minutes/air_temperature/meta_data/Meta_Daten_zehn_min_tu_00232.zip'))

    def test_control_spec_cannot_enter_input_phase(self):
        with self.assertRaises(ValueError):allowed_spec(self.plan['controls'][0],'inputs',self.plan)

    def test_unregistered_source_cannot_replace_failed_source(self):
        s=copy.deepcopy(self.plan['inputs'][0]);s['url']+='&model=best_match'
        with self.assertRaises(ValueError):allowed_spec(s,'inputs',self.plan)

    def test_control_without_published_commit_blocked_before_network(self):
        with tempfile.TemporaryDirectory() as d,patch('v1_acquire.registered',return_value=self.plan):
            with self.assertRaisesRegex(ValueError,'PUBLISHED_COMMIT'):collect('controls',Path(d)/'never-created',None,opener=lambda *a,**k:self.fail('Network reached before gate'))
            self.assertFalse((Path(d)/'never-created').exists())

    def test_packet_parts_reassemble_bitwise(self):
        raw=io.BytesIO();body=b'original provider bytes\n';m={'phase':'inputs','original_body_sha256':{'source.csv':sha256(body).hexdigest()}}
        with zipfile.ZipFile(raw,'w') as z:z.writestr('source.csv',body);z.writestr('manifest.json',json.dumps(m))
        with tempfile.TemporaryDirectory() as d:
            directory=Path(d);info=store_packet(raw.getvalue(),directory,'test.zip')
            bodies,_,r=read_packet(directory,'test.zip',phase='inputs')
            self.assertEqual(bodies['source.csv'],body);self.assertEqual(info['sha256'],r['sha256'])
            p=directory/info['parts'][0]['name'];p.write_bytes(p.read_bytes()+b'x')
            with self.assertRaisesRegex(ValueError,'PART_HASH'):read_packet(directory,'test.zip',phase='inputs')

    def test_resampling_synchronous_seasons_not_independent_site_hours(self):
        blocks={s:[(np.array([2.,2.]),np.array([1.,1.])),(np.array([2.,2.]),np.array([1.,1.]))] for s in ('winter','spring','summer','autumn')}
        r=summarize_blocks(blocks)
        self.assertEqual(r['season_blocks'],4);self.assertEqual(r['B0']['n'],16)
        self.assertEqual(r['delta_MAE_K'],-1.);self.assertEqual(r['resampling_95pct_descriptive']['upper_K'],-1.)

    def test_empty_scores_remain_absent_not_zero_error(self):
        r=summarize_blocks({});self.assertIsNone(r['delta_MAE_K']);self.assertIsNone(r['R1']['MAE_K'])

    def test_centring_separates_bias_from_hourly_shape(self):
        r=metrics([2.,2.,2.]);self.assertEqual(r['bias_K'],2.);self.assertEqual(r['centred_RMSE_K'],0.)

    def test_inverse_high_frequency_gain_and_boundary_decay(self):
        clock=pd.date_range(A,periods=200,freq='h');nodes=clock.insert(0,A-pd.Timedelta(hours=1))
        b=pd.Series(0.,index=nodes);b.attrs['unit']='°C';raw=pd.Series((-1.)**np.arange(200),index=clock)
        actual,ledger=reconstruct_nodes(b,raw)
        self.assertAlmostEqual(abs(actual.iloc[-1]),6.,places=10)
        self.assertLess(20*(5/7)**73,5e-10)
        self.assertLess(np.max(np.abs(ledger.mean_roundtrip_residual_K)),1e-11)

    def test_R1_insufficient_donors_stays_NaN(self):
        group=next(g for g in self.admission['groups'] if g['target_key']=='CH:STG')
        target=admitted_reference(self.admission['records']['CH:STG']);refs=[admitted_reference(self.admission['records'][k]) for k in group['donors']]
        clock=pd.date_range(A,periods=2,freq='h');b=pd.Series([1.,2.],index=clock);b.attrs.update(unit='°C',reference_operator='mean_six_10min_nominal_nodes')
        obs={r.key:b+1 for r in refs};bg={r.key:b.copy() for r in refs}
        for s in obs.values():s.attrs.update(b.attrs)
        qc={r.key:pd.Series([True,False],index=clock) for r in refs}
        y,l=reconstruct_temperature(target,b,refs,obs,bg,qc)
        self.assertEqual(y.iloc[0],2.);self.assertTrue(pd.isna(y.iloc[1]));self.assertEqual(l.accepted_donor_count.tolist(),[2,0])

    def test_exposure_is_bounded_not_global_blindness_claim(self):
        e=json.loads((R/EXPOSURE).read_text())
        self.assertFalse(e['strict_raw_byte_unseen_global_certification'])
        self.assertNotIn('STG',e['old_CH_2010_2019_hourly_candidate_union']);self.assertNotIn('SCU',e['old_CH_2010_2019_hourly_candidate_union'])
        self.assertIn('monthly',e['prior_coarse_temperature_exposure'])

    def test_validation_cannot_claim_full_weather_or_production(self):
        self.assertFalse(self.plan['pressure_RH_q_accuracy_qualified_by_this_test'])
        self.assertFalse(self.plan['NASA_future_event_accuracy_qualified_by_this_test'])
        self.assertFalse(self.plan['production_ready'])

    def test_matched_mask_and_partial_case_admission(self):
        frames=[];cases=[]
        for key in TARGETS:
            for w in WINDOWS:
                clock=pd.date_range(w['start_UTC'],periods=168,freq='h')
                f=pd.DataFrame({'target_key':key,'country':key[:2],'season':w['season'],
                    'reference_time_UTC':clock,'B0_C':np.nan,'R1_C':np.nan,'R1_predicted':False,
                    'B0_endpoint_C':np.nan,'R1_endpoint_C':np.nan,'endpoint_eligible':False})
                if key=='DE:00232' and w['season']=='winter':
                    f.loc[0:1,'B0_C']=[11.,10.];f.loc[0,'R1_C']=10.5;f.loc[0,'R1_predicted']=True
                frames.append(f);cases.append({'target_key':key,'country':key[:2],'season':w['season'],
                    'R1_predicted_hours':int(f.R1_predicted.sum()),'source_block_reasons':[]})
        predictions=pd.concat(frames).to_csv(index=False).encode();data=de([('201801100000','3','10'),('201801100100','3','11')]);raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as z:z.writestr('produkt_zehn_min_tu_20100101_20191231_00232.txt',data)
        specs=self.plan['controls'];bodies={};receipts=[]
        for s in specs:
            ok=s['station_key']=='DE:00232'
            receipts.append({'id':s['id'],'status':'ORIGINAL_BODY_RECEIVED' if ok else 'SOURCE_BLOCKED'})
            if ok:bodies[s['member']]=raw.getvalue()
        manifest={'sources':receipts,'HTTP_attempts_this_phase':0,'decoded_body_bytes_read_all_attempts':0}
        with patch('v1_run.sources',return_value=(bodies,manifest,{'sha256':'0'*64})),patch('v1_run.registered',return_value=self.plan):
            result,pairs=score_predictions(predictions,{'cases':cases})
        c=next(c for c in result['cases'] if c['target_key']=='DE:00232' and c['season']=='winter')
        self.assertEqual(c['paired_hours'],1);self.assertEqual(c['B0_all_reference']['n'],2)
        self.assertEqual(c['B0_paired']['MAE_K'],1.);self.assertEqual(c['R1_paired']['MAE_K'],.5)
        self.assertEqual(result['per_country']['DE']['admitted_cases'],0);self.assertEqual(len(pairs),1)
        self.assertEqual(len(result['cases']),24)

    def test_malformed_case_census_cannot_be_silently_dropped(self):
        with self.assertRaises(ValueError):
            # The standalone loader also rejects an incomplete prediction grid.
            from v1_run import load_predictions
            load_predictions(b'target_key,reference_time_UTC,R1_predicted,endpoint_eligible\nDE:00232,2018-01-10T00:00Z,True,False\n')

if __name__=='__main__':unittest.main()
