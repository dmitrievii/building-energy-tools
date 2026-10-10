#!/usr/bin/env python3
import urllib.request,urllib.parse,json,pathlib,datetime,hashlib
out=pathlib.Path("outputs/power");out.mkdir(parents=True,exist_ok=True)
url="https://power.larc.nasa.gov/api/temporal/monthly/point?"+urllib.parse.urlencode({
 "parameters":"ALLSKY_SFC_SW_DWN","community":"RE","longitude":15.450,
 "latitude":46.983,"start":1991,"end":2020,"format":"JSON"})
req=urllib.request.Request(url,headers={"User-Agent":"IGE-Independent-Climate-Engine-Research/0.3","Accept":"application/json"})
with urllib.request.urlopen(req,timeout=90) as r:
 buf=r.read(5000000); print("NASA_POWER_HTTP",r.status,"MIME",r.headers.get("Content-Type"),"BYTES",len(buf),flush=True)
d=json.loads(buf);print("SOURCE_KEYS",list(d),flush=True)
print("PROPERTIES",str(d.get("properties",{}))[:1200],flush=True)
params=d["properties"]["parameter"]; data=params["ALLSKY_SFC_SW_DWN"]
keyed=[k for k in data if k.isdigit() and len(k)==6 and 1991<=int(k[:4])<=2020]
print("HISTORICAL_ROWS",len(keyed),"SAMPLE",list(data.items())[:4],flush=True)
if len(keyed)<360:raise RuntimeError("NASA POWER lacks 360 monthly records")
(out/"nasa_power_graz_monthly_1991_2020.json").write_bytes(buf)
(out/"source.json").write_text(json.dumps({"url":url,"timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat(),
  "sha256":hashlib.sha256(buf).hexdigest(),"months":len(keyed)}),encoding="utf8")
