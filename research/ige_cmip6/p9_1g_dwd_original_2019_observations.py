#!/usr/bin/env python3
"""IGE P9.1G original DWD 2019 hourly TT_TU QC=10, geography outside Austria.

Fixed 4 stations; no arbitrary selection on skill, no hourly source republishing.
"""
from __future__ import annotations
import csv,datetime as dt,hashlib,html,io,json,math,re,time,urllib.error,urllib.parse,urllib.request,zipfile
from pathlib import Path

ROOT="https://opendata.dwd.de/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/"
STATION_IDS=(3987,4271,3730,2290)
LABELS={3987:"Potsdam",4271:"Rostock-Warnemuende",
        3730:"Oberstdorf",2290:"Hohenpeissenberg"}
MAX_FILE=8*1024*1024
QC_FINAL=frozenset((10,))
SEASONS=(("winter_2019","2019-01-10","2019-01-16"),
         ("autumn_2019","2019-10-10","2019-10-16"))


def get_original(url,maximum=MAX_FILE):
    u=urllib.parse.urlsplit(url)
    if (u.scheme!="https" or u.hostname!="opendata.dwd.de" or
            not u.path.startswith(
              "/climate_environment/CDC/observations_germany/climate/hourly/air_temperature/historical/")):
        raise ValueError("P9G_DWD_ONLY_ALLOWLISTED_HISTORICAL_CDC_SOURCE")
    req=urllib.request.Request(url,headers={
        "User-Agent":"IGE-P9.1G-independent-DWD-qualified-historical-2019"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req,timeout=90) as r:
                data=r.read(maximum+1)
            if len(data)>maximum:raise ValueError("P9G_DWD_DOWNLOAD_TOO_LARGE")
            return data
        except urllib.error.HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==3:raise
        except (TimeoutError,urllib.error.URLError):
            if attempt==3:raise
        time.sleep(2**(attempt+1))
    raise RuntimeError("P9G_ORIGINAL_DWD_NO_SILENT_FALLBACK")


def fixed_zip_filenames(listing):
    text=listing.decode("utf8",errors="replace")
    found={}
    for sid in STATION_IDS:
        matches=set(re.findall(
            rf'stundenwerte_TU_{sid:05d}_(\d{{8}})_(\d{{8}})_hist\.zip',
            text,re.I))
        eligible=[(start,end) for start,end in matches
                  if start<="20190110" and end>="20191016"]
        if len(eligible)!=1:
            raise ValueError("P9G_DWD_ORIGINAL_2019_ARCHIVE_MISSING_OR_AMBIGUOUS_"+str(sid))
        start,end=eligible[0]
        found[sid]=f"stundenwerte_TU_{sid:05d}_{start}_{end}_hist.zip"
    return found


def parse_original_metadata(original):
    text=original.decode("latin1",errors="replace")
    sites={}
    for row in text.splitlines():
        fields=row.split(maxsplit=6)
        if len(fields)<7 or not fields[0].isdigit():continue
        sid=int(fields[0])
        if sid not in STATION_IDS:continue
        try:
            start,end=fields[1],fields[2]
            alt=float(fields[3].replace(",","."))
            lat=float(fields[4].replace(",","."))
            lon=float(fields[5].replace(",","."))
        except ValueError:continue
        if not(start<="20190110" and end>="20191016"):
            raise ValueError("P9G_DWD_STATION_METADATA_NOT_COVERING_2019")
        if not(-90<lat<90 and -180<lon<180 and -500<alt<6000):
            raise ValueError("P9G_DWD_INVALID_ORIGINAL_STATION_GEOGRAPHY")
        if sid in sites:raise ValueError("P9G_DWD_DUPLICATE_STATION_METADATA")
        sites[sid]={"id":sid,"name":LABELS[sid],"lat":lat,"lon":lon,
                    "altitude_m":alt,"source_record":row}
    if set(sites)!=set(STATION_IDS):
        raise ValueError("P9G_DWD_ORIGINAL_METADATA_STATION_MISSING")
    return sites


def parse_original_zip(raw,sid):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        bad=z.testzip()
        if bad:raise ValueError("P9G_DWD_SOURCE_ZIP_CRC_INVALID_"+bad)
        names=[n for n in z.namelist()
               if Path(n).name.startswith("produkt_tu_stunde_") and n.lower().endswith(".txt")]
        if len(names)!=1:raise ValueError("P9G_DWD_TU_2019_ORIGINAL_CSV_NOT_UNIQUE")
        name=names[0]
        if z.getinfo(name).file_size>16*1024*1024:
            raise ValueError("P9G_DWD_UNCOMPRESSED_CSV_EXCESSIVE")
        src=z.read(name).decode("latin1")
    reader=csv.DictReader(io.StringIO(src),delimiter=";")
    fields=set(reader.fieldnames or ())
    if not {"STATIONS_ID","MESS_DATUM","QN_9","TT_TU"}.issubset(fields):
        raise ValueError("P9G_DWD_SOURCE_TU_QC_TEMPERATURE_COLUMNS_MISSING_"+repr(fields))
    periods={}
    per_year={}
    for season,start,end in SEASONS:
        n=168;startdt=dt.datetime.fromisoformat(start+"T00:00:00")
        periods[season]={(startdt+dt.timedelta(hours=i)).strftime("%Y%m%d%H")
                         for i in range(n)}
        per_year[season]={}
    flags={season:{} for season,_,_ in SEASONS}
    for row in reader:
        timestamp=row.get("MESS_DATUM","").strip()
        season=next((name for name,_,_ in SEASONS if timestamp in periods[name]),None)
        if season is None:continue
        if int(row["STATIONS_ID"])!=sid:
            raise ValueError("P9G_DWD_ORIGINAL_SOURCE_STATION_ID_MISMATCH")
        if timestamp in flags[season]:
            raise ValueError("P9G_DWD_DUPLICATED_SOURCE_UTC_STATION_HOUR")
        raw_QC=row.get("QN_9","").strip()
        qc=int(raw_QC) if raw_QC else -999
        flags[season][timestamp]=qc
        val=float(row.get("TT_TU","-999").strip())
        if qc not in QC_FINAL or val<=-999 or not -80<val<65:
            continue
        per_year[season][dt.datetime.strptime(timestamp,"%Y%m%d%H")
                         .strftime("%Y-%m-%dT%H:%M")]=val
    return {
        "source_zip_original_SHA256":hashlib.sha256(raw).hexdigest(),
        "source_product_member":name,
        "original_QC_histograms":{season:dict(sorted(
            {k:sum(v==k for v in flags[season].values())
             for k in set(flags[season].values())}.items()))
            for season,_,_ in SEASONS},
        "QC_accepted_original_source_hours":{k:len(v) for k,v in per_year.items()},
        "hourly_QC_accepted_TT_TU_for_scoring_PRIVATE":per_year,
    }


def retrieve_all():
    listing=get_original(ROOT,maximum=1500000)
    metadata=get_original(ROOT+"TU_Stundenwerte_Beschreibung_Stationen.txt",maximum=1200000)
    sites=parse_original_metadata(metadata)
    paths=fixed_zip_filenames(listing)
    source={}
    for sid in STATION_IDS:
        raw=get_original(ROOT+paths[sid])
        source[sid]=parse_original_zip(raw,sid)
        print("P9G_DWD_ORIGINAL_SOURCE",json.dumps({
            "id":sid,"name":LABELS[sid],"archive":paths[sid],
            "QC_final_10_hours":source[sid]["QC_accepted_original_source_hours"],
            "QN_9_histograms":source[sid]["original_QC_histograms"]}),flush=True)
    return sites,source,{
        "historical_original_directory_SHA256":hashlib.sha256(listing).hexdigest(),
        "original_station_geography_metadata_SHA256":hashlib.sha256(metadata).hexdigest(),
        "historical_2019_ZIP_pinned_ID_archive_paths":paths,
        "source_DWD_QN_9_acceptance_only_final_QC_10":True,
        "no_2019_station_temperature_values_are_published":True,
    }
