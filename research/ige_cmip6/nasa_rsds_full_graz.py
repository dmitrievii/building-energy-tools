#!/usr/bin/env python3
"""Open NASA NEX-GDDP-CMIP6 v2.0 rsds daily-to-monthly point extraction.

Research benchmark for Graz. Same model/member in historical/future runs.
No CCKP ensemble is confused with a single-GCM NASA scenario.
Calendar-aware solar daily energy integration: W/m² daily mean ×24h /1000.
"""
from __future__ import annotations
import calendar
import csv
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import netCDF4
import numpy as np

SITE = {"lat":46.983, "lon":15.450, "name":"Graz EPW reference coordinate"}
MODEL="ACCESS-CM2"
MEMBER="r1i1p1f1"
VARIABLE="rsds"
VERSION="v2.0"
BASE="https://ds.nccs.nasa.gov"
PERIODS={"historical":(1995,2014),"ssp245-2040-2059":(2040,2059),
         "ssp245-2080-2099":(2080,2099),"ssp585-2040-2059":(2040,2059),
         "ssp585-2080-2099":(2080,2099)}
OUT=Path("outputs/nasa_rsds")
OUT.mkdir(parents=True,exist_ok=True)
SOURCES=[]
YEARROWS=[]
ERR=[]
UA={"User-Agent":"IGE-open-Climate-Engine-NASA-rsds-v0.3.0/2026"}

def download(url, cap=7_000_000):
    attempts=[]
    for k in range(4):
        try:
            req=urllib.request.Request(url,headers=UA)
            with urllib.request.urlopen(req,timeout=105) as f:
                status=f.status
                body=f.read(cap+1)
                mime=f.headers.get("Content-Type","")
            if status!=200 or len(body)>cap:
                raise ValueError(f"HTTP {status}, bytes {len(body)}, cap {cap}, mime={mime}")
            return body,mime
        except Exception as e:
            attempts.append(f"{type(e).__name__}: {e}")
            if k < 3:
                time.sleep(2*(k+1))
    raise RuntimeError(f"Unable to fetch {url}: {attempts}")

def catalog(scenario):
    url=f"{BASE}/thredds/catalog/AMES/NEX/GDDP-CMIP6/{MODEL}/{scenario}/{MEMBER}/rsds/catalog.xml"
    data,mime=download(url)
    root=ET.fromstring(data)
    mapping={}
    for el in root.iter():
        if not el.tag.endswith("dataset"):continue
        key=el.attrib.get("name","")
        path=el.attrib.get("urlPath","")
        if path and key.endswith(f"_{VERSION}.nc"):
            yrpart=key.removesuffix(f"_{VERSION}.nc").split("_")[-1]
            if yrpart.isdigit() and len(yrpart)==4:
                mapping[int(yrpart)]=path
    print("CATALOG",scenario,"years",len(mapping),"range",min(mapping),max(mapping),flush=True)
    if len(mapping)<85 and scenario!="historical":
        raise RuntimeError("Catalog unexpectedly short")
    if len(mapping)<60 and scenario=="historical":
        raise RuntimeError("Historical catalog unexpectedly short")
    return mapping

def year_data(scenario, year, key):
    url=f"{BASE}/thredds/ncss/grid/{key}?"+urllib.parse.urlencode({
        "var":"rsds","north":"47.11","south":"46.88",
        "west":"15.33","east":"15.59","time_start":f"{year}-01-01T12:00:00Z",
        "time_end":f"{year}-12-31T12:00:00Z",
        "accept":"netcdf3","addLatLon":"true"})
    raw,mime=download(url)
    if not raw.startswith(b"CDF"):
        raise ValueError(f"NCSS returned non-NetCDF bytes: {mime!r} {raw[:120]!r}")
    sha=hashlib.sha256(raw).hexdigest()
    with tempfile.NamedTemporaryFile(suffix=".nc",delete=False) as f:
        file=f.name
        f.write(raw)
    try:
        with netCDF4.Dataset(file) as ds:
            if "rsds" not in ds.variables:raise RuntimeError("NCSS has no rsds")
            v=ds.variables["rsds"]
            unit=str(getattr(v,"units","")).replace(" ","").lower()
            if unit not in ("wm-2","w/m2","wm**-2","wm^-2","wm−2","wm-²"):
                raise RuntimeError(f"Unexpected solar units: {getattr(v,'units',None)!r}")
            if "time" not in ds.variables:raise RuntimeError("No time coordinate")
            t=ds.variables["time"]
            dates=netCDF4.num2date(t[:],t.units,getattr(t,"calendar","standard"),
                    only_use_cftime_datetimes=True)
            if len(dates)<360:raise RuntimeError(f"Only {len(dates)} days returned")
            if any(int(d.year)!=year for d in dates):
                raise RuntimeError("Data time grid mismatches requested calendar year")
            lat=ds.variables["lat"];lon=ds.variables["lon"]
            lats=np.asarray(lat[:],dtype=float).reshape(-1)
            lons=np.asarray(lon[:],dtype=float).reshape(-1)
            expected_lon=SITE["lon"]%360 if np.nanmax(lons)>180 else SITE["lon"]
            ilat=int(np.nanargmin(np.abs(lats-SITE["lat"])))
            ilon=int(np.nanargmin(np.abs(lons-expected_lon)))
            slat=float(lats[ilat]);slon=float(lons[ilon])
            if abs(slat-SITE["lat"])>0.30 or abs(slon-expected_lon)>0.30:
                raise RuntimeError(f"Solar grid too far from site: {slat},{slon}")
            # Explicit dimensions to prevent accidental spatial/time broadcasting.
            axes=v.dimensions
            index=tuple(slice(None) if dim=="time" else
                        ilat if dim==lat.dimensions[0] else
                        ilon if dim==lon.dimensions[0] else
                        0 if len(ds.dimensions[dim])==1 else
                        (_ for _ in ()).throw(RuntimeError(f"Unexpected axis {dim}")) for dim in axes)
            vals=np.asarray(np.ma.filled(v[index],np.nan),dtype=float).reshape(-1)
            if len(vals)!=len(dates):raise RuntimeError("Time/radiation mismatch")
            if not np.all(np.isfinite(vals)):raise RuntimeError("Solar data missing/nonfinite")
            if np.nanmin(vals)<-0.01 or np.nanmax(vals)>750:
                raise RuntimeError(f"Implausible daily rsds range {np.min(vals):.2f} to {np.max(vals):.2f}")
            counts={}
            rows={}
            for m in range(1,13):
                mvals=[float(x) for x,d in zip(vals,dates) if int(d.month)==m]
                expected=calendar.monthrange(year,m)[1]
                # Accept an explicit no-leap calendar in leap years.
                cal=str(getattr(t,"calendar","standard")).lower()
                if cal in ("365_day","noleap") and m==2:expected=28
                if cal=="360_day":expected=30
                if len(mvals)!=expected:
                    raise RuntimeError(f"Incomplete daily series {year}-{m:02d}: {len(mvals)} vs {expected} ({cal})")
                rows[m]={
                    "year":year,"month":m,"scenario":scenario,"model":MODEL,"member":MEMBER,
                    "days":len(mvals),
                    "monthly_mean_wm2":float(np.mean(mvals)),
                    "monthly_total_kwh_m2":sum(mvals)*0.024,
                    "grid_lat":slat,"grid_lon":slon,
                    "nc_sha256":sha,"nc_bytes":len(raw),"source_url":url,
                    "time_calendar":str(getattr(t,"calendar","standard")),
                }
            if sum(x["days"] for x in rows.values())!=len(dates):raise RuntimeError("Unexpected extraneous dates")
            return list(rows.values())
    finally:
        Path(file).unlink(missing_ok=True)

def summarize(records):
    grouped={}
    for r in records:
        key=(r["scenario"],r["month"])
        grouped.setdefault(key,[]).append(r)
    summary={}
    for name,(a,b) in PERIODS.items():
        if name=="historical":scenario="historical"
        else:scenario=name.split("-")[0]
        for m in range(1,13):
            sub=[r for r in grouped[(scenario,m)] if a<=r["year"]<=b]
            years={r["year"] for r in sub}
            if years!=set(range(a,b+1)):raise RuntimeError(f"Missing years {name}, month {m}")
            samplecoords={(r["grid_lat"],r["grid_lon"]) for r in sub}
            if len(samplecoords)!=1:raise RuntimeError("Solar coordinate changed across years")
            summary[(name,m)]={
                "window":name,"month":m,"model":MODEL,"member":MEMBER,
                "mean_wm2":sum(r["monthly_mean_wm2"] for r in sub)/len(sub),
                "monthly_energy_kwh_m2":sum(r["monthly_total_kwh_m2"] for r in sub)/len(sub),
                "years":len(sub),"grid_lat":sub[0]["grid_lat"],"grid_lon":sub[0]["grid_lon"]}
    result=[]
    for name in PERIODS:
        if name=="historical":continue
        for m in range(1,13):
            future=summary[(name,m)];historic=summary[("historical",m)]
            result.append({**future,
                "history_mean_wm2":historic["mean_wm2"],
                "history_energy_kwh_m2":historic["monthly_energy_kwh_m2"],
                "delta_mean_rsds_wm2":future["mean_wm2"]-historic["mean_wm2"],
                "delta_monthly_ghi_kwh_m2":future["monthly_energy_kwh_m2"]-historic["monthly_energy_kwh_m2"],
                "source":"NASA NEX-GDDP-CMIP6 v2.0, daily rsds",
                "historical_reference":"1995-2014"})
    return summary,result

def main():
    full={"status":"IN_PROGRESS","model":MODEL,"member":MEMBER,"site":SITE,
          "periods":PERIODS,"source":"NASA NEX-GDDP-CMIP6 v2.0",
          "source_data_license":"Research-only source; NASA qualification/citation required for engineering use",
          "began_utc":dt.datetime.now(dt.timezone.utc).isoformat(),"errors":[]}
    try:
        catalogs={scenario:catalog(scenario) for scenario in ("historical","ssp245","ssp585")}
        for group,(start,end) in PERIODS.items():
            scenario="historical" if group=="historical" else group.split("-")[0]
            for yr in range(start,end+1):
                if yr not in catalogs[scenario]:raise RuntimeError(f"Missing year in catalog {scenario}/{yr}")
                record=year_data(scenario,yr,catalogs[scenario][yr])
                YEARROWS.extend(record)
                first=record[0]
                print("YEAR",group,yr,"days",sum(x["days"] for x in record),
                     "jan",round(first["monthly_mean_wm2"],2),
                     "grid",first["grid_lat"],first["grid_lon"],flush=True)
        if len(YEARROWS)!=1200:raise RuntimeError(f"Expected 100 years * 12, got {len(YEARROWS)}")
        summary,anomalies=summarize(YEARROWS)
        full["status"]="PASS"
        full["year_count"]=100;full["year_month_count"]=len(YEARROWS)
        full["grid"]={"lat":YEARROWS[0]["grid_lat"],"lon":YEARROWS[0]["grid_lon"]}
        full["annual_ghi_kwh_m2"]={key:sum(summary[(key,m)]["monthly_energy_kwh_m2"] for m in range(1,13))
                                   for key in PERIODS}
        full["anomaly_records"]=len(anomalies)
        full["files_sha256_by_year"]={f'{r["scenario"]}/{r["year"]}':r["nc_sha256"] for r in YEARROWS if r["month"]==1}
        with (OUT/"daily_aggregated_year_month.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(YEARROWS[0]))
            writer.writeheader();writer.writerows(YEARROWS)
        with (OUT/"nex_gddp_cmip6_graz_rsds_anomalies.csv").open("w",newline="",encoding="utf-8") as f:
            writer=csv.DictWriter(f,fieldnames=list(anomalies[0]))
            writer.writeheader();writer.writerows(anomalies)
        print("SUMMARY",json.dumps(full["annual_ghi_kwh_m2"],ensure_ascii=False),flush=True)
    except Exception as e:
        full["status"]="FAIL"
        full["errors"].append(f"{type(e).__name__}: {e}")
        print("ERROR",repr(e),flush=True)
        raise
    finally:
        full["finished_utc"]=dt.datetime.now(dt.timezone.utc).isoformat()
        (OUT/"source_provenance.json").write_text(json.dumps(full,indent=2,ensure_ascii=False),encoding="utf8")
        (OUT/"README.md").write_text(
          "# NASA NEX-GDDP-CMIP6 v2.0 Graz solar rsds research\n\n"
          f"Result: {full['status']}\n\n"
          "100 yearly NASA NCSS spatial subsets (20 historical, 80 future) were"
          " obtained from the same model and member. Monthly solar energy is summed"
          " from each daily W/m² and subsequently averaged over 20 years.\n\n"
          "The reference is native 1995–2014; future windows are 2040–2059"
          " and 2080–2099, not calendar 2050 or 2100.\n\n"
          "Only an ACCESS-CM2 single-model case study; it MUST NOT be described"
          " as the same multi-model ensemble as World Bank CCKP median tas/pr.\n\n"
          "Independent POWER reference requires separate acquisition and validation."
          " No hourly solar generation or independently validated local solar simulation.\n",
          encoding="utf8")

if __name__=="__main__":
    main()
