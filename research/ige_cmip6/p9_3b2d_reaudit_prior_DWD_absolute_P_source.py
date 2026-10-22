#!/usr/bin/env python3
"""IGE P9.3B2D RETROSPECTIVE error-correction audit: original DWD P is not empty.

Earlier P9.3B2/C CSV readers compared stripped header names but accessed
DictReader fields without stripping: original '  P'/' P0' became missing.
This correction is SOURCE-ONLY and original existing-year test, not a new
independent holdout or an update to source pressure method.
"""
from __future__ import annotations
import argparse,csv,io,zipfile,re,json,math,collections
from pathlib import Path
from p9_3b2d_dwd_2020_source_pressure_census import fetch,ROOT
STATIONS=(
 ("Oberstdorf","03730",2024,(("January","2024011000","2024011623"),
                         ("July","2024071000","2024071623"))),
 ("Potsdam","03987",2023,(("January","2023011000","2023011623"),
                       ("July","2023071000","2023071623")))
)
def source(station,id,year,periods,files):
 matches=sorted(set(re.findall(r"stundenwerte_P0_"+id+r"_(\d{8})_(\d{8})_hist\.zip",
                                  files,flags=re.I)))
 usable=[(start,end) for start,end in matches if start<=periods[0][1][:8] and end>=periods[-1][2][:8]]
 if len(usable)!=1:raise ValueError("P93B2D_PREVIOUS_SOURCE_ARCHIVE_IDENTITY_UNRESOLVED")
 start,end=usable[0]
 fname=f"stundenwerte_P0_{id}_{start}_{end}_hist.zip"
 blob,sha=fetch(ROOT+fname,12_000_000)
 summary={"station":station,"id":id,"year":year,"source_archive_name":fname,
          "source_archive_SHA256":sha,"retrospective_not_new_holdout":True,
          "failed_old_reader_looked_up_unstripped_P_and_P0":True,
          "no_ERA5_skill_calculated_in_source_audit":True,
          "windows":{s:{"n_original_hours":0,"n_real_P_valid":0,"n_real_P0_valid":0,
                         "n_true_P_QN8_3":0,"n_true_P_QN8_10":0,
                         "original_QN_8_histogram":collections.Counter()}
                     for s,lo,hi in periods}}
 with zipfile.ZipFile(io.BytesIO(blob)) as arc:
  if arc.testzip():raise ValueError("P93B2D_OLD_REPAIR_ZIP_CRC")
  members=[m for m in arc.namelist() if Path(m).name.startswith("produkt_p0_stunde_")
              and m.endswith(".txt")]
  if len(members)!=1:raise ValueError("P93B2D_REPAIR_OLD_ARCHIVE_MEMBER_NOT_FOUND")
  with io.TextIOWrapper(arc.open(members[0]),encoding="latin1") as fp:
   rd=csv.DictReader(fp,delimiter=";")
   original_header=list(rd.fieldnames or [])
   rd.fieldnames=[k.lstrip("\ufeff").strip() for k in original_header]
   if not {"STATIONS_ID","MESS_DATUM","QN_8","P","P0"}.issubset(rd.fieldnames):
    raise ValueError("P93B2D_DWD_FIELD_NORMALIZATION_NOT_VERIFIED")
   summary["original_csv_fields_before_normalization"]=original_header
   summary["normalized_csv_fields"]=rd.fieldnames
   for r in rd:
    dt=(r.get("MESS_DATUM") or "").strip()
    target=next((s for s,start,end in periods if start<=dt<=end),None)
    if target is None:continue
    if int(r["STATIONS_ID"])!=int(id):raise ValueError("P93B2D_DWD_SOURCE_STATION_MISMATCH")
    d=summary["windows"][target];d["n_original_hours"]+=1
    qc=(r.get("QN_8") or "").strip()
    d["original_QN_8_histogram"][qc]+=1
    try:p=float(r["P"])
    except (ValueError,TypeError):p=float("nan")
    try:p0=float(r["P0"])
    except (ValueError,TypeError):p0=float("nan")
    if 450<p<1080:
     d["n_real_P_valid"]+=1
     if qc=="3":d["n_true_P_QN8_3"]+=1
     if qc=="10":d["n_true_P_QN8_10"]+=1
    if 450<p0<1100:d["n_real_P0_valid"]+=1
 for d in summary["windows"].values():
  d["original_QN_8_histogram"]=dict(d["original_QN_8_histogram"])
  if d["n_original_hours"]!=168:
   raise ValueError("P93B2D_ORIGINAL_PRIOR_WINDOW_INCOMPLETE")
 return summary
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 listing,listing_sha=fetch(ROOT,5_000_000)
 text=listing.decode("utf8",errors="replace")
 results=[source(*item,text) for item in STATIONS]
 report={"phase":"IGE_P9_3B2D_CORRECTION_OF_OLD_P93B2_P93B2C_DWD_MISSING_P_RESULTS",
         "source_directory_SHA256":listing_sha,
         "supersedes_priors_source_absent_claims_if_fields_now_valid":True,
         "does_not_change_frozen_prior_model_code_or_original_years":True,
         "no_new_weather_model_holdout":True,
         "station_sources":results,
         "all_old_source_absent_claims_invalid_if_any":all(
             s["windows"][w]["n_real_P_valid"]>0
             for s in results for w in ("January","July"))}
 for r in results:
  print("P93B2D_REPAIR_OLD_DWD_ABSOLUTE_P",json.dumps({
    "station":r["station"],"csv_headers":r["original_csv_fields_before_normalization"],
    "January":r["windows"]["January"],"July":r["windows"]["July"]}),flush=True)
 (out/"p9_3b2d_reaudit_original_DWD_Potsdam_2023_Oberstdorf_2024_corrected_P_sources.json").write_text(
    json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
 return report
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2d-prior-source-correction")
 run(Path(p.parse_args().out))
