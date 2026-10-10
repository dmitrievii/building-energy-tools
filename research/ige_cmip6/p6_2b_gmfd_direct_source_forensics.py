#!/usr/bin/env python3
"""P6.2B forensic GMFD -> BCSD -> NASA GHI root-cause verification.

Does not claim attribution unless the processed GMFD_for_GDDPv2
solar forcing at the correct pixel is actually retrieved and evaluated.
Original 0.25-degree NCAR d314000 is a related ARCHIVAL version, NOT
proof of equality to NASA's 1960-2014 processed training input.
"""
from __future__ import annotations
import argparse,csv,hashlib,json,math,tempfile,urllib.error,urllib.parse,urllib.request
from datetime import datetime,date
from pathlib import Path
from statistics import fmean
from collections import Counter
from xml.etree import ElementTree as ET

COORD=(46.875,15.375)
NASA_TECH="https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com/NEX-GDDP-CMIP6-v2-Tech_Note.pdf"
NCAR_ARCHIVE="https://tds.gdex.ucar.edu/thredds"
NCAR_PRODUCT="files/g/d314000/0.25deg/daily/dswrf_0p25_daily_2005-2005.nc"
NA_LINKS=(
 "https://ds.nccs.nasa.gov/thredds/catalog/AMES/NEX/GMFD_for_GDDPv2/catalog.xml",
 "https://nex-gddp-cmip6.s3.us-west-2.amazonaws.com/?list-type=2&prefix=GMFD_for_GDDPv2%2F&max-keys=10",
)
def sha(raw):return hashlib.sha256(raw).hexdigest()
def fetch(url,maximum=6_000_000,seconds=28):
    try:
        request=urllib.request.Request(url,headers={"Accept":"*/*",
          "User-Agent":"IGE-GMFD-SOLAR-SOURCE-FORENSICS-2026"})
        with urllib.request.urlopen(request,timeout=seconds) as response:
            buf=response.read(maximum+1)
            if response.status!=200 or len(buf)>maximum:
                raise RuntimeError(f"Bad HTTP {response.status}, bytes={len(buf)}")
            if not buf:raise ValueError("Empty provider response")
            return buf
    except Exception as exc:
        raise RuntimeError(f"{type(exc).__name__}: {str(exc)[:400]}") from exc

def probe_pdf(out):
    report={"source_url":NASA_TECH,"status":"UNAVAILABLE","hyperlinks":[]}
    try:
        from pypdf import PdfReader
        source=fetch(NASA_TECH,8_000_000,25)
        (out/"nasa_v2_technical_note.pdf").write_bytes(source)
        links=[]
        with tempfile.NamedTemporaryFile(suffix=".pdf") as t:
            t.write(source);t.flush()
            pdf=PdfReader(t.name)
            for index,page in enumerate(pdf.pages):
                for annotation in page.get("/Annots",[]) or []:
                    record=annotation.get_object()
                    target=(record.get("/A") or {}).get("/URI")
                    if target:
                        links.append({"page":index+1,"url":str(target)})
        report.update({"status":"PASS","bytes":len(source),"sha256":sha(source),
                       "pages":len(pdf.pages),"hyperlinks":links,
                       "gmfd_relevant_links":[v for v in links if "gmfd" in v["url"].lower()
                           or "forcing" in v["url"].lower()]})
    except Exception as exc:report["error"]=str(exc)[:900]
    return report

def probe_links(out,pdf_report):
    candidates=[{"url":u,"source":"candidate","name":"nasa_specific"} for u in NA_LINKS]
    for match in pdf_report.get("gmfd_relevant_links",[]):
        url=match["url"]
        if url.startswith("https://") or url.startswith("http://"):
            candidates.insert(0,{"url":url,"source":"NASA_v2_PDF_link","name":"nasa_specific"})
    result=[]
    seen=set()
    for item in candidates:
        if item["url"] in seen:continue
        seen.add(item["url"])
        rec=dict(item)
        try:
            blob=fetch(rec["url"],1200000,18)
            rec.update({"status":"RESPONSE_AVAILABLE","bytes":len(blob),
                        "sha256":sha(blob),
                        "response_preview":blob[:600].decode("utf-8","replace")})
            if len(blob)<30000:
                (out/f"gmfd_catalog_{len(result)}.txt").write_bytes(blob)
        except Exception as exc:rec.update({"status":"INACCESSIBLE","reason":str(exc)[:500]})
        result.append(rec)
    return result

def ncar_attempts(out):
    """Download only a point-subset; never entire ~1GB global yearly NCAR source."""
    base=NCAR_ARCHIVE+"/ncss/grid/"+NCAR_PRODUCT
    variants=[
        {"var":"dswrf","latitude":"46.875","longitude":"15.375",
         "time_start":"2005-01-01T00:00:00Z","time_end":"2005-12-31T00:00:00Z",
         "accept":"netcdf3"},
        {"var":"dswrf","north":"47","south":"46.75","west":"15.25","east":"15.5",
         "time_start":"2005-01-01T00:00:00Z","time_end":"2005-12-31T00:00:00Z",
         "accept":"netcdf3","addLatLon":"true"},
    ]
    sources=[]
    for q in variants:
        url=base+"?"+urllib.parse.urlencode(q)
        rec={"url":url,"status":"UNAVAILABLE"}
        try:
            blob=fetch(url,6_000_000,36)
            rec.update({"bytes":len(blob),"sha256":sha(blob)})
            if not (blob[:3]==b"CDF" or blob[:8]==b"\x89HDF\r\n\x1a\n"):
                rec.update({"status":"NOT_NETCDF","content_prefix":blob[:300].decode("utf8","replace")})
            else:
                path=out/f"ncar_original_gmfd_2005_subset_{len(sources)}.nc"
                path.write_bytes(blob)
                rec.update({"status":"NETCDF_AVAILABLE","path":path.name})
        except Exception as ex:rec["error"]=str(ex)[:500]
        sources.append(rec)
        if rec["status"]=="NETCDF_AVAILABLE":break
    return sources

def decode_ncar_subset(out, attempts):
    available=[i for i in attempts if i.get("status")=="NETCDF_AVAILABLE"]
    if not available:return {"status":"UNAVAILABLE","note":"No original 0.25° GMFD point subset received"}
    import netCDF4
    import numpy as np
    path=out/available[0]["path"]
    with netCDF4.Dataset(path,"r") as ds:
        names=list(ds.variables)
        axes={name:{"dims":list(v.dimensions),"units":str(getattr(v,"units",'')),
                    "shape":list(v.shape)} for name,v in ds.variables.items()}
        possible=[n for n in names if 'swrf' in n.lower() or
                  'down' in n.lower() and 'short' in n.lower()]
        if len(possible)!=1:
            return {"status":"VARIABLE_NOT_RESOLVED","variables":axes}
        var=ds.variables[possible[0]]
        unit=str(getattr(var,'units',''))
        canonical=unit.lower().replace(" ","").replace("_","")
        if canonical not in ("wm-2","wm**-2","w/m2","watts/m^2","wm^-2"):
            return {"status":"INVALID_UNITS","found_units":unit,"variables":axes}
        times=next((n for n in names if n.lower()=="time"),None)
        if times is None:return {"status":"TIME_AXIS_NOT_FOUND","variables":axes}
        t=ds.variables[times]
        dates=netCDF4.num2date(t[:],t.units,calendar=getattr(t,"calendar","standard"),
                               only_use_cftime_datetimes=True)
        lat_var=next((n for n in names if n.lower() in ("lat","latitude")),None)
        lon_var=next((n for n in names if n.lower() in ("lon","longitude")),None)
        if lat_var is None or lon_var is None:
            return {"status":"COORDINATES_MISSING","variables":axes}
        lats=np.array(ds.variables[lat_var][:],dtype=float)
        lons=np.array(ds.variables[lon_var][:],dtype=float)
        yy=int(np.argmin(abs(lats-COORD[0])))
        xx=int(np.argmin(abs(lons-COORD[1])))
        found=(float(lats[yy]),float(lons[xx]))
        if abs(found[0]-COORD[0])>.26 or abs(found[1]-COORD[1])>.26:
            return {"status":"WRONG_GRID_LOCATION","grid":found,"variables":axes}
        index=[]
        for name in var.dimensions:
            if name==t.dimensions[0]:index.append(slice(None))
            elif name==ds.variables[lat_var].dimensions[0]:index.append(yy)
            elif name==ds.variables[lon_var].dimensions[0]:index.append(xx)
            else:return {"status":"UNEXPECTED_VARIABLE_AXES","variables":axes}
        values=np.asarray(np.ma.filled(var[tuple(index)],np.nan),dtype=float).reshape(-1)
        if len(values)!=len(dates) or not all(math.isfinite(x) and 0<=x<=700 for x in values):
            return {"status":"INVALID_PHYSICAL_FLUX","day_count":len(values),"variables":axes}
        if not all(int(d.year)==2005 for d in dates):
            return {"status":"INVALID_YEAR","year_first":int(dates[0].year)}
        if len(values)!=365:
            return {"status":"INCOMPLETE_NCAR_YEAR","days":len(values),"variables":axes}
        annual=float(np.sum(values))*.024
        return {"status":"GMFD_ARCHIVAL_POINT_YEAR_AVAILABLE","origin":"NCAR_d314000_ARCHIVAL_NOT_NASA_PROCESSED",
                "grid":found,"variable":possible[0],"native_unit":unit,
                "day_count":len(values),"annual_ghi_kwh_m2":annual,
                "annual_mean_sw_w_m2":float(np.mean(values)),
                "monthly_kwh_m2":[float(np.sum([v for v,d in zip(values,dates) if int(d.month)==m]))*.024
                                  for m in range(1,13)],
                "nc_sha256":sha(path.read_bytes()),
                "warning":"NCAR archive ends in 2010, NASA processed v2 GMFD is a distinct input version; do not infer equality."}

def verify_original_nasa(out, original):
    """Read an independently downloaded native NASA annual rsds NetCDF subset."""
    from p6_daily_multivariable import catalog,fetch_one
    from p6_access_full_period import WINDOWS
    if "historical-1995-2014" not in WINDOWS:raise ValueError("Baseline changed")
    src=catalog("historical","rsds")[2005]
    payload,prov=fetch_one("historical",2005,"rsds",src)
    flux=[float(v) for v in payload["values"]]
    if not 365<=len(flux)<=366 or not all(0<=v<=750 for v in flux):
        raise ValueError("Invalid independently fetched NASA annual solar")
    expected={}
    with (original/"joint_daily_raw.csv").open(encoding="utf8",newline="") as f:
        for row in csv.DictReader(f):
            if int(row["year"])==2005:
                expected[(int(row["month"]),int(row["day"]))]=float(row["rsds"])
    if len(expected)!=len(flux):raise ValueError("Original NASA P6.1 day mismatch")
    if any(abs(float(v)-expected[int(m),int(d)])>1e-5
           for v,(y,m,d) in zip(flux,payload["days"])):
        # The source key is by (month,day), not by a synthetic model day-of-year
        raise ValueError("Original NASA independent native NetCDF disagrees with P6.1 CSV")
    annual=sum(flux)*.024
    return {"status":"PASS_RAW_NATIVE_NASA_CONFIRMATION","year":2005,
            "daily_count":len(flux),"annual_kwh_m2":annual,
            "annual_mean_w_m2":fmean(flux),
            "grid":[payload["lat"],payload["lon"]],
            "variable":"rsds","units":payload["unit"],
            "netcdf_uncompressed_sha256":prov["sha256"],
            "source_url":prov["url"]}

def execute(out,original):
    out.mkdir(parents=True,exist_ok=True)
    result={"phase":"P6.2B_SCIENTIFIC_GMFD_DIRECT_CAUSE_TEST",
            "do_not_mutate_model_outputs":True,
            "target_nasa_cell":{"lat":COORD[0],"lon":COORD[1]},
            "sources":{"nasa_technical_note":None,"nasa_processed_gmfd":[],
                        "ncar_archival_source":None,"raw_nasa_netCDF":None}}
    pdf=probe_pdf(out)
    result["sources"]["nasa_technical_note"]=pdf
    print("GMFD NASA TECH NOTE",pdf["status"],
          "gmfd links",len(pdf.get("gmfd_relevant_links",[])),flush=True)
    links=probe_links(out,pdf)
    result["sources"]["nasa_processed_gmfd"]=links
    print("NASA PROCESSED GMFD",[(l["source"],l["status"]) for l in links],flush=True)
    probes=ncar_attempts(out)
    result["sources"]["ncar_archival_probe"]=probes
    try:
        ncar=decode_ncar_subset(out,probes)
        result["sources"]["ncar_archival_source"]=ncar
    except Exception as ex:
        result["sources"]["ncar_archival_source"]={"status":"SOURCE_EXCEPTION",
                                                 "error":f"{type(ex).__name__}: {str(ex)[:900]}"}
    print("GMFD NCAR SOURCE",result["sources"]["ncar_archival_source"].get("status"),flush=True)
    try:
        nasa=verify_original_nasa(out,original)
        result["sources"]["raw_nasa_netCDF"]=nasa
    except Exception as ex:
        result["sources"]["raw_nasa_netCDF"]={"status":"SOURCE_EXCEPTION",
                                              "error":f"{type(ex).__name__}: {str(ex)[:900]}"}
    print("NASA INDEPENDENT NCSS",result["sources"]["raw_nasa_netCDF"]["status"],flush=True)
    ncar=result["sources"]["ncar_archival_source"]
    nasa=result["sources"]["raw_nasa_netCDF"]
    if ncar.get("annual_ghi_kwh_m2") is not None and nasa.get("annual_kwh_m2") is not None:
        result["compared_2005_annual"]={
            "ncar_archival_gmfd_kwh_m2":ncar["annual_ghi_kwh_m2"],
            "nasa_v2_rsds_kwh_m2":nasa["annual_kwh_m2"],
            "nasa_minus_ncar_archival_kwh_m2":
                nasa["annual_kwh_m2"]-ncar["annual_ghi_kwh_m2"],
            "warning":"Archival forcing is not a proven byte-identical version of processed NASA v2 reference"
        }
    result["root_cause_attribution_status"]="NOT_PROVEN_UNTIL_NASA_PROCESSED_GMFD_AT_SAME_CELL_IS_EXTRACTED"
    result["next_required_source"]="GMFD_for_GDDPv2 processed dswrf at 46.875N 15.375E, 1995-2014"
    (out/"direct_gmfd_root_cause_report.json").write_text(
        json.dumps(result,indent=2,ensure_ascii=False)+"\n",encoding="utf8")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--original",type=Path,required=True)
    a=p.parse_args()
    execute(a.out,a.original)
if __name__=="__main__":main()
