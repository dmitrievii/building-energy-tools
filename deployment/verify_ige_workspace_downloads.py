"""Verify actual browser-downloaded files independently of UI success messages."""
from hashlib import sha256
import csv
import gzip
import io
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools/climate_analyzer'), str(ROOT/'research/ige_cmip6')]


def verify(out):
    from epw_climate_analyzer.engine.model_sources import bounded_zip
    from epw_climate_analyzer.engine.f1 import check_state
    from f1_replay_audit import compare_output
    import pandas as pd
    out = Path(out)
    audit = json.loads((out/'browser-acceptance.json').read_bytes())
    assert audit['status'] == 'PASS' and len(audit['downloads']) == 10
    for row in audit['downloads']:
        raw = (out/row['file']).read_bytes()
        assert len(raw) == row['bytes'] and sha256(raw).hexdigest() == row['sha256']
    def epw(name):
        raw = (out/'downloads'/name).read_bytes()
        rows = list(csv.reader(io.StringIO(raw.decode())))
        assert len(rows) == 8768 and all(len(r) == 35 for r in rows[8:])
        assert rows[8][:5] == ['2023','1','1','1','60'] and rows[-1][:5] == ['2023','12','31','24','60']
        return raw, rows
    s1, srows = epw('s1-point.epw'); f1, frows = epw('f1-future.epw')
    assert sha256(s1).hexdigest() == '855515517eb22601f5f4e6025a32ff463fc81b8055aa08168ff48442565138d2'
    assert float(srows[0][9]) == 375. and float(frows[0][9]) == 467.
    sources = bounded_zip((out/'downloads/f1-future.zip').read_bytes(), byte_limit=256*1024**2, member_limit=96)
    manifest = json.loads(sources['manifest.json'])
    assert set(sources) == set(manifest['files']) | {'manifest.json'}
    for name, entry in manifest['files'].items():
        assert sha256(sources[name]).hexdigest() == entry['sha256'] and len(sources[name]) == entry['bytes']
    assert sources['climate.epw'] == f1
    assert sources['ui_report.json'] == (out/'downloads/f1-quality.json').read_bytes()
    assert sources['hourly.csv.gz'] == (out/'downloads/f1-hourly.csv.gz').read_bytes()
    assert sources['adjustment_ledger.csv.gz'] == (out/'downloads/f1-adjustments.csv.gz').read_bytes()
    assert sha256(sources['source_packets/NASA_NEX_original.sources.zip']).hexdigest() == '2df672bc6cb2929ca4f59fb8eed061b46561849c0e716a7419d5c56d938b69bd'
    with zipfile.ZipFile(ROOT/'research/ige_cmip6/f1_original_output_reference_20261029.zip') as z:
        comparison = compare_output(f1, z.read('climate.epw'))
    quality = json.loads(sources['ui_report.json'])
    f = pd.read_csv(io.BytesIO(gzip.decompress(sources['hourly.csv.gz'])), index_col=0)
    ledger = pd.read_csv(io.BytesIO(gzip.decompress(sources['adjustment_ledger.csv.gz'])))
    assert len(f) == len(ledger) == 8760
    closure = check_state(f, quality['diagnostics']['water_curve'])
    assert quality['quality']['independent_accuracy'] == 'NOT_INDEPENDENTLY_VALIDATED'
    assert not quality['production_ready']
    h1 = bounded_zip((out/'downloads/h1-admission.zip').read_bytes(), byte_limit=128*1024**2, member_limit=50)
    assert 'climate.epw' not in h1
    assert h1['admission.json'] == (out/'downloads/h1-admission.json').read_bytes()
    assert h1['missing_hours.csv.gz'] == (out/'downloads/h1-gaps.csv.gz').read_bytes()
    admission = json.loads(h1['admission.json']); assert admission['status'] == 'EPW_BLOCKED'
    counts = {row['field']:row['numeric_hours'] for row in admission['fields']}
    assert counts['dry_bulb_temperature_c'] == 4303 and counts['atmospheric_station_pressure_pa'] == 8736
    contract = ROOT/'deployment/ige-f1-candidate-20261029.json'
    frozen = {name:value for name,value in json.loads(contract.read_bytes())['source_sha256'].items() if name.startswith('research/')}
    assert all(sha256((ROOT/name).read_bytes()).hexdigest() == value for name,value in frozen.items())
    result = {'schema':'IGE_WORKSPACE_ACTUAL_BROWSER_DOWNLOAD_VERIFICATION_v1','status':'PASS',
        'browser_downloads_verified':10,'annual_rows_S1':8760,'annual_rows_F1':8760,'adjustment_rows_F1':8760,
        'S1_EPW_sha256':sha256(s1).hexdigest(),'F1_EPW_sha256':sha256(f1).hexdigest(),
        'F1_reference_comparison':comparison,'F1_csv_state_closure':closure,
        'F1_ZIP_every_member_hash_verified':True,'H1_incomplete_EPW_rejected':True,
        'H1_temperature_numeric_hours':4303,'H1_pressure_numeric_hours':8736,
        'unchanged_original_research_inputs':len(frozen),'scientific_implementation_changed':True,
        'new_independent_accuracy_qualification':False,'actual_public_deployment_verified':False}
    (out/'download-verification.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    return result


if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--out',type=Path,required=True)
    verify(p.parse_args().out)
