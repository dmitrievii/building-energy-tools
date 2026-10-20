#!/usr/bin/env python3
"""P9.3B2D frozen original DWD urban 00399 2023 pressure holdout, no tuning.

Uses true station P0_ST_10, NOT sea-level PP_ST_10.
Original DWD hourly P is sea-level, P0 station-level: separate erratum.
This new urban holdout is the ONLY unseen German pressure skill experiment.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,io,json,math,statistics,re,zipfile
from pathlib import Path

from p9_3b2d_alternate_dwd_source_only import (SOURCES,WINDOWS,fetch,
    original_archive_name,parse_time)
from p9_3b2c_original_geopotential_and_Potsdam_2023_pressure_validation import original_era5
from p9_3b2c_arco_original_surface_geopotential_probe import read_arco
from p9_3b2_hypsometric_pressure_model import correct_pressure

FROZEN=next(s for s in SOURCES if s["family"]=="URBAN_10MIN" and s["id"]=="00399")
LABEL="DWD_URBAN_PUBLISHED_NO_PER_SAMPLE_QC"
MIN_HOURS=144
MEASUREMENT="P0_ST_10"
SEA_LEVEL="PP_ST_10"


def parse_station_metadata(raw):
    entries=[x.strip() for x in raw.decode("latin1").splitlines()
             if re.match(r"^\s*0?0399\s",x)]
    if len(entries)!=1:
        raise ValueError("P93B2D_DWD_URBAN_STATION_00399_ORIGINAL_METADATA_NOT_UNIQUE")
    fields=entries[0].split(maxsplit=6)
    if len(fields)<6 or int(fields[0])!=399:
        raise ValueError("P93B2D_ORIGINAL_METADATA_EXPECTED_STATION_ID")
    z=float(fields[3]);lat=float(fields[4]);lon=float(fields[5])
    if not (0<z<1400 and 45<lat<56 and 5<lon<16):
        raise ValueError("P93B2D_SOURCE_STATION_GEOMETRY_NONPHYSICAL")
    return {"id":"00399","source_record":entries[0],
            "station_height_m":z,"lat":lat,"lon":lon,
            "coordinates_from_original_DWD_source":True}


def read_original_station(raw):
    data={season:{} for season in WINDOWS}
    quality={season:{} for season in WINDOWS}
    with zipfile.ZipFile(io.BytesIO(raw)) as zip_:
        if zip_.testzip() is not None:
            raise ValueError("P93B2D_ORIGINAL_URBAN_ARCHIVE_ZIP_CRC_FAIL")
        names=[n for n in zip_.namelist() if Path(n).name.lower().startswith("produkt")
               and n.lower().endswith(".txt")]
        if len(names)!=1:
            raise ValueError("P93B2D_URBAN_NATIVE_CSV_NOT_UNIQUE")
        with io.TextIOWrapper(zip_.open(names[0]),encoding="latin1") as handle:
            reader=csv.DictReader(handle,delimiter=";")
            col=set(str(v).strip() for v in reader.fieldnames or [])
            required={"STATIONS_ID","MESS_DATUM","QN",MEASUREMENT,SEA_LEVEL}
            if not required.issubset(col):
                raise ValueError("P93B2D_URBAN_STATION_OR_SEALEVEL_FIELDS_NOT_CERTIFIED")
            for row in reader:
                when=parse_time(row.get("MESS_DATUM"),"URBAN_10MIN")
                season=next((k for k,(start,end) in WINDOWS.items()
                             if when and start<=when<=end),None)
                if season is None:
                    continue
                if int(row["STATIONS_ID"])!=399:
                    raise ValueError("P93B2D_ORIGINAL_STATION_ID_MISMATCH")
                time=dt.datetime.strptime(when,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
                if time in quality[season]:
                    raise ValueError("P93B2D_ORIGINAL_DUPLICATE_UTC_STATION_HOUR")
                qc=(row.get("QN") or "").strip()
                quality[season][time]=qc
                # P0_ST_10 is station QFE. Never fallback to PP_ST_10.
                try: p=float(row[MEASUREMENT])
                except (TypeError,ValueError): continue
                if math.isfinite(p) and 450<p<1100:
                    data[season][time]=p
    return data,quality


def measures(original,forecast,period):
    start,end=WINDOWS[period]
    # Only the pre-registered original 168 hours in UTC; no shifting.
    t0=dt.datetime.strptime(start,"%Y%m%d%H")
    times=[(t0+dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M")
           for h in range(168)]
    common=[t for t in times if t in original and t in forecast]
    if len(common)<MIN_HOURS:
        return {"status":"INSUFFICIENT_FROZEN_EXACT_HOUR_STATION_PRESSURE",
                "n_original":len(original),"n_pairs":len(common),"metrics":{}}
    result={}
    for name in ("B0_ERA5_GRID","B3_PROVIDER_HEIGHT","B4_ARCO_GEOPOTENTIAL"):
        errors=[forecast[t][name]-original[t] for t in common]
        result[name]={"N":len(errors),"MAE_hPa":statistics.fmean(map(abs,errors)),
                      "RMSE_hPa":math.sqrt(statistics.fmean(e*e for e in errors)),
                      "bias_hPa":statistics.fmean(errors)}
    return {"status":"ORIGINAL_URBAN_STATION_PRESSURE_SCORED_NO_PER_SAMPLE_QC",
        "n_original":len(original),"n_pairs":len(common),"metrics":result,
        "B4_minus_B0_MAE_hPa":result["B4_ARCO_GEOPOTENTIAL"]["MAE_hPa"]-
                            result["B0_ERA5_GRID"]["MAE_hPa"],
        "B4_minus_B3_MAE_hPa":result["B4_ARCO_GEOPOTENTIAL"]["MAE_hPa"]-
                            result["B3_PROVIDER_HEIGHT"]["MAE_hPa"]}


def synthetic_contracts():
    p=correct_pressure(985.,12.,8.,380.,400.,"ISOTHERMAL_VIRTUAL_T")
    assert p>985.
    p=correct_pressure(985.,12.,8.,400.,380.,"ISOTHERMAL_VIRTUAL_T")
    assert p<985.
    assert abs(correct_pressure(985.,12.,8.,380.,380.,"ISOTHERMAL_VIRTUAL_T")-985.)<1e-10
    assert MEASUREMENT=="P0_ST_10" and SEA_LEVEL=="PP_ST_10"
    assert MEASUREMENT!=SEA_LEVEL
    assert all(len(k)==10 and int(k[-2:]) in (0,23)
               for bounds in WINDOWS.values() for k in bounds)
    out=measures({"2023-01-10T00:00":930.},
                 {"2023-01-10T00:00":{"B0_ERA5_GRID":929.,
                     "B3_PROVIDER_HEIGHT":930.,"B4_ARCO_GEOPOTENTIAL":930.}},
                 "JAN_2023")
    assert out["status"].startswith("INSUFFICIENT") and not out["metrics"]
    print("P93B2D_FROZEN_ORIGINAL_URBAN_PRESSURE_PHYSICAL_CONTRACTS_PASS",flush=True)


def run(out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    report={"phase":"P9_3B2D_FROZEN_2023_DWD_URBAN_ORIGINAL_SITE_PRESSURE",
       "pre_registered":"docs/IGE_P9_3B2D_FROZEN_URBAN_2023_PRESSURE_HOLDOUT_PREREG_RU.md",
       "original_source_pressure":"DWD climate_urban P0_ST_10 absolute station level hPa",
       "sea_level_pressure_PP_ST_10_used_as_station_pressure":False,
       "observed_station_P_used_in_prediction":False,
       "source_GCM_native_high_frequency_ps_recovered":False,
       "full_AT_DE_CH_pressure_quality_qualified":False,
       "production_epw_ready":False,
       "native_sensor_quality":"NO_NATIVE_PER_SAMPLE_QN_PRESENT_2023",
       "station_source_tier":LABEL,"registered_2023_windows":WINDOWS,"cells":[]}
    try:
        root=FROZEN["root"]
        m,ms=fetch(root+FROZEN["meta"],1_000_000)
        ls,lsha=fetch(root,3_000_000)
        station=parse_station_metadata(m)
        filename=original_archive_name(ls,FROZEN)
        raw,sha=fetch(root+filename)
        observed,native_qn=read_original_station(raw)
        if any(len(observed[season])<MIN_HOURS for season in WINDOWS):
            raise ValueError("P93B2D_URBAN_FROZEN_2023_STATION_VALUES_BELOW_CENSUS_GATE")
        if any(any(x!="" for x in native_qn[season].values()) for season in WINDOWS):
            # Unlike a source schema QC claim, nonblank QN would require
            # preregistered QC-tier requalification. No post-hoc filter.
            raise ValueError("P93B2D_QN_FIELD_CHANGED_FROM_CENSUS")
        report["original_DWD_station_metadata"]=station
        report["original_DWD_metadata_SHA256"]=ms
        report["original_DWD_listing_SHA256"]=lsha
        report["original_DWD_archive"]=filename
        report["original_DWD_archive_SHA256"]=sha
        # Anchor OM selected grid from original returned source, then obtain
        # native surface (not pressure-level) ERA5-derived ARCO z at that grid.
        latitude,longitude=station["lat"],station["lon"]
        raw_predictions={};source_metadata={}
        for season,(start,end) in WINDOWS.items():
            start_=dt.datetime.strptime(start,"%Y%m%d%H").date().isoformat()
            end_=dt.datetime.strptime(end,"%Y%m%d%H").date().isoformat()
            p,meta=original_era5(latitude,longitude,start_,end_)
            source_metadata[season]=meta
            raw_predictions[season]=p
        grids={(float(m["selected_cell_latitude"]),float(m["selected_cell_longitude"]))
               for m in source_metadata.values()}
        if len(grids)!=1:
            raise ValueError("P93B2D_ERA5_SELECTED_GRID_JAN_JUL_INCONSISTENT")
        grid=next(iter(grids))
        arco=read_arco({"DWD_URBAN_00399_2023":grid})
        z_arco=float(arco["points"]["DWD_URBAN_00399_2023"]
                     ["ERA5_ARCO_surface_geopotential_height_m"])
        report["ARCO_original_ERA5_surface_reference"]={
          "source":arco["arco_dataset"],"source_kind":arco["source_kind"],
          "original_variable":arco["original_ARCO_variable"],
          "grid":list(grid),"height_m":z_arco,
          "CDS_native_spectral_grid_verified":False}
        for season in WINDOWS:
            sm=source_metadata[season]
            response_z=float(sm["response_elevation_m_unverified"])
            pred={}
            for t,(p,T,dp) in raw_predictions[season].items():
                pred[t]={
                    "B0_ERA5_GRID":p,
                    "B3_PROVIDER_HEIGHT":correct_pressure(
                        p,T,dp,station["station_height_m"],response_z,
                        "ISOTHERMAL_VIRTUAL_T"),
                    "B4_ARCO_GEOPOTENTIAL":correct_pressure(
                        p,T,dp,station["station_height_m"],z_arco,
                        "ISOTHERMAL_VIRTUAL_T")}
            score=measures(observed[season],pred,season)
            score["season"]=season
            score["station_source_original_records"]=len(native_qn[season])
            score["original_observation_QN_missing_count"]=sum(
                not v for v in native_qn[season].values())
            score["original_ERA5_canonical_SHA"]=sm["canonical_hourly_weather_and_selected_cell_sha256"]
            score["provider_grid_elevation_m"]=response_z
            score["ARCO_minus_provider_height_m"]=z_arco-response_z
            score["same_UTC_hour_but_not_verified_same_temporal_support"]=True
            report["cells"].append(score)
            print("P93B2D_FROZEN_GERMAN_URBAN_PRESSURE_ORIGINAL_SCORE",
                  json.dumps({"season":season,"status":score["status"],
                   "N":score["n_pairs"],
                   "MAE":{name:round(row["MAE_hPa"],4) for name,row
                          in score["metrics"].items()},
                   "original_sensor_native_QC":"MISSING"}),flush=True)
        if all(c["status"].startswith("ORIGINAL_URBAN") for c in report["cells"]):
            report["B4_2000m_both_seasons"]=all(
                c["metrics"]["B4_ARCO_GEOPOTENTIAL"]["MAE_hPa"]<=2.
                for c in report["cells"])
            report["B4_better_than_B0_both_seasons"]=all(
                c["B4_minus_B0_MAE_hPa"]<0 for c in report["cells"])
            report["preregistered_exploratory_accuracy_gate"]=(
                report["B4_2000m_both_seasons"] and
                report["B4_better_than_B0_both_seasons"])
            report["status"]=("EXPLORATORY_ORIGINAL_PRESSURE_ACCURACY_GATE_PASS_NO_QC"
                 if report["preregistered_exploratory_accuracy_gate"]
                 else "EXPLORATORY_ORIGINAL_PRESSURE_ACCURACY_GATE_NOT_MET")
        else:
            report["status"]="INCOMPLETE_NATIVE_GERMAN_2023_VALIDATION"
    except Exception as exc:
        report["status"]="ORIGINAL_SOURCE_OR_MODEL_BLOCKED"
        report["reason"]=f"{type(exc).__name__}: {exc}"[:750]
        print("P93B2D_ORIGINAL_SOURCE_OR_MODEL_BLOCKED",report["reason"],flush=True)
    (out/"p9_3b2d_original_DWD_urban_00399_2023_pressure_holdout.json").write_text(
        json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P93B2D_FROZEN_PRESSURE_FINAL",
          json.dumps({"status":report["status"],"n_scored":len(report["cells"]),
                      "full_AT_DE_CH_pressure_qualified":False,
                      "production_epw_ready":False}),flush=True)
    return report


if __name__ == "__main__":
    a=argparse.ArgumentParser()
    a.add_argument("--out",default="outputs/p93b2d-frozen")
    args=a.parse_args()
    synthetic_contracts()
    run(args.out)
