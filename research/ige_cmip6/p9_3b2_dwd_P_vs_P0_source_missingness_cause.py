#!/usr/bin/env python3
"""P9.3B2 causal source-only DWD original 2024 station P missingness audit.

Do NOT substitute sea-level P0/QFF for true station P, do not expand frozen
station cohort or tune model to measured pressure.
"""
from __future__ import annotations
import argparse,io,zipfile,re,json,csv,collections,hashlib
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request,urlopen
DWD_PRESS_ROOT="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"
def _download_DWD_pressure(url,max_bytes=9_000_000):
 u=urlsplit(url)
 if u.hostname!="opendata.dwd.de" or not u.path.startswith(
     "/climate_environment/CDC/observations_germany/climate/hourly/pressure/historical/"):
  raise ValueError("P93B2_DWD_SOURCE_HOST_INVALID")
 with urlopen(Request(url,headers={"User-Agent":"IGE-P93B2-DWD-Pressure-Source-Causal/1.0"}),timeout=90) as response:
  b=response.read(max_bytes+1)
 if len(b)>max_bytes:raise ValueError("P93B2_DWD_SOURCE_OVERSIZED")
 return b,hashlib.sha256(b).hexdigest()
def run(out):
 out=Path(out);out.mkdir(parents=True,exist_ok=True)
 ls,source_sha=_download_DWD_pressure(DWD_PRESS_ROOT,2_000_000)
 archives=set(re.findall(r"stundenwerte_P0_03730_(\d{8})_(\d{8})_hist\.zip",ls.decode("utf8",errors="replace"),re.I))
 valid=[(s,e) for s,e in archives if s<="20240110" and e>="20240716"]
 if len(valid)!=1:raise ValueError("P93B2_DWD_SOURCE_ARCHIVE_AMBIGUOUS")
 s,e=valid[0];asset=f"stundenwerte_P0_03730_{s}_{e}_hist.zip"
 raw,sha=_download_DWD_pressure(DWD_PRESS_ROOT+asset,8_000_000)
 outp={"phase":"P93B2_DWD_ORIGINAL_STATION_PRESSURE_SOURCE_MISSINGNESS_CAUSAL",
   "source_archive":asset,"source_zip_SHA256":sha,
   "station_id":"03730","original_field_P_is_station_pressure":True,
   "original_field_P0_is_SEALEVEL_NOT_INTERCHANGEABLE":True,
   "original_2024_fixed_pressure_cohort_not_changed":True,
   "source_ERA5_grid_model_not_modified":True,
   "registered_windows":{"January":("2024011000","2024011623"),
                         "July":("2024071000","2024071623")}}
 stats={n:{"n_rows":0,"QN8_counts":collections.Counter(),
     "P_native_counts":collections.Counter(),"P0_native_counts":collections.Counter(),
     "P_numeric_min_max":None,"P0_numeric_min_max":None} for n in outp["registered_windows"]}
 vals={n:{"P":[],"P0":[]} for n in stats}
 with zipfile.ZipFile(io.BytesIO(raw)) as z:
  if z.testzip() is not None:raise ValueError("P93B2_DE_SOURCE_ZIP_CRC")
  member=[p for p in z.namelist() if Path(p).name.startswith("produkt_p0_stunde_") and p.endswith(".txt")]
  if len(member)!=1:raise ValueError("P93B2_DE_ORIGINAL_PRODUCT_MISSING")
  reader=csv.DictReader(io.TextIOWrapper(z.open(member[0]),encoding="latin1"),delimiter=";")
  outp["native_P0_csv_columns"]=reader.fieldnames
  for r in reader:
   ts=(r.get("MESS_DATUM") or "").strip()
   n=next((n for n,(a,b) in outp["registered_windows"].items() if a<=ts<=b),None)
   if n is None:continue
   stats[n]["n_rows"]+=1
   stats[n]["QN8_counts"][(r.get("QN_8") or "").strip()]+=1
   for field in ("P","P0"):
    v=(r.get(field) or "").strip()
    k=("EMPTY" if not v else "MISSING_SENTINEL" if v in ("-999","-999.0","-9999","-999.00") else
        "NUMERIC_FINITE_RANGE" if re.fullmatch(r"-?\d+(?:\.\d+)?",v) and 450<float(v)<1080 else
        "NONSTATION_RANGE_OR_OTHER")
    stats[n][field+"_native_counts"][k]+=1
    if k=="NUMERIC_FINITE_RANGE":vals[n][field].append(float(v))
 for n in stats:
  for field in ("P","P0"):
   v=vals[n][field]
   stats[n][field+"_numeric_min_max"]=[min(v),max(v)] if v else None
   stats[n][field+"_native_counts"]=dict(stats[n][field+"_native_counts"])
  stats[n]["QN8_counts"]=dict(stats[n]["QN8_counts"])
  print("P93B2_DWD_ORIGINAL_P_VS_P0_MISSINGNESS",n,json.dumps(stats[n]),flush=True)
 outp["diagnostics"]=stats
 outp["station_QFE_original_2024_hPa_source_qualifies"]=all(
    stats[n]["P_native_counts"].get("NUMERIC_FINITE_RANGE",0)>=96 for n in stats)
 outp["do_not_use_P0_as_P"]=True
 (out/"p9_3b2_original_DWD_03730_2024_P_vs_P0_source_missingness.json").write_text(
    json.dumps(outp,ensure_ascii=False,indent=2)+"\n")
 return outp
if __name__=="__main__":
 p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p93b2-de-causal")
 run(Path(p.parse_args().out))
