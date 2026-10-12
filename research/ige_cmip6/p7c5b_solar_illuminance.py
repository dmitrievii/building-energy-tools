#!/usr/bin/env python3
"""P7C.5B — source-referenced radiometric–photometric EPW coherence.

Research method: keep baseline hourly/monthly direct and diffuse luminous efficacies;
recompose horizontal illuminance from physical irradiance projection. Original
Meteonorm data are never overwritten. Research-only: source baseline is an
empirical sky model, not measured sky luminance. No fabricated zenith luminance.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, math, statistics, zipfile
from pathlib import Path

GLOBAL_RAD,DIRECT_RAD,DIFFUSE_RAD=13,14,15
GLOBAL_LUX,DIRECT_LUX,DIFFUSE_LUX,ZENITH_LUMINANCE=16,17,18,19
ILLUMINANCE_FIELDS=(GLOBAL_LUX,DIRECT_LUX,DIFFUSE_LUX)


def sha(data:bytes):return hashlib.sha256(data).hexdigest()

def parse_epw(data:bytes):
    text=data.decode('utf-8-sig',errors='strict');lines=text.splitlines(keepends=True)
    if len(lines)!=8768:raise ValueError(f'EPW must have 8 header lines and 8760 hourly rows; got {len(lines)}')
    fields=list(csv.reader(lines));
    if any(len(row)!=35 for row in fields[8:]):raise ValueError('EPW requires 35 columns in each weather row')
    return fields[:8],fields[8:]

def encode_epw(headers,rows):
    sio=io.StringIO(newline='');w=csv.writer(sio,lineterminator='\n');w.writerows(headers+rows);return sio.getvalue().encode('utf-8')

def expected_efficiency(base_rows,rad_col,lux_col):
    """Prefer authentic *hourly* efficacy, monthly robust backup when undefined.

    Units: lux/(W/m2). Efficiencies outside 2..220 are rejected as
    degenerate input for *fallback*, not silently capped for valid hours.
    """
    months=[int(r[1]) for r in base_rows];ratios=[[] for _ in range(13)];all_valid=[]
    for r,month in zip(base_rows,months):
        rad=float(r[rad_col]);lux=float(r[lux_col]);
        if rad>=10 and lux>=0:
            eff=lux/rad
            if 2<=eff<=220:
                ratios[month].append(eff);all_valid.append(eff)
    if len(all_valid)<30:raise ValueError('Insufficient measured/source-derived luminous efficacy samples')
    med=statistics.median(all_valid)
    monthly={m:statistics.median(ratios[m]) if len(ratios[m])>=5 else med for m in range(1,13)}
    return monthly,med

def corrected_illuminance(baseline_data:bytes,future_data:bytes,expected_baseline_sha:str,expected_future_sha:str):
    if sha(baseline_data)!=expected_baseline_sha:raise ValueError('Baseline EPW source SHA-256 mismatch')
    if sha(future_data)!=expected_future_sha:raise ValueError('Future EPW P7C.4 source SHA-256 mismatch')
    hb,baseline=parse_epw(baseline_data);hf,future=parse_epw(future_data)
    if [r[:4] for r in baseline]!=[r[:4] for r in future]:raise ValueError('EPW date/hour order differs')
    if hb[0][:2]!=hf[0][:2]:raise ValueError('LOCATION mismatch')
    # No change to weather/solar fields other than declared illuminance 16,17,18.
    fallback_b,b_med=expected_efficiency(baseline,DIRECT_RAD,DIRECT_LUX)
    fallback_d,d_med=expected_efficiency(baseline,DIFFUSE_RAD,DIFFUSE_LUX)
    out=[r.copy() for r in future]
    fallback_count=0;twilight_count=0;max_closure=0.;changed=0;daylight_count=0
    for i,(base,old,new) in enumerate(zip(baseline,future,out)):
        month=int(base[1]);bg,bd,bf=[float(base[k]) for k in (GLOBAL_RAD,DIRECT_RAD,DIFFUSE_RAD)]
        fg,fd,ff=[float(old[k]) for k in (GLOBAL_RAD,DIRECT_RAD,DIFFUSE_RAD)]
        if min(fg,fd,ff)<0:raise ValueError(f'Negative solar energy at hour {i}')
        if fg+1.1<ff:raise ValueError('Invalid irradiance geometry: diffuse exceeds global')
        if fd>0:
            cosz=(fg-ff)/fd
            if cosz< -0.002 or cosz>1.002:raise ValueError(f'Nonphysical inferred cos(solar zenith) at {i}: {cosz}')
            cosz=max(0.,min(1.,cosz))
        else:
            if abs(fg-ff)>1.01:raise ValueError('GHI and DHI differ without beam')
            cosz=0.
        daylight_count+=int(fg>0.5)
        # Preserve source twilight when all irradiance channels in both files are 0:
        # source illuminance can remain positive at sub-hourly near-horizon conditions.
        if max(bg,bd,bf,fg,fd,ff)<0.51:
            twilight_count+=int(float(base[GLOBAL_LUX])>0)
            new[GLOBAL_LUX]=base[GLOBAL_LUX]
            new[DIRECT_LUX]=base[DIRECT_LUX]
            new[DIFFUSE_LUX]=base[DIFFUSE_LUX]
            continue
        def transformed(rad_future,rad_orig,lum_orig,month_eff):
            nonlocal_dummy=None
            if rad_future<=0:return 0,False
            eff=float(lum_orig)/rad_orig if rad_orig>=10 else float('nan')
            if not (math.isfinite(eff) and 2<=eff<=220):return int(round(rad_future*month_eff)),True
            return int(round(rad_future*eff)),False
        dl,fb=transformed(fd,bd,base[DIRECT_LUX],fallback_b[month]);fl,fc=transformed(ff,bf,base[DIFFUSE_LUX],fallback_d[month]);fallback_count+=int(fb)+int(fc)
        gl=max(fl,int(round(fl+dl*cosz)))
        new[GLOBAL_LUX]=str(gl);new[DIRECT_LUX]=str(dl);new[DIFFUSE_LUX]=str(fl)
        max_closure=max(max_closure,abs(gl-(fl+dl*cosz)))
        changed+=int(any(new[k]!=old[k] for k in ILLUMINANCE_FIELDS))
        if new[ZENITH_LUMINANCE]!=old[ZENITH_LUMINANCE]:raise ValueError('Forbidden zenith luminance synthesis')
    if any(any(new[j]!=old[j] for j in range(35) if j not in ILLUMINANCE_FIELDS) for old,new in zip(future,out)):
        raise ValueError('Unauthorized EPW weather-field mutation')
    report={'source_baseline_sha256':expected_baseline_sha,'source_p7c4_sha256':expected_future_sha,
            'changed_hour_count':changed,'photometric_closure_residual_max_lux':max_closure,
            'fallback_channel_hours':fallback_count,'source_twilight_positive_lux_hours_preserved':twilight_count,
            'future_daylight_radiation_hours':daylight_count,'baseline_beam_efficiency_median_lux_per_Wm2':b_med,
            'baseline_diffuse_efficiency_median_lux_per_Wm2':d_med,
            'zenith_luminance_preserved_missing':all(float(r[ZENITH_LUMINANCE])==9999 for r in baseline),
            'research_only':True,'production_daylight_qualified':False,
            'caveat':'Photometric components reconstructed from Meteonorm source efficacy, not validated against independent measurements'}
    return encode_epw(hf,out),report


def process_archive(baseline_path,source_zip,output_dir):
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    data=Path(baseline_path).read_bytes();base_sha=sha(data)
    with zipfile.ZipFile(source_zip) as z:
        manifest=json.loads(z.read('manifest_sha256.json'))
        names=sorted(n for n in z.namelist() if n.startswith('epw/') and n.endswith('.epw'))
        if len(names)!=28:raise ValueError('Not exactly 28 P7C.4 EPW members')
        summaries=[]
        for name in names:
            orig=z.read(name);q=sha(orig)
            if manifest.get(name)!=q:raise ValueError('Original archive manifest SHA mismatch: '+name)
            new,audit=corrected_illuminance(data,orig,base_sha,q)
            a=output/Path(name).name.replace('P7C4_HOURLY_ENSEMBLE_RESEARCH_ONLY','P7C5B_SOLAR_ILLUMINANCE_RESEARCH_ONLY')
            a.write_bytes(new)
            audit.update({'filename':a.name,'output_sha256':sha(new)})
            summaries.append(audit)
        with (output/'p7c5b_photometric_28_summary.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,summaries[0]);w.writeheader();w.writerows(summaries)
        (output/'p7c5b_photometric_science_audit.json').write_text(json.dumps({'n':28,'baseline_sha256':base_sha,'members':summaries,'energyplus_actual_simulation_executed':False,'solar_luminous_model_independently_validated':False,'production_epw_ready':False},indent=2)+'\n')
    return summaries

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--baseline',required=True);p.add_argument('--source-zip',required=True);p.add_argument('--out',required=True)
    a=p.parse_args();x=process_archive(a.baseline,a.source_zip,a.out)
    print(json.dumps({'members':len(x),'hours_changed':sum(a['changed_hour_count'] for a in x),'maximum_illuminance_closure_lux':max(a['photometric_closure_residual_max_lux'] for a in x)},indent=2))