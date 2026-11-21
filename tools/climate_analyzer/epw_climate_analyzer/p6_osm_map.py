"""One on-demand OSM viewport for a printed station map.
Uses the same standard raster basemap as Find climate; no bulk prefetch.
"""
from __future__ import annotations
import io
import math
import os
import tempfile
import time
import json
from pathlib import Path
from email.utils import parsedate_to_datetime
import requests
from PIL import Image, ImageDraw
import plotly.graph_objects as go

ATTRIBUTION="© OpenStreetMap contributors · openstreetmap.org/copyright"
CACHE=Path(tempfile.gettempdir())/"ige_report_osm_v1"
TILE_URL=os.environ.get("IGE_REPORT_MAP_TILE_URL","https://tile.openstreetmap.org/{z}/{x}/{y}.png")
USER_AGENT="IGE-ClimateAnalyzer-Report/1.0 (+https://github.com/dmitrievii/building-energy-tools)"
def coordinates(c):
    try:lat,lon=float(c["latitude"]),float(c["longitude"])
    except (KeyError,TypeError,ValueError):return None
    if not (math.isfinite(lat) and math.isfinite(lon) and -85.05112878<=lat<=85.05112878 and -180<=lon<=180):return None
    return lat,lon

def tile_image(z,x,y):
    # Respect HTTP cache freshness; when absent use OSM's seven-day default.
    import hashlib
    key=hashlib.sha256(f"{TILE_URL}/{z}/{x}/{y}".encode()).hexdigest()
    path=CACHE/(key+".png");meta=CACHE/(key+".json")
    previous={}
    try:
        previous=json.loads(meta.read_text())
        if time.time()<float(previous["expires"]):
            with Image.open(path) as im:return im.convert("RGB")
    except (OSError,ValueError,KeyError):pass
    headers={"User-Agent":USER_AGENT}
    if path.exists():
        if previous.get("etag"):headers["If-None-Match"]=previous["etag"]
        if previous.get("last_modified"):headers["If-Modified-Since"]=previous["last_modified"]
    with requests.get(TILE_URL.format(z=z,x=x,y=y),headers=headers,timeout=(3,5),stream=True) as response:
        response.raise_for_status()
        if response.status_code==304:
            raw=path.read_bytes()
        else:
            chunks=[];size=0
            for chunk in response.iter_content(16384):
                size+=len(chunk)
                if size>2*1024*1024:raise ValueError("Oversized map tile")
                chunks.append(chunk)
            raw=b"".join(chunks)
        with Image.open(io.BytesIO(raw)) as image:
            if image.size!=(256,256):raise ValueError("Unexpected map tile geometry")
            im=image.convert("RGB")
        cc=response.headers.get("Cache-Control","").lower()
        seconds=7*86400
        for part in cc.split(","):
            key2,sep,v=part.strip().partition("=")
            if key2=="max-age" and v.isdigit():seconds=int(v)
        if "max-age" not in cc and response.headers.get("Expires"):
            try:seconds=max(0,parsedate_to_datetime(response.headers["Expires"]).timestamp()-time.time())
            except (TypeError,ValueError,OverflowError):pass
        try:seconds=max(0,seconds-int(response.headers.get("Age","0")))
        except ValueError:pass
        if "no-cache" in cc:seconds=0
        if "no-store" not in cc:
            try:
                CACHE.mkdir(parents=True,exist_ok=True)
                # Bounded cache: do not continue writing on a full cache.
                if path.exists() or len(list(CACHE.glob("*.png")))<512:
                    with tempfile.NamedTemporaryFile(dir=CACHE,delete=False) as f:
                        f.write(raw);tmp=f.name
                    os.replace(tmp,path)
                    meta.write_text(json.dumps({"expires":time.time()+seconds,"etag":response.headers.get("ETag",previous.get("etag")),"last_modified":response.headers.get("Last-Modified",previous.get("last_modified"))}))
            except OSError:pass
        return im

def osm_figure(c,*,zoom=9,tile_loader=None):
    coordinate=coordinates(c)
    if coordinate is None:return None
    lat,lon=coordinate
    if tile_loader is None:tile_loader=tile_image
    z=int(zoom)
    if not 2<=z<=14:raise ValueError("Invalid report map zoom")
    n=2**z;world=n*256
    cx=(lon+180)/360*world
    cy=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)*world/2
    width,height=640,320
    left,top=math.floor(cx-width/2),math.floor(cy-height/2)
    top=max(0,min(world-height,top))
    img=Image.new("RGB",(width,height),"#e0e8ed")
    for ty in range(top//256,(top+height-1)//256+1):
        for tx in range(left//256,(left+width-1)//256+1):
            tile=tile_loader(z,tx%n,ty)
            img.paste(tile,(tx*256-left,ty*256-top))
    px,py=cx-left,cy-top
    draw=ImageDraw.Draw(img)
    draw.ellipse((px-8,py-8,px+8,py+8),fill="#FFFFFF")
    draw.ellipse((px-5,py-5,px+5,py+5),fill="#BD332D")
    # Attribution also appears as native report text, not embedded solely in the raster.
    f=go.Figure(go.Scatter(x=[px],y=[height-py],mode="text",text=[str(c.get("location","Station"))],
                          textposition="top center",showlegend=False,hoverinfo="skip"))
    # Station name is readable even over a busy basemap.
    f.data[0].text=None
    f.add_layout_image(dict(source=img,x=0,y=height,sizex=width,sizey=height,xref="x",yref="y",xanchor="left",yanchor="top",sizing="stretch",layer="below"))
    f.add_annotation(x=px,y=height-py,text=str(c.get("location","Station")),showarrow=True,ax=0,ay=-26,
        bgcolor="white",bordercolor="#BDC5CA",borderpad=3,font=dict(size=13,color="#202830"))
    f.update_layout(template="plotly_white",title="Station location",meta={"report_kind":"station_locator","map_attribution":ATTRIBUTION},
        margin=dict(l=8,r=8,t=8,b=8),width=656,height=336,
        xaxis=dict(range=[0,width],scaleanchor="y",scaleratio=1,constrain="domain",visible=False,fixedrange=True),
        yaxis=dict(range=[0,height],constrain="domain",visible=False,fixedrange=True))
    return f

def export_locator(c,*,use_osm=False):
    from .p6_report_structure import locator_figure
    if use_osm:
        try:
            f=osm_figure(c)
            if f is not None:return f,ATTRIBUTION
        except (requests.RequestException,OSError,ValueError):pass
    f=locator_figure(c)
    return f,"Station locator · Natural Earth, 1:110m · offline fallback" if use_osm else "Station locator · Natural Earth, 1:110m"
