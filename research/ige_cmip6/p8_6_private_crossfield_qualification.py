#!/usr/bin/env python3
"""IGE P8.6: validate 57 actual user-authorized EPWs, independently of reports.

No hourly Meteonorm records or derived licensed EPW bytes are ever exported.
Folder or local ZIP sources supported; missing files FAIL CLOSED.
"""
from __future__ import annotations
import argparse
import collections
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
import zipfile
from pathlib import Path

from p7c5b_solar_illuminance import parse_epw
from p8_5_final_epw_generator_audit import (
    BASELINE_SHA, P7C4_MEMBERS, P7C5B_MEMBERS, read_csv, source_hash,
)

N=8760
FIELDS=35
REVISED=frozenset((16,17,18))
MORPHED=frozenset((6,7,8,12,13,14,15,21,33))
SIGMA=5.670374419e-8
EPS=.621945
MODEL_SOURCE="research/ige_cmip6/results/p7c3_384_monthly_model_signals.csv"
CRITICAL_FIELDS=(6,7,8,9,12,13,14,15,20,21,33)
CALM_MPS=.5
RH_SAT_THRESHOLD=99.995
MAX_PRIVATE_EPW_BYTES=16_000_000


def file_sha(data):
    return hashlib.sha256(data).hexdigest()


def audit_collection(source,expected):
    """Required exact EPW basenames, no unregistered scenario files."""
    src=Path(source)
    if src.is_dir():
        actual=[p.name for p in src.glob("*.epw") if p.is_file()]
    elif src.is_file() and src.suffix.lower()==".zip":
        with zipfile.ZipFile(src) as z:
            actual=[Path(i.filename).name for i in z.infolist()
                    if not i.is_dir() and Path(i.filename).suffix.lower()==".epw"]
    else:
        raise ValueError("P8_6_PRIVATE_SOURCE_MISSING_OR_NOT_DIRECTORY_OR_ZIP")
    if len(actual)!=len(expected) or set(actual)!=set(expected):
        raise ValueError("P8_6_PRIVATE_EXPECTED_EXACTLY_28_REGISTERED_EPW_MEMBERS")
    return {"exact_expected_member_EPWs":True,"n_epws":len(actual)}


def member_bytes(source,name):
    """Only read user-local bytes; archive paths cannot escape or be ambiguous."""
    source=Path(source)
    if source.is_dir():
        file=source/name
        if not file.is_file() or file.parent.resolve()!=source.resolve():
            raise ValueError("P8_6_PRIVATE_MEMBER_MISSING_"+name)
        data=file.read_bytes()
    elif source.is_file() and source.suffix.lower()==".zip":
        with zipfile.ZipFile(source) as z:
            candidates=[i for i in z.infolist()
                        if not i.is_dir() and Path(i.filename).name==name]
            if len(candidates)!=1 or candidates[0].file_size>MAX_PRIVATE_EPW_BYTES:
                raise ValueError("P8_6_PRIVATE_ZIP_MISSING_DUPLICATE_OR_OVERSIZE_"+name)
            data=z.read(candidates[0])
    else:
        raise ValueError("P8_6_PRIVATE_SOURCE_MISSING_OR_NOT_DIRECTORY_OR_ZIP")
    if len(data)>MAX_PRIVATE_EPW_BYTES:
        raise ValueError("P8_6_PRIVATE_EPW_BYTE_CAP")
    return data


def calendar(rows):
    """Typical meteorological years may use different source-year labels."""
    if len(rows)!=N or any(len(r)!=FIELDS for r in rows):
        raise ValueError("P8_6_EPW_8760_X_35_REQUIRED")
    day=dt.date(2001,1,1)
    for i,r in enumerate(rows):
        today=day+dt.timedelta(days=i//24)
        try:
            year,month,mday,hour,minute=[int(r[j]) for j in range(5)]
        except (ValueError,IndexError) as exc:
            raise ValueError("P8_6_INVALID_TMY_HOURLY_TIMESTAMP") from exc
        if not 1800<=year<=2200 or (month,mday,hour,minute)!=(
            today.month,today.day,i%24+1,60):
            raise ValueError("P8_6_TMY_MONTH_DAY_HOUR_ENDING_OR_DST_DRIFT")
    return {"hourly_time_axis_pass":True,"mixed_TMY_year_labels_allowed":True}


def verify_source_pair(base,raw,corrected):
    """The 28 edited sources must be unchanged except registered columns."""
    calendar(base);calendar(raw);calendar(corrected)
    if any(a[:5]!=b[:5] or b[:5]!=c[:5] for a,b,c in zip(base,raw,corrected)):
        raise ValueError("P8_6_BASE_P7C4_P7C5B_TIME_ANCHORS_DIVERGE")
    for i,(a,b,c) in enumerate(zip(base,raw,corrected)):
        if any(a[k]!=b[k] for k in range(FIELDS) if k not in MORPHED):
            raise ValueError(f"P8_6_P7C4_CHANGED_IMMUTABLE_FIELD_AT_{i}")
        if any(b[k]!=c[k] for k in range(FIELDS) if k not in REVISED):
            raise ValueError(f"P8_6_P7C5B_CHANGED_NONPHOTOMETRIC_FIELD_AT_{i}")
    return {"P7C4_allowed_fields_only":True,
            "P7C5B_only_illuminance_16_17_18":True,
            "all_8760_hourly_source_timestamps_identical":True}


def sat_pa(tc):
    """Buck (1981) water-only diagnostic, not an ice-phase psychrometric model."""
    return 611.21*math.exp((18.678-tc/234.5)*tc/(257.14+tc))


def actual_q(tc,rh,pressure_pa):
    vapour=sat_pa(tc)*rh/100.
    return EPS*vapour/(pressure_pa-(1.-EPS)*vapour)


def noaa_coszen_noleap(day_of_year,local_hour_mid,lat_deg,lon_deg,tz_hours):
    """Independent approximate NOAA solar geometry for EPW local STANDARD time.

    Returns geometric cos(zenith) before refraction correction. Calculated
    using day-of-year 1..365; this is a quality-screen reference, NOT the
    exact source P7C4 solar geometry or an independent irradiance observation.
    """
    if not -90<=lat_deg<=90 or not -180<=lon_deg<=180 or not -14<=tz_hours<=14:
        raise ValueError("P8_6_INVALID_EPW_LOCATION_SOLAR_GEOMETRY")
    gamma=2*math.pi/365*(day_of_year-1+(local_hour_mid-12)/24)
    eq=229.18*(.000075+.001868*math.cos(gamma)-.032077*math.sin(gamma)
              -.014615*math.cos(2*gamma)-.040849*math.sin(2*gamma))
    decl=(.006918-.399912*math.cos(gamma)+.070257*math.sin(gamma)
          -.006758*math.cos(2*gamma)+.000907*math.sin(2*gamma)
          -.002697*math.cos(3*gamma)+.00148*math.sin(3*gamma))
    minutes=60*local_hour_mid+eq+4*lon_deg-60*tz_hours
    hour_angle=math.radians(minutes/4-180)
    lat=math.radians(lat_deg)
    return math.sin(lat)*math.sin(decl)+math.cos(lat)*math.cos(decl)*math.cos(hour_angle)


def epw_location(headers):
    if not headers or headers[0][0]!="LOCATION" or len(headers[0])<9:
        raise ValueError("P8_6_EPW_LOCATION_HEADER_MISSING")
    try:
        return tuple(float(headers[0][i]) for i in (6,7,8))
    except (ValueError,IndexError) as exc:
        raise ValueError("P8_6_INVALID_LAT_LONG_STANDARD_TIME_ZONE") from exc


def pearson(xs,ys):
    n=len(xs)
    if n<24:return None
    mx=statistics.fmean(xs);my=statistics.fmean(ys)
    vx=sum((v-mx)**2 for v in xs)
    vy=sum((v-my)**2 for v in ys)
    return sum((a-mx)*(b-my) for a,b in zip(xs,ys))/math.sqrt(vx*vy) if vx>0 and vy>0 else None


def run_lengths(flags):
    streak=0;lengths=[]
    for flag in [*flags,False]:
        if flag:streak+=1
        elif streak:lengths.append(streak);streak=0
    return {"episode_count":len(lengths),
            "maximum_consecutive_hours":max(lengths,default=0),
            "episodes_ge24h":sum(v>=24 for v in lengths),
            "episodes_ge72h":sum(v>=72 for v in lengths)}


def diagnose(rows,reference=None,location=None):
    """Calculate only aggregates; use diagnostic vs impossible-physics flags."""
    calendar(rows)
    if reference is not None:calendar(reference)
    count=collections.Counter()
    month=collections.defaultdict(lambda:collections.defaultdict(list))
    hard=collections.Counter()
    daily_ghi=collections.defaultdict(float)
    dirhist=[0]*16
    sky_cloud_x=[];sky_irr_y=[];longwave_rh_x=[];longwave_rh_y=[]
    humid_flags=[];hot_humid_flags=[];wind_high_flags=[]
    q_values=[]
    prev_rh=None
    for i,r in enumerate(rows):
        m=int(r[1]);day=i//24
        try:
            T,Td,RH,p,L,G,DNI,DHI,luxG,luxD,luxF,zen,angle,speed,cloud,opaque,rain=(
                float(r[k]) for k in (6,7,8,9,12,13,14,15,16,17,18,19,20,21,22,23,33))
        except (IndexError,ValueError) as exc:
            raise ValueError("P8_6_NONNUMERIC_CRITICAL_WEATHER_FIELD") from exc
        if any(not math.isfinite(v) for v in (T,Td,RH,p,L,G,DNI,DHI,angle,speed,rain)):
            hard["nonfinite_critical_record"]+=1;continue
        if not (-70<T<70 and -80<Td<70 and 30000<p<120000 and 0<=RH<=100):
            hard["invalid_temperature_RH_pressure"]+=1;continue
        if Td>T+.15:hard["dewpoint_above_drybulb"]+=1
        rh_check=100*sat_pa(Td)/sat_pa(T)
        if abs(RH-rh_check)>2:hard["RH_dewpoint_Buck_disagreement_gt2pp"]+=1
        q=actual_q(T,RH,p)
        if not math.isfinite(q) or not 0<=q<.1:hard["invalid_specific_humidity"]+=1
        if any(v<-.00001 or v>=9999 for v in (G,DNI,DHI)):
            hard["invalid_solar_irradiance"]+=1
        if DHI>G+2:hard["diffuse_exceeds_global"]+=1
        if DNI>20 and G-DHI>2:
            cos=(G-DHI)/DNI
            if cos<-.02 or cos>1.02:hard["unphysical_solar_cosine"]+=1
            count["solar_cosine_scored_hours"]+=1
            if all(0<=a<999999 for a in (luxG,luxD,luxF)):
                err=abs(luxG-(luxF+luxD*cos))
                count["illuminance_closure_scored_hours"]+=1
                if err>2:hard["illuminance_GHI_DNI_DHI_closure_gt2lux"]+=1
                month[m]["luminous_err"].append(err)
        if location is not None:
            latitude,longitude,tz=location
            cosastr=noaa_coszen_noleap(day+1,(i%24)+.5,latitude,longitude,tz)
            if G>20 and cosastr<-.1:
                hard["nontrivial_solar_energy_at_astronomical_night"]+=1
            if DNI>20 and G>20 and cosastr>.08:
                count["independent_astro_sun_angle_scored_hours"]+=1
                err=abs((G-DHI)-DNI*cosastr)
                month[m]["independent_astro_GHI_diffuse_beam_abs_residual_Wm2"].append(err)
                if err>max(35.,.10*G):
                    count["independent_astro_radiation_projection_mismatch_diagnostic_hours"]+=1
        if G>20 and DNI<.1:count["diffuse_or_overcast_daylight_hours"]+=1
        if L<=0 or L>=9999:
            count["sky_longwave_missing_or_invalid_hours"]+=1
        else:
            epsilon=L/(SIGMA*(T+273.15)**4)
            if epsilon<.35 or epsilon>1.3:count["sky_emissivity_extreme_diagnostic_hours"]+=1
            month[m]["sky_eff"].append(epsilon)
            month[m]["sky_effective_T"].append((L/SIGMA)**.25-273.15)
            longwave_rh_x.append(L);longwave_rh_y.append(RH)
        if cloud==99 or opaque==99:
            count["cloud_opaque_missing_hours"]+=1
        elif not (0<=cloud<=10 and 0<=opaque<=10):
            hard["invalid_cloud_cover_0_to_10"]+=1
        else:
            if opaque>cloud+1:count["opaque_exceeds_total_1tenth_diagnostic"]+=1
            if G>10:
                sky_cloud_x.append(cloud)
                sky_irr_y.append(DHI/max(G,1))
        if speed<0 or speed>=999:
            hard["invalid_wind_speed"]+=1
        if angle!=999 and not 0<=angle<=360:
            hard["invalid_wind_direction"]+=1
        if speed>=CALM_MPS and angle==999:
            hard["missing_noncalm_FROM_azimuth"]+=1
        if speed>=CALM_MPS and angle!=999:
            dirhist[int(((angle%360+11.25)%360)//22.5)]+=1
        if rain<0 or rain>=999:
            hard["invalid_precipitation_depth"]+=1
        if zen>=9999:count["zenith_luminance_missing_hours"]+=1
        if RH>=RH_SAT_THRESHOLD:count["RH_ge99p995_hours"]+=1
        if abs(RH-100.)<=.00101:count["P7C4_legacy_np_isclose_near100_hours"]+=1
        saturated=RH>=RH_SAT_THRESHOLD
        humid_flags.append(saturated)
        hot_humid_flags.append(T>=30 and RH>=70)
        wind_high_flags.append(speed>=5)
        if prev_rh is not None and abs(RH-prev_rh)>20:count["hourly_RH_jump_gt20pp"]+=1
        prev_rh=RH
        if rain>.01:count["wet_hours"]+=1
        if speed<CALM_MPS:count["calm_hours"]+=1
        if T>=30:count["hot_ge30C_hours"]+=1
        q_values.append(q)
        daily_ghi[day]+=max(G,0)/1000.
        for name,value in (("q",q),("rh",RH),("t",T),("Td",Td),("p",p),
                           ("ghi",G),("dni",DNI),("dhi",DHI),
                           ("speed",speed),("rain",rain)):
            month[m][name].append(value)
    if len(q_values)!=N:
        hard["missing_or_invalid_critical_hours"]=N-len(q_values)
    if reference is not None:
        count["historical_cloud_hours_inherited"]=sum(
            r[22]==b[22] and r[23]==b[23] for b,r in zip(reference,rows))
        count["historical_wind_direction_hours_inherited"]=sum(
            r[20]==b[20] for b,r in zip(reference,rows))
        count["historical_rain_occurrence_hours_inherited"]=sum(
            (float(r[33])>0)==(float(b[33])>0) for b,r in zip(reference,rows))
        count["baseline_calm_promoted_with_inherited_direction"]=sum(
            float(b[21])<CALM_MPS<=float(r[21]) for b,r in zip(reference,rows))
        if count["baseline_calm_promoted_with_inherited_direction"]:
            hard["source_calm_direction_promoted_to_noncalm_unqualified"]=(
                count["baseline_calm_promoted_with_inherited_direction"])
        count["historical_precipitation_occurrence_changed_hours"]=sum(
            (float(r[33])>0)!=(float(b[33])>0) for b,r in zip(reference,rows))
        if count["historical_precipitation_occurrence_changed_hours"]:
            hard["historical_rain_event_occurrence_changed"]=(
                count["historical_precipitation_occurrence_changed_hours"])
    bymonth={}
    for m in range(1,13):
        values=month[m]
        bymonth[str(m)]={k:statistics.fmean(v) if v else None
                         for k,v in values.items()}
        bymonth[str(m)]["hours"]=len(values["q"])
    count["source_hourly_fields_scored"]=len(q_values)
    return {
        "critical_physics_failures":dict(hard),
        "critical_physics_pass":not any(hard.values()),
        "diagnostics":dict(count),
        "RH_ge99p995_episode_statistics":run_lengths(humid_flags),
        "hot_Tge30_RHge70_episode_statistics":run_lengths(hot_humid_flags),
        "strong_wind_ge5_episode_statistics":run_lengths(wind_high_flags),
        "monthly_means":bymonth,
        "annual_GHI_kwh_m2":sum(daily_ghi.values()),
        "annual_q_mean_kgkg":statistics.fmean(q_values) if q_values else None,
        "cloud_fraction_vs_daytime_diffuse_fraction_pearson":pearson(sky_cloud_x,sky_irr_y),
        "horizontal_IR_vs_RH_pearson":pearson(longwave_rh_x,longwave_rh_y),
        "resolved_wind_from_rose_16_sector_counts":dirhist,
        "physical_independent_irradiance_or_luminous_measurements_used":False,
        "native_hourly_weather_source_measurements_authentic":False,
    }


def read_registered_ratios():
    table=read_csv(MODEL_SOURCE)
    r={}
    for x in table:
        key=x["model"],x["window"],int(x["month"])
        if key in r:raise ValueError("P8_6_DUPLICATE_MODEL_WINDOW_MONTH")
        r[key]=x
    if len(r)!=384:raise ValueError("P8_6_REGISTERED_GCM_SIGNAL_CENSUS_NOT_384")
    return r


def monthly_ratio_closure(base,corrected,model,window,signals):
    monthly=[]
    for month in range(1,13):
        idx=[i for i in range(N) if int(base[i][1])==month]
        s=signals[(model,window,month)]
        bw=statistics.fmean(float(base[i][21]) for i in idx)
        cw=statistics.fmean(float(corrected[i][21]) for i in idx)
        bq=statistics.fmean(actual_q(float(base[i][6]),float(base[i][8]),float(base[i][9])) for i in idx)
        fq=statistics.fmean(actual_q(float(corrected[i][6]),float(corrected[i][8]),float(corrected[i][9])) for i in idx)
        base_ghi=sum(float(base[i][13]) for i in idx)
        future_ghi=sum(float(corrected[i][13]) for i in idx)
        ewind=abs(cw-bw*float(s["wind_ratio"]))
        eq=abs(fq-bq*float(s["huss_ratio"]))
        eghi=abs(future_ghi-base_ghi*float(s["ghi_ratio"]))/1000.
        monthly.append({
            "month":month,"wind_mean_factor_abs_mps":ewind,
            "monthly_q_ratio_abs_kgkg":eq,
            "monthly_GHI_expected_vs_actual_abs_kwh_m2":eghi,
        })
    return monthly


def verify_original_bundle(baseline,raw_dir,corrected_dir,out):
    base_bytes=Path(baseline).read_bytes()
    if file_sha(base_bytes)!=BASELINE_SHA:
        raise ValueError("P8_6_AUTHENTIC_METEONORM_BASELINE_SHA_MISMATCH")
    base_header,base=parse_epw(base_bytes);calendar(base)
    location=epw_location(base_header)
    original=read_csv(P7C4_MEMBERS)
    corrected=read_csv(P7C5B_MEMBERS)
    by_source={m["source_p7c4_sha256"]:m for m in corrected}
    if len(original)!=28 or len(corrected)!=28 or len(by_source)!=28:
        raise ValueError("P8_6_REQUIRED_28_ORIGINAL_AND_28_CORRECTED_SOURCES")
    if {m["EPW_sha256"] for m in original}!={m["source_p7c4_sha256"] for m in corrected}:
        raise ValueError("P8_6_P7C5B_P7C4_SOURCE_SHA_BIJECTION_FAILED")
    audit_collection(raw_dir,{m["EPW_filename"] for m in original})
    audit_collection(corrected_dir,{m["filename"] for m in corrected})
    signal=read_registered_ratios()
    base_diag=diagnose(base)
    all_result=[]
    for index,m in enumerate(original,1):
        raw_bytes=member_bytes(raw_dir,m["EPW_filename"])
        if file_sha(raw_bytes)!=m["EPW_sha256"]:
            raise ValueError("P8_6_P7C4_ORIGINAL_EPW_SHA_MISMATCH_"+m["EPW_filename"])
        corr=by_source[m["EPW_sha256"]]
        corrected_bytes=member_bytes(corrected_dir,corr["filename"])
        if file_sha(corrected_bytes)!=corr["output_sha256"]:
            raise ValueError("P8_6_P7C5B_CORRECTED_EPW_SHA_MISMATCH_"+corr["filename"])
        raw_h,raw=parse_epw(raw_bytes)
        corr_h,rev=parse_epw(corrected_bytes)
        source_check=verify_source_pair(base,raw,rev)
        if raw_h!=corr_h:
            raise ValueError("P8_6_PHOTOMETRIC_CORRECTION_CHANGED_EPW_HEADERS")
        if epw_location(raw_h)!=location or raw_h[3]!=base_header[3]:
            raise ValueError("P8_6_LOCATION_OR_GROUND_TEMPERATURE_PROVENANCE_DRIFT")
        a=diagnose(rev,reference=base,location=location)
        monthly=monthly_ratio_closure(base,rev,m["model"],m["window"],signal)
        largest={
            "q":max(x["monthly_q_ratio_abs_kgkg"] for x in monthly),
            "wind":max(x["wind_mean_factor_abs_mps"] for x in monthly),
            "GHI":max(x["monthly_GHI_expected_vs_actual_abs_kwh_m2"] for x in monthly),
        }
        if largest["q"]>1e-9:
            a["critical_physics_failures"]["monthly_specific_humidity_GCM_ratio_not_closed"]=1
        if largest["wind"]>.002:
            a["critical_physics_failures"]["monthly_wind_mean_GCM_ratio_not_closed"]=1
        if largest["GHI"]>.02:
            a["critical_physics_failures"]["monthly_GHI_GCM_ratio_not_closed"]=1
        a["critical_physics_pass"]=not any(a["critical_physics_failures"].values())
        all_result.append({
            "model":m["model"],"window":m["window"],
            "p7c4_original_EPW_sha256":m["EPW_sha256"],
            "p7c5b_corrected_EPW_sha256":corr["output_sha256"],
            "source_edit_invariants":source_check,
            "GCM_monthly_closure_max_abs_error":largest,
            "cross_variable_QC":a,
            "current_optimizer_strict_convergence_proven":False,
            "independent_wind_future_direction_proven":False,
            "independent_luminous_efficacy_validation_proven":False,
        })
        print(f"P8_6_PRIV  [{index:02d}/28] {m['model']} {m['window']} | "
              f"critical_physical_pass={a['critical_physics_pass']}",flush=True)
    physical_pass=all(x["cross_variable_QC"]["critical_physics_pass"] for x in all_result)
    result={
        "phase":"IGE_P8_6_PRIVATE_57_ORIGINAL_EPW_READBACK",
        "original_licensed_Meteonorm_57_files_physically_read":True,
        "expected_original_baseline_sha256":BASELINE_SHA,
        "required_original_P7C4_members":28,
        "required_corrected_P7C5B_members":28,
        "strict_original_28_vs_corrected_28_sha_validation_pass":True,
        "critical_crossfield_physical_pass_all_28":physical_pass,
        "research_physics_qualification_pass":physical_pass and base_diag["critical_physics_pass"],
        "humidity_optimizer_convergence_independently_proven":False,
        "independent_photometric_sky_measurements_verified":False,
        "all_28_native_EnergyPlus_simulations_executed_here":False,
        "future_wind_direction_physically_projected":False,
        "production_epw_ready":False,
        "baseline_crossfield_QC":base_diag,
        "members":all_result,
        "licensed_hourly_EPWs_in_report":False,
    }
    p=Path(out);p.mkdir(parents=True,exist_ok=True)
    (p/"p8_6_original_28_plus_28_crossfield_aggregates.json").write_text(
        json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",
        encoding="utf-8")
    print("IGE_P8_6",json.dumps({
        "n_originals":28,"n_corrected":28,
        "original_real_file_hashes_pass":True,
        "critical_crossfield_pass":physical_pass,
        "production_epw_ready":False
    }),flush=True)
    return result


def public_research_smoke(path,out):
    """A real archived file, explicitly NEVER a substitute for 57 licensed bytes."""
    bytes_=Path(path).read_bytes()
    headers,rows=parse_epw(bytes_)
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    x=diagnose(rows,location=epw_location(headers))
    report={
        "phase":"IGE_P8_6_PUBLIC_RESEARCH_SMOKE_ONLY",
        "source_epw_sha256":file_sha(bytes_),
        "actual_licensed_Meteonorm_originals_validated":0,
        "actual_licensed_Meteonorm_corrected_validated":0,
        "source_is_synthetic_weather_with_wind_analogue":True,
        "scientific_original_57_file_gate_pass":False,
        "public_crossfield_diagnostics":x,
        "production_epw_ready":False,
    }
    (out/"p8_6_public_only_smoke.json").write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")
    print("IGE_P8_6_PUBLIC_SMOKE",json.dumps({
        "actual_hourly_rows":8760,
        "source_is_proprietary_Meteonorm":False,
        "crossfield_pass":x["critical_physics_pass"],
        "private_source_validated":False,
    }))
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--baseline")
    p.add_argument("--p7c4-original-dir-or-zip")
    p.add_argument("--p7c5b-corrected-dir-or-zip")
    p.add_argument("--public-research-smoke")
    p.add_argument("--out",required=True)
    opts=p.parse_args()
    if opts.public_research_smoke:
        if opts.baseline or opts.p7c4_original_dir_or_zip or opts.p7c5b_corrected_dir_or_zip:
            p.error("public research smoke must not mix with private licensed sources")
        public_research_smoke(opts.public_research_smoke,opts.out)
    else:
        if not all((opts.baseline,opts.p7c4_original_dir_or_zip,opts.p7c5b_corrected_dir_or_zip)):
            p.error("P8.6 original private validation needs ALL 57 source bytes")
        result=verify_original_bundle(opts.baseline,opts.p7c4_original_dir_or_zip,
                                      opts.p7c5b_corrected_dir_or_zip,opts.out)
        if not result["research_physics_qualification_pass"]:
            raise SystemExit(
                "P8_6_PRIVATE_CROSSFIELD_SCIENTIFIC_BLOCKED: "
                "source-integrity passed but critical physical diagnostics "
                "failed; review the aggregate report (exit=2).")
