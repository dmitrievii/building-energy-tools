#!/usr/bin/env python3
"""Local-only 28 P7C.5B EPWs + authentic contemporary benchmark; no licensed files to GitHub.

Requires EnergyPlus 26.2, official pinned one-zone IDF, Meteonorm baseline,
P7C5B corrected 28 EPWs, and verified provenance from P7C4 source manifest.
Fail closed on missing/malformed files; record E+.err for each model, flag any severe.
"""
from __future__ import annotations
import argparse, csv, hashlib,json,re,subprocess,sys,statistics
from pathlib import Path
from p7c5_energyplus_benchmark import generate_from_official,check_errors,extract_annual_sql
from p7c5b_solar_illuminance import parse_epw,sha

def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    src=Path(args.epw_dir)
    provenance=json.loads((src/'p7c5b_photometric_science_audit.json').read_text())
    if provenance.get('n')!=28 or provenance.get('energyplus_actual_simulation_executed'):raise ValueError('P7C.5B provenance invalid')
    all_members=[]
    for r in provenance['members']:
        p=src/r['filename']
        if not p.is_file() or sha(p.read_bytes())!=r['output_sha256']:raise ValueError('EPW integrity failure: '+r['filename'])
        h,rows=parse_epw(p.read_bytes());all_members.append(p)
    if len(set(p.name for p in all_members))!=28:raise ValueError('Expected 28 unique GCM scenarios')
    baseline=Path(args.baseline)
    if sha(baseline.read_bytes())!=provenance['baseline_sha256']:raise ValueError('Original Meteonorm baseline mismatch')
    eplus=Path(args.energyplus);ver=subprocess.run([str(eplus),'--version'],capture_output=True,text=True,check=True).stdout
    if '26.2.0' not in ver:raise RuntimeError('Wrong EnergyPlus version; require v26.2.0')
    official=Path(args.official_idf)
    model=out/'p7c5b_one_zone_idf.idf';model.write_text(generate_from_official(official.read_text()))
    inputs=[baseline]+all_members
    outputs=[];bad=[]
    for idx,epw in enumerate(inputs,1):
        work=out/'runs'/('BASELINE' if epw==baseline else epw.stem);work.mkdir(parents=True,exist_ok=True)
        cmd=[str(eplus.resolve()),'-w',str(epw.resolve()),'-d',str(work.resolve()),str(model.resolve())]
        process=subprocess.run(cmd,capture_output=True,text=True,timeout=args.timeout_s)
        (work/'stdout.txt').write_text(process.stdout[-6000:]);(work/'stderr.txt').write_text(process.stderr[-6000:])
        err=work/'eplusout.err';source=err.read_text(errors='replace') if err.exists() else 'MISSING ERR'
        record={'name':'BASELINE' if epw==baseline else epw.stem,'source_sha256':sha(epw.read_bytes()),'actual_energyplus':True,
                'eplus_returncode':process.returncode,'warnings_psychrometric':len(re.findall('PsyPsatFnTemp',source,re.I)),'diagnostic_err_sha256':sha(source.encode())}
        try:
            if process.returncode!=0:raise RuntimeError('Process failed '+source[-2500:])
            record.update(check_errors(err));record.update(extract_annual_sql(work/'eplusout.sql'))
            if record.get('heating_kwh',-1)<0 or record.get('cooling_kwh',-1)<0:raise RuntimeError('Invalid negative annual load')
            if any(not 8700<=v<=8760 for k,v in record.items() if k.startswith('n_')):raise RuntimeError('Unexpected hourly SQL count')
            record['status']='PASS'
        except Exception as exc:
            record['status']='FAIL';record['failure_reason']=str(exc)[:3000];bad.append(record['name'])
        outputs.append(record)
        print(f"[{idx:02}/{len(inputs)}] {record['name']} {record['status']}",flush=True)
    baseline_output=outputs[0]
    for result in outputs[1:]:
        if result['status']=='PASS' and baseline_output['status']=='PASS':
            result['heating_change_pct']=100*(result['heating_kwh']/baseline_output['heating_kwh']-1)
            result['cooling_change_pct']=100*(result['cooling_kwh']/baseline_output['cooling_kwh']-1) if baseline_output['cooling_kwh']>0 else None
    fields=sorted(set(k for r in outputs for k in r))
    with (out/'p7c5b_actual_energyplus_29_weather.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(outputs)
    report={'n_future_epw':28,'n_weather_files_executed':len(outputs),'n_Pass':len(outputs)-len(bad),'n_Fail':len(bad),
            'baseline_sha256':provenance['baseline_sha256'],'energyplus_version':ver.strip(),
            'actual_energyplus_executed':True,'private_original_meteonorm_baseline':True,'production_epw_ready':False,
            'building_model':'EnergyPlus official 1ZoneUncontrolled.idf modified with ideal loads, no glazing, 20/26 C',
            'daylighting_impact_tested':False,'results':outputs}
    (out/'p7c5b_energyplus_full_benchmark_audit.json').write_text(json.dumps(report,indent=2)+'\n')
    if bad:raise RuntimeError('EnergyPlus failed '+str(len(bad))+' weather runs: '+', '.join(bad))
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--energyplus',required=True);p.add_argument('--official-idf',required=True)
    p.add_argument('--baseline',required=True);p.add_argument('--epw-dir',required=True);p.add_argument('--out',required=True)
    p.add_argument('--timeout-s',type=int,default=300);a=p.parse_args();r=run(a)
    print(json.dumps({'real_simulations':r['n_weather_files_executed'],'status':'PASS'},indent=2))