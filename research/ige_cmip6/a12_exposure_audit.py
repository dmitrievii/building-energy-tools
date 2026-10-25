"""Bounded audit of prior station/year/variable use from retained code and docs.

Archive-byte exposure, numeric extraction, model fitting and score inspection
are different facts. No observation CSV/ZIP or measurement JSON is opened.
Absence of a code match does not certify all external project history.
"""
from __future__ import annotations
from hashlib import sha256
from functools import lru_cache
import io
import json
from pathlib import Path
import re
import subprocess
import zipfile

ROOT=Path(__file__).resolve().parents[2]
BASE='ae6f4ae406fd1adf72eaf4da23d898e1d54059ff'


@lru_cache(maxsize=1)
def audit():
    protocol=json.loads((ROOT/'research/ige_cmip6/a1_1_protocol_20261025.json').read_text())
    files=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE,'--','research/ige_cmip6','docs','.github/workflows'],cwd=ROOT,text=True).splitlines()
    files=[p for p in files if Path(p).suffix in ('.py','.md','.yml','.yaml')
        and not Path(p).name.startswith(('a1','test_','IGE_A1'))]
    targets=protocol['targets'];matches={g['target_key']:[] for g in targets};digests={};totals={k:0 for k in matches}
    labels={g['target_key']:[g['target']['station_id'],g['target']['name'],g['anchor']['anchor'].split('_',1)[1]] for g in targets}
    for path in files:
        body=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT)
        digests[path]=sha256(body).hexdigest();lines=body.decode('utf8',errors='replace').splitlines()
        for key,terms in labels.items():
            for number,line in enumerate(lines,1):
                if any(re.search(r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])',line,re.I) for term in terms):
                    totals[key]+=1
                    if len(matches[key])<40:
                        matches[key].append({'path':path,'line':number,'source_line_sha256':sha256(line.encode()).hexdigest(),
                            'source_context':line[:240]})
    def evidence(path,needle):
        b=subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT);s=b.decode()
        assert needle in s
        return {'path':path,'sha256':sha256(b).hexdigest(),'first_matching_line':s[:s.index(needle)].count('\n')+1}
    crossyear='research/ige_cmip6/p8_2e_crossyear.py'
    other=json.loads(subprocess.check_output(['git','show',BASE+':research/ige_cmip6/p9_2c_regional_2025_frozen_cohort.json'],cwd=ROOT))
    prior_keys={'AT:30','DE:03730','CH:DAV'}
    assert {g['target_key'] for g in targets}.isdisjoint(prior_keys)
    by_site={}
    for group in targets:
        key=group['target_key']
        by_site[key]={'prior_code_or_document_mentions':matches[key],
            'text_match_count_before_40_row_display_cap':totals[key],
            'text_matches_are_not_automatically_station_use_evidence':True,
            'documented_2025_target_T_fitting_or_tuning_found_in_reviewed_evidence':False,
            'absence_is_global_proof':False,'strict_source_byte_unexposed_certified':False,
            'conclusion':'NO_KNOWN_2025_TARGET_T_USE_IN_AUDITED_RETAINED_SCOPE; external source manifests incomplete'}
    by_site['CH:BAS'].update({
        'P8_2E_raw_archive_exposure':'POTENTIAL_PREVIOUS_2020_2029_HOURLY_CONTAINER_DOWNLOAD_AS_2020_DONOR; later wind container exposure separately confirmed below',
        'numeric_2025_values_used_by_P8_2E_parser':False,
        'parser_evidence':evidence(crossyear,'if when.year!=year:continue'),
        'execution_year_guard':evidence(crossyear,"if year not in (2018,2020):"),
        'archive_selection_evidence':evidence(crossyear,"dec='2020-2029' if year>=2020 else '2010-2019'"),
        'conclusion':'NOT_CERTIFIED_RAW_UNSEEN; documented parser excludes 2025 before extracting T/P/e/RH/Td; no demonstrated 2025 fitting/score leakage'})
    by_site['DE:01443']['other_variable_prior_use']={
        'pressure_2023_source_census':evidence('research/ige_cmip6/p9_3b2d_dwd_source_only_census.py','01443'),
        'prior_pressure_availability_is_not_proof_of_2025_temperature_training':True}
    by_site['AT:3202']['earlier_solar_transfer_note']='Linz group56 appeared in earlier solar-transfer geography; GHI/2012-2014 is not target T/2025. Group aliases require source crosswalk.'
    artifact=ROOT/'research/ige_cmip6/a12_prior_wind_provenance_39023515729.zip'
    artifact_raw=artifact.read_bytes()
    digest='33e1f8fc85fbf0de9c2baa820fc58adfd1e7ee02dd4661b67ad50397da83e8c7'
    if sha256(artifact_raw).hexdigest()!=digest:raise ValueError('A12_PRIOR_PROVENANCE_ARTIFACT_HASH')
    with zipfile.ZipFile(io.BytesIO(artifact_raw)) as archive:
        if len(archive.namelist())!=1 or not archive.namelist()[0].endswith('aggregates.json') or archive.infolist()[0].file_size>2_000_000:
            raise ValueError('A12_EXPECTED_AGGREGATE_PROVENANCE_ONLY')
        prior=json.loads(archive.read(archive.namelist()[0]))
    assert prior['original_provider_hourly_observations_published'] is False
    selected_ch={s['station_id'] for g in targets for s in [g['target'],*g['donors']] if s['country']=='CH'}
    provenance={r['station_id']:r for r in prior['full_catalog_original_provenance'] if r['station_id'] in selected_ch}
    assert set(provenance)==selected_ch and all(r['read_ok'] for r in provenance.values())
    parser_path='research/ige_cmip6/p8_3a_wind_spatial.py'
    for key in ('CH:BAS','CH:ALT'):
        by_site[key].update({'raw_archive_exposure':'CONFIRMED_PRIOR_WHOLE_HOURLY_CONTAINER_BYTES_WITH_2025_WIND_COVERAGE',
            'source_manifest_row':provenance[key.split(':')[1]],
            'raw_byte_unseen_claim_allowed':False,
            'numeric_temperature_2025_extraction_demonstrated':False,
            'temperature_2025_prediction_errors_or_fitting_demonstrated':False,
            'conclusion':'SOURCE_CONTAINER_PREVIOUSLY_READ; wind parser selects wind fields, not T; no documented 2025 T fitting/score leakage, no strict untouched-source qualification'})
    return {'schema':'IGE_A12_BOUNDED_EXPOSURE_AUDIT_v1','base_commit':BASE,
        'audited_versioned_text_files':len(files),'audited_file_sha256':digests,
        'scope':'retained research Python, workflow YAML and reports; observation payloads not read',
        'excluded_or_unavailable':['raw observation bodies','all expired original Actions source manifests','untracked external archives and unindexed prior conversations'],
        'prior_P9_2C_2025':{'sites':other['sites'],'windows':other['evaluation_UTC_windows'],'overlap_with_A1_control_station_identity':False},
        'targets':by_site,'strict_blindness_certified':False,
        'prior_P8_4B3':{'CI_run':39023515729,'tested_commit':'c73275842ea378027866f663dc5f880c1642f627',
            'artifact_id':12097702297,'artifact_file':artifact.relative_to(ROOT).as_posix(),'artifact_bytes':len(artifact_raw),'artifact_sha256':digest,
            'only_published_wind_aggregate_and_source_provenance_opened':True,'new_observation_containers_opened':False,
            'all_eight_selected_CH_station_containers_previously_read':provenance,
            'wind_field_evidence':[evidence(parser_path,"SPEED='fkl010h0'"),evidence(parser_path,"DIRECTION='dkl010h0'")],
            'source_census_evidence':evidence('research/ige_cmip6/p8_4b3_independent_sites.py','b2.source_census(metadata)'),
            'assessed_past_variable':'wind, not temperature skill'},
        'raw_bytes_exposed_does_not_by_itself_prove_training_or_score_leakage':True,
        'no_previously_revealed_score_relabeled_independent':True,
        'new_2025_station_measurements_opened':False,'IV1_2022_values_opened':False,
        'independent_accuracy_qualified':False,'decision':'Retain frozen six targets; publish exposure tiers; no strict untouched-data claim or scoring before prediction seal'}


if __name__=='__main__':
    r=audit();print(json.dumps({'files':r['audited_versioned_text_files'],'strict_blindness_certified':False,
        'site_mentions':{k:len(v['prior_code_or_document_mentions']) for k,v in r['targets'].items()}},indent=2))
