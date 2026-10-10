#!/usr/bin/env python3
"""Read-only NOAA/NASA GDDP-CMIP6 solar radiation source connectivity probe."""
import json, pathlib, datetime, urllib.request, urllib.parse, traceback
OUT=pathlib.Path("outputs/solar_probe");OUT.mkdir(parents=True,exist_ok=True)
base="https://ds.nccs.nasa.gov"
models=[
    ("ACCESS-CM2","r1i1p1f1","historical",2014),
    ("ACCESS-CM2","r1i1p1f1","ssp245",2050),
    ("ACCESS-CM2","r1i1p1f1","ssp585",2090),
]
rows=[]
def request(url,max_bytes=3_000_000):
    req=urllib.request.Request(url,headers={"User-Agent":"IGE-Climate-Engine-Independent-Research/0.3","Accept":"*/*"})
    with urllib.request.urlopen(req,timeout=55) as res:
       blob=res.read(max_bytes)
       return {"status":res.status,"content_type":res.headers.get("Content-Type"),"bytes":len(blob),
               "url":res.url,"sample":blob[:400].decode("utf-8","replace")}
for model,member,scenario,year in models:
    path=f"/thredds/catalog/AMES/NEX/GDDP-CMIP6/{model}/{scenario}/{member}/rsds/catalog.xml"
    url=base+path
    try:
      item=request(url)
      print("CATALOG_OK",scenario,year,item["status"],item["content_type"],item["bytes"],item["sample"][:100],flush=True)
      rows.append({"scenario":scenario,"year":year,"kind":"catalog","request_url":url,**item})
    except Exception as exc:
      print("CATALOG_FAIL",scenario,year,type(exc).__name__,str(exc),flush=True)
      rows.append({"scenario":scenario,"year":year,"kind":"catalog","request_url":url,"error":str(exc)})
    basename=f"rsds_day_{model}_{scenario}_{member}_gn_{year}.nc"
    path=f"/thredds/ncss/grid/AMES/NEX/GDDP-CMIP6/{model}/{scenario}/{member}/rsds/{basename}"
    query=urllib.parse.urlencode({"var":"rsds","north":"47.11","south":"46.88","west":"15.33","east":"15.59",
        "time_start":f"{year}-06-01T12:00:00Z","time_end":f"{year}-06-05T12:00:00Z","accept":"netcdf3","addLatLon":"true"})
    url=base+path+"?"+query
    try:
      item=request(url)
      print("NCSS_OK",scenario,year,item["status"],item["content_type"],item["bytes"],item["sample"][:100],flush=True)
      rows.append({"scenario":scenario,"year":year,"kind":"ncss","request_url":url,**item})
    except Exception as exc:
      print("NCSS_FAIL",scenario,year,type(exc).__name__,str(exc),flush=True)
      rows.append({"scenario":scenario,"year":year,"kind":"ncss","request_url":url,"error":str(exc)})
(OUT/"nasa_ncss_probe.json").write_text(json.dumps({"date_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "results":rows},ensure_ascii=False,indent=2),encoding="utf-8")
if not any(x.get("kind")=="ncss" and x.get("status")==200 and x.get("content_type","").lower().startswith("application") for x in rows):
  raise SystemExit("No validated NCSS binary response")
