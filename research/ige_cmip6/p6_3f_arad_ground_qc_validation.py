#!/usr/bin/env python3
"""P6.3F: fail-closed ARAD Graz minute-to-hour ground validation against NASA POWER.

No ARAD source has been acquired. Without a custodian-authenticated original
minute CSV *and* explicit source contract JSON, generate acquisition-gate
evidence only; DO NOT manufacture or infer ground validation statistics.

If authentic QC data are supplied: require 60/60 q=1 minutes per component
for primary hourly comparisons; do not impute, clip, replace, time-shift, or
use NASA values as observed ground. Primary years 2012–2014 only.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
from pathlib import Path
from statistics import fmean
from p6_2d_solar_methods_benchmark import checksum
from p6_3c_precip_semantics_daily_alignment import save_union

ARAD_COLS={"GHI":"ghi_w_m2","DNI":"dni_w_m2","DHI":"dhi_w_m2",
           "LW":"lw_down_w_m2"}
QC={1:"good",2:"wrong",3:"dubious",255:"missing"}
PROVENANCE_STATES=("RESTRICTED_CUSTODIAN_REQUEST_REQUIRED",
                   "AUTHENTIC_ORIGINAL_RESEARCH_ACCESS_APPROVED")
STATION_ID="ARAD_GRAZ"
SLOTS=60
START=datetime(2012,1,1,tzinfo=timezone.utc)
END=datetime(2015,1,1,tzinfo=timezone.utc)
PERIOD_HOURS=26304
PERIOD_MINS=PERIOD_HOURS*60
SEASONS={"ANNUAL":set(range(1,13)),"DJF":{12,1,2},"MAM":{3,4,5},
         "JJA":{6,7,8},"SON":{9,10,11}}
SITES=("graz_station30","nasa_gcm_cell")
NASA_COLUMNS={"GHI":"GHI_kwh_m2_hour","DNI":"DNI_kwh_m2_hour",
              "DHI":"DHI_kwh_m2_hour"}
DATA_CONTACTS={
 "dataset":"ARAD Graz original one-minute solar radiation, 2012–2014",
 "public_open_csv_confirmed":False,
 "access":"RESTRICTED; formal approval and source-specific partner conditions",
 "custodian":"GeoSphere Austria (with University of Graz station partners)",
 "scientific_contacts":["marc.olefs@geosphere.at",
                        "florian.geyer@geosphere.at"],
 "official_data_access":"klima@geosphere.at",
 "local_instrument_contact":"messung.physik@uni-graz.at",
 "source_reference_urls":[
   "https://www.gcos.at/reports/Austrian_GCOS_Report_2025.pdf",
   "https://amt.copernicus.org/articles/9/1513/2016/",
   "https://climatephysics.uni-graz.at/en/meteorological-station/"],
 "qc_codes":{"1":"good","2":"wrong","3":"dubious","255":"missing"},
 "qc_disclaimer":"Published 2012–14 percentage statistics are not minute-level records",
 "source_files_present":False,
 "permission_to_redistribute":False,
}
def iso_utc(value):
    if not value.endswith(("+00:00","Z")):
        raise ValueError("Original ARAD requires explicit UTC offset, not local time")
    stamp=datetime.fromisoformat(value.replace("Z","+00:00"))
    if stamp.utcoffset()!=timedelta(0):
        raise ValueError("Original ARAD timestamp must be UTC")
    if stamp.second or stamp.microsecond:
        raise ValueError("Original ARAD sampling must align to whole UTC minutes")
    return stamp

def validate_manifest(manifest,original_sha):
    required={"station_id","custodian","original_source_sha256",
      "source_approval","quality_flag_mapping","time_standard",
      "timestamp_represents","sampling_seconds","variables",
      "archived_raw_unmodified","permission_to_analyse","station_latitude",
      "station_longitude","source_data_version"}
    if not required<=set(manifest):
        raise ValueError("ARAD custodian manifest missing required scientific provenance")
    if manifest["station_id"]!=STATION_ID or \
       manifest["source_approval"]!="AUTHENTIC_ORIGINAL_RESEARCH_ACCESS_APPROVED":
        raise ValueError("ARAD archive has no confirmed original custodial approval")
    if manifest["original_source_sha256"]!=original_sha or \
       not manifest["archived_raw_unmodified"]:
        raise ValueError("ARAD source bytes not traceable to immutable original archive")
    if manifest["time_standard"]!="UTC" or \
       manifest["timestamp_represents"]!="start_of_1_minute_average" or \
       manifest["sampling_seconds"]!=60:
        raise ValueError("ARAD original measurement UTC timestamp semantics unconfirmed")
    if not manifest["permission_to_analyse"]:
        raise ValueError("ARAD science data-use permission not documented")
    if manifest["quality_flag_mapping"]!={str(k):v for k,v in QC.items()}:
        raise ValueError("Original ARAD quality flag code legend must be explicit")
    if manifest["variables"]!={k:{"column":v,"unit":"W/m2","quality_flag_column":v+"_qc"}
                                 for k,v in ARAD_COLS.items()}:
        raise ValueError("ARAD physical units/column schema not original-source verified")
    lat=float(manifest["station_latitude"])
    lon=float(manifest["station_longitude"])
    if not (46.7<lat<47.4 and 14.9<lon<16.0):
        raise ValueError("ARAD Graz actual instrument location unconfirmed")
    if not str(manifest["custodian"]).strip() or \
       not str(manifest["source_data_version"]).strip():
        raise ValueError("Missing original custodian/source data version")
    return {"latitude":lat,"longitude":lon,
            "redistribution_permitted":bool(manifest.get("redistribution_permitted",False))}

def load_original_arad(csv_path,manifest_path):
    origin_sha=checksum(csv_path)
    manifest=json.loads(manifest_path.read_text(encoding="utf8"))
    approved=validate_manifest(manifest,origin_sha)
    by_hour=defaultdict(dict)
    records=0;quality=Counter();prev=None
    with csv_path.open("r",encoding="utf8",newline="") as inp:
        reader=csv.DictReader(inp)
        mandatory={"timestamp_utc"}
        for field in ARAD_COLS.values():mandatory.update([field,field+"_qc"])
        if not mandatory<=set(reader.fieldnames or []):
            raise ValueError("Original ARAD provider CSV expected columns absent")
        for row in reader:
            stamp=iso_utc(row["timestamp_utc"])
            if not START<=stamp<END:
                raise ValueError("ARAD pilot source contains date outside approved 2012–2014 window")
            if prev is not None and stamp<=prev:
                raise ValueError("ARAD original timestamps duplicate or not chronological")
            prev=stamp
            hr=stamp.replace(minute=0)
            minute=stamp.minute
            readings={}
            for name,col in ARAD_COLS.items():
                q=int(row[col+"_qc"])
                if q not in QC:raise ValueError("Unknown original ARAD source QC flag")
                quality[f"{name}_q{q}"]+=1
                val=row[col].strip()
                if q==1:
                    if not val:raise ValueError("ARAD q1 good record has no measurement")
                    physical=float(val)
                    if not math.isfinite(physical) or \
                       not (-50<=physical<=2000 if name!="LW"
                            else 0<=physical<=1000):
                        raise ValueError("Non-finite or extreme ARAD q1 irradiance; retain for provider investigation")
                    readings[name]=physical
                else:
                    readings[name]=None
            if minute in by_hour[hr]:
                raise ValueError("Duplicate original minute")
            by_hour[hr][minute]=readings
            records+=1
    if records==0:raise ValueError("No original ARAD records supplied")
    # Individual solar channel hourly energy is accepted ONLY with
    # 60 actual original minutes, all 60 with documented q=1.
    hourly={}
    for hr,minute_data in sorted(by_hour.items()):
        all_minutes=len(minute_data)==SLOTS and set(minute_data)==set(range(SLOTS))
        values={}
        for name in ARAD_COLS:
            samples=[x[name] for x in minute_data.values() if x[name] is not None]
            n=len(samples)
            values[f"{name}_good_minutes"]=n
            values[f"{name}_kwh_m2_hour"]=(sum(samples)/SLOTS/1000.0
                      if all_minutes and n==SLOTS else None)
            values[f"{name}_all_minutes_q1"]=bool(all_minutes and n==SLOTS)
        values["source_minute_count"]=len(minute_data)
        values["joint_good_minutes"]=sum(all(x.get(c) is not None
                 for c in ARAD_COLS) for x in minute_data.values())
        values["all_four_complete_q1"]=bool(all_minutes and
                                             values["joint_good_minutes"]==SLOTS)
        values["timestamp_utc_start"]=hr.isoformat()
        hourly[hr]=values
    return hourly,{"original_source_sha256":origin_sha,"records":records,
         "hours_with_any_minute":len(hourly),"complete_all_four_hours":
             sum(r["all_four_complete_q1"] for r in hourly.values()),
         "quality_counts":dict(sorted(quality.items())),
         "time_standard":"UTC; original start-of-minute average",
         "source_status":"AUTHENTIC_ORIGINAL_RESEARCH_ACCESS_APPROVED",
         "ground_archive_redistribution_permitted":approved["redistribution_permitted"],
         "site_latitude":approved["latitude"],"site_longitude":approved["longitude"]}

def load_nasa_reference(e_artifact):
    source=e_artifact/"p6_3e_native_hourly_ghi_dni_dhi_toa_physical_diagnostics.csv"
    report=e_artifact/"p6_3e_hourly_solar_components_arad_science_audit.json"
    if not source.is_file() or not report.is_file():
        raise FileNotFoundError("P6.3E immutable hourly provenance artifacts unavailable")
    science=json.loads(report.read_text(encoding="utf8"))
    expected=science["output_file_sha256"][source.name]
    actual=checksum(source)
    if expected!=actual or science.get("production_epw_ready") is not False:
        raise ValueError("Original frozen P6.3E CSV checksum/scientific gate changed")
    index={};seen=Counter()
    with source.open("r",encoding="utf8",newline="") as inp:
        for r in csv.DictReader(inp):
            site=r["site"]
            if site not in SITES:raise ValueError("Unknown NASA POWER reference site")
            stamp=iso_utc(r["timestamp_utc_start"])
            if stamp.second!=0 or stamp.minute!=0:raise ValueError("NASA hourly start not whole UTC hour")
            seen[site]+=1
            if not START<=stamp<END:continue
            if r["valid"]!="True" or r["is_satellite_not_observed_ground"]!="True":
                raise ValueError("Unverified NASA POWER source row treated as valid ground data")
            key=(site,stamp)
            if key in index:raise ValueError("NASA POWER duplicated hourly reference")
            index[key]={name:float(r[col]) for name,col in NASA_COLUMNS.items()}
            index[key]["solar_coszen_noaa_midpoint"]=float(r["solar_coszen_noaa_midpoint"])
    if set(seen)!=set(SITES) or any(seen[x]!=87648 for x in SITES):
        raise ValueError("Expected frozen original 2005–2014 NASA hourly source absent")
    if len(index)!=len(SITES)*PERIOD_HOURS:
        raise ValueError("Expected original NASA 2012–2014 reference coverage missing")
    return index,{"p6_3e_native_csv_sha256":actual,
         "source":"NASA POWER satellite/reanalysis, not ground observed",
         "utc_hours_per_site":PERIOD_HOURS,
         "geographic_points":list(SITES)}

def pearson(pairs):
    if len(pairs)<30:return None
    x,y=zip(*pairs);u=fmean(x);v=fmean(y)
    cov=sum((a-u)*(b-v) for a,b in pairs)
    ssx=sum((a-u)**2 for a in x);ssy=sum((b-v)**2 for b in y)
    return cov/math.sqrt(ssx*ssy) if ssx>0 and ssy>0 else None

def metrics(rows,site,channel,season):
    selected=[r for r in rows if r["site"]==site and r["channel"]==channel
        and r["month"] in SEASONS[season]]
    observed=[(r["arad_kwh_m2_hour"],r["power_kwh_m2_hour"])
            for r in selected if r["paired_valid"]]
    if not selected:raise ValueError("No NASA POWER evaluation hours")
    n=len(observed); diffs=[m-o for o,m in observed]
    return {"site":site,"channel":channel,"season":season,
      "available_reference_hours":len(selected),
      "independent_ground_q1_paired_hours":n,
      "paired_coverage":n/len(selected),
      "mean_bias_nasa_minus_ground_kwh_m2_hour":fmean(diffs) if diffs else None,
      "mae_kwh_m2_hour":fmean(abs(d) for d in diffs) if diffs else None,
      "rmse_kwh_m2_hour":math.sqrt(fmean(d*d for d in diffs)) if diffs else None,
      "pearson_r":pearson(observed),
      "ground_hourly_research_approved":n>0,
      "satellite_is_independent_ground_observation":False}

def compare(ground,nasa):
    # Each NASA hour is present as a row. Ground values are accepted ONLY
    # for complete 60-minute hourly cells for that channel.
    rows=[]
    for (site,stamp),power in sorted(nasa.items()):
        original=ground.get(stamp)
        for name in NASA_COLUMNS:
            measure=original.get(f"{name}_kwh_m2_hour") if original else None
            rows.append({"site":site,"timestamp_utc_start":stamp.isoformat(),
                "month":stamp.month,"year":stamp.year,"channel":name,
                "ground_source":"ARAD_GRAZ_ORIGINAL_MINUTE_QC1_60_OF_60",
                "power_source":"NASA_POWER_GRID_NOT_STATION",
                "paired_valid":measure is not None,
                "arad_kwh_m2_hour":measure,
                "power_kwh_m2_hour":power[name],
                "power_minus_arad_kwh_m2_hour":(
                      power[name]-measure if measure is not None else None)})
    total=[metrics(rows,site,name,season) for site in SITES
                for name in NASA_COLUMNS for season in SEASONS]
    return rows,total

def run(p6e,out,arad=None,manifest=None):
    out.mkdir(parents=True,exist_ok=True)
    if bool(arad)!=bool(manifest):
        raise ValueError("ARAD ORIGINAL CSV and original custodian provenance JSON must be supplied together")
    nasa,original_reference=load_nasa_reference(p6e)
    ground_exists=arad is not None
    evidence={"stage":"IGE_P6_3F_ARAD_GRAZ_INDEPENDENT_GROUND_VALIDATION",
      "research_branch_type":"RESTRICTED_ORIGINAL_GROUND_SOURCE_GATED",
      "freeze_upstream":"IGE P1–P6.3E integrated scientific preservation freeze",
      "source_acquisition":DATA_CONTACTS,
      "historical_assessment_years":[2012,2013,2014],
      "source":original_reference,
      "approved_ground_original_provided":ground_exists,
      "production_epw_ready":False,
      "scientific_limitations":[
         "NASA POWER grid is NOT independently measured hourly ground radiation.",
         "Published ARAD QC percentages are NOT original minute records.",
         "Require explicit custodian UTC start-of-minute semantics; DST/local timestamps forbidden.",
         "Only exact original 60/60 minutes per channel with ARAD q=1 become primary accepted 1h observations; no imputation.",
         "Do not shift timestamps to increase correlations, reprocess original archived data, or copy private ARAD measurements into public GitHub.",
         "P6.3E satellite source-internal GHI/DNI/DHI consistency is distinct from P6.3F independent ground validation.",
         "Ground reference alone would not prove future EPW physical coherence or future predictive validity."],
      "scientific_status":"BLOCKED_ARAD_SOURCE_ACCESS_NOT_YET_ACQUIRED",
      "comparison_statistics":None,
      "raw_ground_redistribution":False}
    if ground_exists:
        ground,ground_source=load_original_arad(arad,manifest)
        rows,summary=compare(ground,nasa)
        evidence["ground_provenance"]=ground_source
        evidence["scientific_status"]=("ORIGINAL_GROUND_COMPARISON_COMPLETED_REVIEW_REQUIRED"
              if ground_source["complete_all_four_hours"]>=30 else
              "INSUFFICIENT_JOINT_HOURLY_ARAD_QC_COVERAGE")
        evidence["comparison_statistics"]=summary
        evidence["raw_ground_redistribution"]=ground_source[
              "ground_archive_redistribution_permitted"]
        # Important: only the matched SCIENTIFIC SUMMARY is emitted; do not
        # upload any private raw ground or timestamp-level joined values.
        # The private per-hour diagnostic may be written only to a manually
        # approved restricted repository, not this CI artifact.
        save_union(out/"p6_3f_arad_ghidnidhi_summary.csv",summary)
    else:
        by_site=[{"site":site,"period":"2012–2014",
              "power_utc_hourly_records":sum(k[0]==site for k in nasa),
              "ground_original_minute_records":None,
              "independent_ground_pairs":None,
              "source_access":"RESTRICTED_SOURCE_NOT_ACQUIRED",
              "status":"GROUND_VALIDATION_BLOCKED"} for site in SITES]
        save_union(out/"p6_3f_nasa_source_preservation_preflight.csv",by_site)
    (out/"p6_3f_ground_access_science_report.json").write_text(
         json.dumps(evidence,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print("P6.3F",evidence["scientific_status"],
          "original_2012_2014_nasa_hours",len(nasa),
          "ground_present",ground_exists,
          "epw_ready",evidence["production_epw_ready"],flush=True)
    return evidence

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--p6e-frozen",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--arad-original-minute-csv",type=Path)
    p.add_argument("--arad-source-manifest-json",type=Path)
    a=p.parse_args()
    run(a.p6e_frozen,a.out,a.arad_original_minute_csv,a.arad_source_manifest_json)
