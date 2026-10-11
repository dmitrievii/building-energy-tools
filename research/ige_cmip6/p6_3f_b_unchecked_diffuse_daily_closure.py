#!/usr/bin/env python3
"""P6.3F-B: keep unchecked q21=0 GeoSphere diffuse radiation as PROVISIONAL evidence.

Original source status 0 means *ungeprüfte Daten*, not "falsch". Numerical
research may use complete unchecked solar measurements, provided source
uncertainty, comparison tier and physical screens remain visible.

Research only. No provider rewriting, infill, licence changes, DNI "ground
measurements", post-hoc timestamp optimization or EPW production.
"""
from __future__ import annotations
import argparse,csv,gzip,hashlib,json,math
from collections import Counter,defaultdict
from datetime import date,datetime,timedelta,timezone
from pathlib import Path
from statistics import fmean

from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union
from p6_3e_hourly_solar_components_arad import solar_cos_zenith
from p6_3f_geosphere_open_10min_solar_qc import (
    decode_year,nasa_reference,metric,parse_utc,STATIONS,SOLAR,QC_ACCEPTED,
    YEARS,SEASONS,WINDOWS,START,END,
)

TIMESTAMPS_SUPPORTED=("record_start","record_end")
SOLAR_SOURCE_STATION=30
SAMPLES_PER_HOUR=6
DAY_SLOTS=24
RECORD_DELTA=timedelta(minutes=10)
MAX_DIFFUSE_EXCESS_WM2=20.0
MAX_DIFFUSE_EXCESS_FRACTION=.05
DAYLIGHT_COS_THRESHOLD=.05
DEEP_NIGHT_COS_THRESHOLD=-.05
NIGHT_EXCESS_KWH=.02
DNI_ANGLE_MIN_COS=.20
SCIENCE_TIERS=(
    "QC_CONFIRMED",
    "COMPLETE_UNCHECKED_Q0",
    "COMPLETE_MIXED_Q0_QC",
    "PARTIAL_OR_MISSING",
    "UNRECOGNIZED_OR_REJECTED_FLAG",
)

def tier(samples,field):
    """Original data availability and source QA status; not an accuracy score."""
    if len(samples)!=SAMPLES_PER_HOUR:
        return "PARTIAL_OR_MISSING"
    vals=[r[field] for r in samples]
    flags=[r[field+"_flag"] for r in samples]
    if any(x is None for x in vals):
        return "PARTIAL_OR_MISSING"
    if all(f in QC_ACCEPTED for f in flags):
        return "QC_CONFIRMED"
    if all(f==0 for f in flags):
        return "COMPLETE_UNCHECKED_Q0"
    if all(f in QC_ACCEPTED or f==0 for f in flags):
        return "COMPLETE_MIXED_Q0_QC"
    return "UNRECOGNIZED_OR_REJECTED_FLAG"

def valid_values(samples,field):
    """Research utility: q0 can be used but never promoted to QC approved."""
    return len(samples)==SAMPLES_PER_HOUR and all(
        r[field] is not None and
        (r[field+"_flag"] in QC_ACCEPTED or r[field+"_flag"]==0)
        for r in samples)

def hourly_energy(samples,field):
    if not valid_values(samples,field):
        return None
    # 6 ten-minute averaged irradiances W/m² ×(1/6 hour)/1000.
    return sum(r[field] for r in samples)/6000.0

def physical_screens(ghi,dhi,coszen):
    """Transparent non-normative radiative plausibility flags, no alterations."""
    if ghi is None or dhi is None:
        return {"assessable":False,"suspect":False,
                "negative_beyond_5W":None,
                "diffuse_above_global":None,
                "deep_night_diffuse_above_20W":None,
                "deep_night_global_above_20W":None}
    # hourly integrated kWh/m²; 5 and 20 W/m² are 0.005 and 0.020
    # kWh/m² for an hour, respectively.
    negative=min(ghi,dhi)<-.005
    above=(dhi>ghi+max(MAX_DIFFUSE_EXCESS_WM2/1000,
                       MAX_DIFFUSE_EXCESS_FRACTION*max(ghi,0)))
    night_dhi=coszen<DEEP_NIGHT_COS_THRESHOLD and dhi>NIGHT_EXCESS_KWH
    night_ghi=coszen<DEEP_NIGHT_COS_THRESHOLD and ghi>NIGHT_EXCESS_KWH
    return {"assessable":True,
            "suspect":negative or above or night_dhi or night_ghi,
            "negative_beyond_5W":negative,
            "diffuse_above_global":above,
            "deep_night_diffuse_above_20W":night_dhi,
            "deep_night_global_above_20W":night_ghi}

def original_sources(source_dir):
    """Graz COMBINED station #30 only, child #16412 was identical in prior audit."""
    report_path=source_dir/"p6_3f_open_10min_scientific_audit.json"
    original_index=source_dir/"p6_3f_geosphere_10min_source_hashes.csv"
    if not report_path.is_file() or not original_index.is_file():
        raise FileNotFoundError("Original P6.3F first-stage provenance missing")
    report=json.loads(report_path.read_text(encoding="utf8"))
    if checksum(original_index)!=report["derived_file_sha256"][original_index.name]:
        raise ValueError("Original GeoSphere per-year source SHA index modified")
    if report["requested_stations"]!=list(STATIONS) or \
       report["requested_years"]!=list(YEARS):
        raise ValueError("GeoSphere 10min frozen source station/year identity drift")
    entries=list(csv.DictReader(original_index.open("r",encoding="utf8",newline="")))
    indexed={}
    for r in entries:
        key=(int(r["station_id"]),int(r["year"]))
        if key in indexed:raise ValueError("Duplicate source station-year provenance")
        indexed[key]=r
    by_year={};source_checks=[]
    for y in YEARS:
        provenance=indexed.get((SOLAR_SOURCE_STATION,y))
        if provenance is None:raise FileNotFoundError(f"Original Graz 30 {y} missing")
        raw_path=source_dir/provenance["source_file"]
        decompressed=gzip.decompress(raw_path.read_bytes())
        raw_sha=hashlib.sha256(decompressed).hexdigest()
        if raw_sha!=provenance["uncompressed_original_sha256"]:
            raise ValueError("Immutable GeoSphere original provider byte SHA mismatch")
        data=json.loads(decompressed)
        rows,counts=decode_year(data,SOLAR_SOURCE_STATION,y)
        if int(provenance["raw_record_count"])!=len(rows):
            raise ValueError("Original provider 10min calendar cardinality drift")
        by_year[y]=rows
        source_checks.append({"station_id":30,"year":y,
            "original_provider_sha256":raw_sha,
            "provider_url":provenance["original_url"],
            "original_raw_rows":len(rows),
            "unchecked_chim_values":sum(
                r["chim"] is not None and r["chim_flag"]==0 for r in rows),
            "accepted_cglo_values":sum(r["cglo_accepted"] for r in rows)})
    return by_year,source_checks,report

def hourly_from_original(by_year,window):
    if window not in TIMESTAMPS_SUPPORTED:
        raise ValueError("Unknown ten-minute mean time-label hypothesis")
    groups=defaultdict(list)
    count=0
    for y,rows in sorted(by_year.items()):
        for r in rows:
            stamp=r["timestamp"]-(RECORD_DELTA if window=="record_end"
                                   else timedelta())
            hour=stamp.replace(minute=0,second=0,microsecond=0)
            # Retain boundary sample but never invent adjacent year.
            if START<=hour<END:
                groups[hour].append(r)
            count+=1
    if count!=sum(len(x) for x in by_year.values()):
        raise ValueError("Ten-minute observations lost when assembling")
    expected=int((END-START).total_seconds()/3600)
    result={}
    for i in range(expected):
        hour=START+timedelta(hours=i)
        records=groups.get(hour,[])
        # Verify six distinct native timestamps exactly on nominated support.
        base=hour+(RECORD_DELTA if window=="record_end" else timedelta())
        expected_stamps={base+RECORD_DELTA*i for i in range(SAMPLES_PER_HOUR)}
        if len(records)!=6 or {r["timestamp"] for r in records}!=expected_stamps:
            records=[]
        g=tier(records,"cglo");h=tier(records,"chim")
        ghi=hourly_energy(records,"cglo")
        dhi=hourly_energy(records,"chim")
        cosz=solar_cos_zenith(hour,47.07767,15.44892)
        flags=physical_screens(ghi,dhi,cosz)
        paired=ghi is not None and dhi is not None
        result[hour]={
          "hour":hour,"window":window,"source_ten_minute_count":len(records),
          "ghi_tier":g,"dhi_tier":h,"ghi_kwh_m2":ghi,"dhi_kwh_m2":dhi,
          "paired_source_complete":paired,"coszen_noaa_mid_hour":cosz,
          **flags,"provisional_dhi_usable_for_exploration":
              paired and not flags["suspect"] and h in
              ("COMPLETE_UNCHECKED_Q0","COMPLETE_MIXED_Q0_QC"),
          "source_qc_approved_dhi":h=="QC_CONFIRMED",
          "ground_dni_measured":False}
    return result

def original_daily_accepted(d_archive):
    csvfile=d_archive/"p6_3d_power_vs_geosphere_daily_2005_2014_two_utc_windows.csv"
    reportfile=d_archive/"p6_3d_hourly_independent_validation_science_audit.json"
    report=json.loads(reportfile.read_text(encoding="utf8"))
    if checksum(csvfile)!=report["output_sha256"][csvfile.name]:
        raise ValueError("Frozen daily official GeoSphere GHI source SHA mismatch")
    result={}
    with csvfile.open("r",newline="",encoding="utf8") as f:
        for r in csv.DictReader(f):
            if r["site"]!="graz_station30" or r["window"]!="geosphere_23_23UTC":
                continue
            if r["valid_day"]!="True":continue
            day=date.fromisoformat(r["date"])
            if day in result:raise ValueError("Duplicate official QC daily solar day")
            result[day]=float(r["official_ghi_kwh_m2_day"])
    if len(result)!=3652:
        raise ValueError("Expected original approved GeoSphere 2005–14 daily GHI")
    return result,checksum(csvfile)

def daily_closure(hours,official):
    """Official daily solar labels D = [D-1 23 UTC, D 23 UTC); same provider.

    This is an INTERNAL CONSISTENCY diagnostic, not independent ground truth.
    """
    results=[]
    for day,accepted in sorted(official.items()):
        utc_start=datetime(day.year,day.month,day.day,tzinfo=timezone.utc)-timedelta(hours=1)
        subset=[hours.get(utc_start+timedelta(hours=i)) for i in range(24)]
        all_present=all(r is not None and r["ghi_kwh_m2"] is not None for r in subset)
        full_qc=all_present and all(r["ghi_tier"]=="QC_CONFIRMED" for r in subset)
        amount=sum(r["ghi_kwh_m2"] for r in subset) if all_present else None
        results.append({
          "date":day.isoformat(),"year":day.year,"month":day.month,
          "source_day_window":"GeoSphere cglo_j 23:00 previous UTC to 23:00 labelled UTC",
          "hypothesis":hours[START]["window"],
          "daily_provider_approved_kwh_m2":accepted,
          "tenminute_reconstructed_all_24_hours":all_present,
          "tenminute_reconstructed_qc_confirmed_day":full_qc,
          "tenminute_reconstructed_kwh_m2":amount,
          "tenminute_minus_daily_kwh_m2":amount-accepted if amount is not None else None,
          "same_provider_not_independent_ground":True})
    return results

def annual_daily_closure_screen(daily_rows):
    """Source-internal disagreement does not mean either instrument is false.

    Threshold 0.10 kWh/m²/day mean absolute signed bias: a transparent
    exploratory screen, not official QC pass/fail or legal calibration.
    """
    annual=[]
    for hypothesis in TIMESTAMPS_SUPPORTED:
        for year in YEARS:
            days=[r for r in daily_rows if r["hypothesis"]==hypothesis
                  and r["year"]==year]
            qualified=[r for r in days
                       if r["tenminute_reconstructed_qc_confirmed_day"]]
            available=[r for r in days
                       if r["tenminute_reconstructed_all_24_hours"]]
            diffs=[r["tenminute_minus_daily_kwh_m2"] for r in qualified]
            official=sum(r["daily_provider_approved_kwh_m2"] for r in qualified)
            reconstructed=sum(r["tenminute_reconstructed_kwh_m2"]
                              for r in qualified)
            bias=fmean(diffs) if diffs else None
            annual.append({
               "year":year,"hypothesis":hypothesis,
               "original_daily_qc_day_count":len(days),
               "matched_complete_raw_days":len(available),
               "matched_full_10min_qc_days":len(qualified),
               "qc_matched_daily_bias_10min_minus_daily_kwh_m2_day":bias,
               "qc_matched_daily_mae_kwh_m2_day":
                   fmean(abs(d) for d in diffs) if diffs else None,
               "tenminute_total_same_matched_days_kwh_m2":reconstructed,
               "daily_total_same_matched_days_kwh_m2":official,
               "ratio_total_same_days":reconstructed/official if official else None,
               "review_internal_daily_bias_gt_0p10":
                   abs(bias)>.10 if bias is not None else None,
               "interpretation":"SAME_PROVIDER_DIFFERENT_RESOLUTIONS_NO_INDEPENDENT_CALIBRATION"})
    return annual

def aggregate_scores(hours,nasa,window):
    detailed=[];metrics=[];annual_qc=[]
    for y in YEARS:
        subset=[r for h,r in hours.items() if h.year==y]
        for name,tier_key in (("GHI","ghi_tier"),("DHI","dhi_tier")):
            statuses=Counter(r[tier_key] for r in subset)
            annual_qc.append({"year":y,"window":window,"channel":name,
                "original_hours":len(subset),
                **{k:statuses.get(k,0) for k in SCIENCE_TIERS},
                "complete_numeric_10min_hours":sum(r[
                  "ghi_kwh_m2" if name=="GHI" else "dhi_kwh_m2"] is not None
                  for r in subset),
                "provisional_physical_screen_pass_hours":sum(
                  r["provisional_dhi_usable_for_exploration"] for r in subset)
                  if name=="DHI" else None})
    for site in ("graz_station30","nasa_gcm_cell"):
        for hr,record in sorted(hours.items()):
            sim=nasa.get((site,hr))
            if sim is None:raise ValueError("Missing NASA POWER original 2005-14 hour")
            for name in ("GHI","DHI"):
                gh=record["ghi_kwh_m2" if name=="GHI" else "dhi_kwh_m2"]
                tier_name=record["ghi_tier" if name=="GHI" else "dhi_tier"]
                permitted=(
                  tier_name=="QC_CONFIRMED" and gh is not None
                  if name=="GHI" else
                  record["provisional_dhi_usable_for_exploration"])
                row={"site":site,"timestamp_utc_start":hr.isoformat(),
                    "year":hr.year,"month":hr.month,"window":window,
                    "channel":name,"original_qc_tier":tier_name,
                    "physical_review_flag":record["suspect"],
                    "independent_ground_qc_approved":tier_name=="QC_CONFIRMED",
                    "exploratory_source_usable":permitted,
                    "ground_original_kwh_m2_hour":gh,
                    "nasa_gridded_kwh_m2_hour":sim[name],
                    "power_minus_ground_kwh_m2_hour":
                       sim[name]-gh if permitted else None,
                    "nasa_is_ground_observation":False}
                detailed.append(row)
        for name in ("GHI","DHI"):
            subset=[r for r in detailed if r["site"]==site and
                    r["channel"]==name and r["window"]==window]
            for season,months in SEASONS.items():
                period=[r for r in subset if r["month"] in months]
                verified=[(r["ground_original_kwh_m2_hour"],
                           r["nasa_gridded_kwh_m2_hour"]) for r in period
                          if r["exploratory_source_usable"]]
                stat=metric(verified)
                metrics.append({"site":site,"window":window,
                    "channel":name,"season":season,"source_hours":len(period),
                    "usable_ground_hours":stat["n"],
                    "ground_source_status":("QC_CONFIRMED" if name=="GHI"
                      else "PROVISIONAL_UNCHECKED_OR_MIXED_PHYSICS_SCREENED"),
                    "mae_kwh_m2_hour":stat["mae"],
                    "bias_nasa_minus_ground_kwh_m2_hour":stat["bias"],
                    "rmse_kwh_m2_hour":stat["rmse"],
                    "pearson_r":stat["pearson_r"],
                    "ground_hourly_validation_science_status":
                         "EXPLORATORY_ONLY_SOURCE_QC_UNVERIFIED" if name=="DHI"
                         else "QC_CONFIRMED_SOURCE_BUT_TIME_SUPPORT_UNRESOLVED",
                    "production_epw_ready":False})
    return annual_qc,metrics,detailed

def run(open_original,p6e,p6d,out):
    out.mkdir(parents=True,exist_ok=True)
    by_year,source_index,prior=original_sources(open_original)
    nasa,nasa_sha=nasa_reference(p6e)
    observed_daily,daily_sha=original_daily_accepted(p6d)
    all_qc=[];all_scores=[];all_detail=[];all_daily=[]
    flags=Counter();summary={}
    for window in WINDOWS:
        hours=hourly_from_original(by_year,window)
        qc,scores,details=aggregate_scores(hours,nasa,window)
        days=daily_closure(hours,observed_daily)
        all_qc.extend(qc);all_scores.extend(scores)
        all_detail.extend(details);all_daily.extend(days)
        flags.update((window,key) for r in hours.values() for key in
                     ("diffuse_above_global","deep_night_diffuse_above_20W",
                      "negative_beyond_5W") if r[key] is True)
        summary[window]={
            "observed_grazer_total_hours":len(hours),
            "exploratory_dhi_hours":sum(
                r["provisional_dhi_usable_for_exploration"] for r in hours.values()),
            "source_qc_confirmed_dhi_hours":sum(
                r["source_qc_approved_dhi"] for r in hours.values()),
            "complete_dhi_hours_with_values":sum(
                r["dhi_kwh_m2"] is not None for r in hours.values()),
            "qc_confirmed_ghi_hours":sum(
                r["ghi_tier"]=="QC_CONFIRMED" for r in hours.values()),
            "daily_qc_confirmed_agreement_days":sum(
                r["tenminute_reconstructed_qc_confirmed_day"] for r in days),
            "daily_all_present_days":sum(
                r["tenminute_reconstructed_all_24_hours"] for r in days)}
        print("P6.3F-B",window,summary[window],flush=True)
    yearly_daily=annual_daily_closure_screen(all_daily)
    review_years=sorted({r["year"] for r in yearly_daily
                         if r["review_internal_daily_bias_gt_0p10"]})
    outputs={
        "p6_3f_b_official_daily_qc_disagreement_by_year.csv":yearly_daily,
        "p6_3f_b_ghidiffuse_hourly_quality_tiers.csv":all_qc,
        "p6_3f_b_provisional_diffuse_nasa_hourly_seasonal_metrics.csv":all_scores,
        "p6_3f_b_qc_vs_provisional_hourly_details.csv":all_detail,
        "p6_3f_b_official_23_23_utc_daily_source_closure.csv":all_daily,
        "p6_3f_b_immutable_geosphere_source_provenance.csv":source_index}
    digests={k:save_union(out/k,v) for k,v in outputs.items()}
    report={
      "stage":"IGE_P6_3F_B_UNCHECKED_VS_QC_SOLAR_EVIDENCE_AND_DAILY_CLOSURE",
      "technical_status":"RESEARCH_QC_TIER_SENSITIVITY_COMPLETED",
      "scientific_status":"GHI_QC_CONFIRMED_DHI_PROVISIONAL_UNCHECKED_ONLY",
      "epw_production_ready":False,
      "original_10min_geo_source_report_sha256":checksum(
          open_original/"p6_3f_open_10min_scientific_audit.json"),
      "original_geosphere_station":30,
      "station_16412_already_identified_as_30_child_alias":True,
      "original_solar_daily_sha256":daily_sha,
      "original_nasa_p6_3e_hourly_sha256":nasa_sha,
      "original_q21_code0_interpretation":"UNGEPRUEFTE_DATEN - unchecked, not erroneous",
      "strict_qc_codes":sorted(QC_ACCEPTED),
      "analysis_uses_original_q0_measurements_without_edits":True,
      "provisional_diffuse_scope":"2006–2009 only if available and physically screened; never independently QC-approved",
      "daily_consistency_not_independent_observational_validation":True,
      "source_time_label":"UNRESOLVED; both record_start and record_end retained",
      "unresolved_geosphere_10min_vs_1d_qc_annual_disagreement_years":review_years,
      "unresolved_daily_consistency_bias_screen_kwh_m2_day":.10,
      "source_internal_quality_note":"QC approved ten-minute GHI can differ materially from official daily GHI even when q21 confirms provider QC; compare 2010–2011 without declaring either source erroneous.",
      "physics_review_screen_counts":{f"{w}:{flag}":v
                      for (w,flag),v in sorted(flags.items())},
      "hourly_source_summary_by_time_hypothesis":summary,
      "methodology_notes":[
         "QC q21=0 is a provenance/quality-assurance uncertainty, not grounds to declare measurements incorrect.",
         "Research may use physically plausible original unverified samples with explicit classification and sensitivity, not as certified ground truth.",
         "GHI record q21-approved and DHI record q21=0 may legitimately be paired at the same hour; each channel maintains its own source quality tier.",
         "Daily cglo_j GHI comes from the same original station/provider; closure verifies consistency, not independent external accuracy.",
         "2010–2011 source-resolution energy discrepancies were detected; provider QA flags on one product do not guarantee equality with independently processed daily products.",
         "DHI observations only available 2006–2009 in original archived historical source; 2005 and 2010–14 cannot be extrapolated.",
         "Solar screens check diffuse<=global with transparent allowance and deep-night flux; their absence does not prove a sensor is calibrated.",
         "DNI derived from GHI minus DHI is not an independently measured DNI source and is not presented as such.",
         "Timestamp hypotheses are not selected post-hoc to maximize correlation.",
         "No future observational validation and no production EPW on P6.3F-B."],
      "output_file_sha256":digests}
    (out/"p6_3f_b_unverified_solar_research_science_report.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    print("P6.3F-B",report["scientific_status"],"EPW ready",False,flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--open-original",required=True,type=Path)
    p.add_argument("--p6e-frozen",required=True,type=Path)
    p.add_argument("--p6d-frozen",required=True,type=Path)
    p.add_argument("--out",required=True,type=Path)
    a=p.parse_args()
    run(a.open_original,a.p6e_frozen,a.p6d_frozen,a.out)
