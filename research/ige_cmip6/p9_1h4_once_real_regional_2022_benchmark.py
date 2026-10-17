#!/usr/bin/env python3
"""One-shot P9.1H regional original observations + four frozen temperature models.

AT GeoSphere, DE DWD CDC, CH MeteoSwiss OGD SwissMetNet. Jan/Jul 2022 only.
No model fitting. No automatically dropped blocked site×season. Only aggregates
and cryptographic provenance published, never measured hourly temperature rows.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,hashlib,io,json,math,re,statistics,urllib.parse,zipfile
from collections import Counter
from pathlib import Path

import p9_1a_global_historical_backbone as era
import p9_1b_geosphere_original_station_holdouts as geosphere
import p9_1c_provider_altitude_2024_ablation as provider
import p9_1g_dwd_original_2019_observations as dwd
import p9_1f1_terrain_inversion_2019_holdout as terrain
import p9_1e_regular_grid_orography as grid
import p8_1e_swiss_external as swiss
from p9_1h23_source_era5_dem_adapter import predict_one_frozen_regional_hour

ROOT=Path(__file__).parent
MANIFEST=ROOT/"p9_1h_2022_frozen_nine_regional_stations.json"
PERIODS=(("winter","2022-01-10","2022-01-16"),("summer","2022-07-10","2022-07-16"))
SITES={"AT":(39,196,30),"DE":(3987,3730,2290),"CH":("PAY","DAV","JUN")}
METHODS=("B0","B1","B2","H")
MIN_QC=96
NO_PRINT_ORIGINAL_SAMPLES=True

def load_manifest():
    obj=json.loads(MANIFEST.read_text())
    assert obj["phase"]=="P9H4_SINGLE_2022_REGIONAL_SCORING_COHORT"
    assert set(obj["sites"])==set(SITES)
    for country,ids in SITES.items():
        assert tuple(str(int(s["id"])) if country!="CH" else s["id"]
                     for s in obj["sites"][country])==tuple(str(x) for x in ids)
    assert [tuple(x) for x in obj["target_windows"]]==list(PERIODS)
    return obj

def fixed_times(start):
    beginning=dt.datetime.fromisoformat(start+"T00:00")
    return [(beginning+dt.timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(168)]

def observed_AT():
    meta,msha=geosphere.source_json(geosphere.BASE+"/metadata")
    catalog={int(s["id"]):s for s in meta["stations"]}
    sites={sid:{"id":f"AT_{sid}","lat":float(catalog[sid]["lat"]),
                "lon":float(catalog[sid]["lon"]),"altitude_m":float(catalog[sid]["altitude"]),
                "name":str(catalog[sid]["name"]),"country":"AT",
                "native_original_metadata_sha256":msha} for sid in SITES["AT"]}
    o={}
    for name,start,end in PERIODS:
        params=urllib.parse.urlencode({"station_ids":",".join(map(str,SITES["AT"])),
            "parameters":"tl,tl_flag","start":start+"T00:00Z",
            "end":end+"T23:00Z","output_format":"geojson"})
        original,digest=geosphere.source_json(geosphere.BASE+"?"+params)
        values=geosphere.decode_observed(original,set(SITES["AT"]),start,end)
        for sid in SITES["AT"]:
            o[(f"AT_{sid}",name)]={"series":values[sid],
               "quality_tier":"GeoSphere_original_tl_flag_qualified",
               "qc_histogram":{"accepted":len(values[sid])},
               "observed_original_source_SHA256":digest}
    return {site["id"]:site for site in sites.values()},o

def observed_DE():
    listing=dwd.get_original(dwd.ROOT,maximum=1500000)
    station_meta=dwd.get_original(dwd.ROOT+"TU_Stundenwerte_Beschreibung_Stationen.txt",maximum=1200000)
    ids=set(SITES["DE"]); sites={}
    for row in station_meta.decode("latin1").splitlines():
        parts=row.split(maxsplit=6)
        if len(parts)<7 or not parts[0].isdigit():continue
        sid=int(parts[0])
        if sid not in ids:continue
        if not (parts[1]<="20220110" and parts[2]>="20220716"):
            continue
        sites[sid]={"id":f"DE_{sid}","lat":float(parts[4].replace(",",".")),
            "lon":float(parts[5].replace(",",".")),
            "altitude_m":float(parts[3].replace(",",".")),"name":parts[6],
            "country":"DE","native_original_metadata_sha256":hashlib.sha256(station_meta).hexdigest()}
    missing=ids-set(sites)
    if missing:raise ValueError("DE_ORIGINAL_STATION_COVERAGE_MISSING_"+str(sorted(missing)))
    filenames={}
    html=listing.decode("utf8",errors="replace")
    for sid in SITES["DE"]:
        matches=set(re.findall(rf"stundenwerte_TU_{sid:05d}_(\d{{8}})_(\d{{8}})_hist\.zip",html,re.I))
        eligible=[(a,b) for a,b in matches if a<="20220110" and b>="20220716"]
        if len(eligible)!=1:raise ValueError(f"DE_2022_HIST_ZIP_NOT_UNIQUE_{sid}_{eligible}")
        a,b=eligible[0];filenames[sid]=f"stundenwerte_TU_{sid:05d}_{a}_{b}_hist.zip"
    observed={}
    for sid in SITES["DE"]:
        source=dwd.get_original(dwd.ROOT+filenames[sid],maximum=16*1024*1024)
        with zipfile.ZipFile(io.BytesIO(source)) as z:
            bad=z.testzip()
            if bad:raise ValueError("DE_ZIP_CRC_BAD")
            names=[p for p in z.namelist() if Path(p).name.startswith("produkt_tu_stunde_") and p.endswith(".txt")]
            if len(names)!=1:raise ValueError("DE_NO_UNIQUE_PRODUCT")
            if z.getinfo(names[0]).file_size>180*1024*1024:raise ValueError("DE_UNCOMPRESSED_TOO_BIG")
            f=io.TextIOWrapper(z.open(names[0]),encoding="latin1")
            reader=csv.DictReader(f,delimiter=";")
            if not {"STATIONS_ID","MESS_DATUM","QN_9","TT_TU"}.issubset(reader.fieldnames or ()):
                raise ValueError("DE_ORIGINAL_VARIABLE_SCHEMA_DRIFT")
            req={name:{x.replace("-","").replace("T","")[:10] for x in fixed_times(start)}
                 for name,start,end in PERIODS}
            by={name:{} for name,_,_ in PERIODS}
            hist={name:Counter() for name,_,_ in PERIODS}
            seen={name:set() for name,_,_ in PERIODS}
            for row in reader:
                stamp=row["MESS_DATUM"].strip()
                name=next((n for n in req if stamp in req[n]),None)
                if name is None:continue
                if int(row["STATIONS_ID"])!=sid:raise ValueError("DE_STATION_ID_MISMATCH")
                if stamp in seen[name]:raise ValueError("DE_SOURCE_DUPLICATE_UTC_HOUR")
                seen[name].add(stamp)
                qc=int(row["QN_9"]);hist[name][qc]+=1
                # QN9=3 is automatically checked only, QN9=10 fully checked.
                if qc not in (3,10):continue
                temperature=float(row["TT_TU"])
                if temperature<=-999 or not -80<temperature<65:continue
                ts=dt.datetime.strptime(stamp,"%Y%m%d%H").strftime("%Y-%m-%dT%H:%M")
                by[name][ts]=(temperature,qc)
        for name,_,_ in PERIODS:
            qc10={t:v for t,(v,qc) in by[name].items() if qc==10}
            qc3={t:v for t,(v,qc) in by[name].items() if qc==3}
            # Never pretend QN3 is QN10; eligible lower-tier only explicitly tagged.
            chosen=qc10 if len(qc10)>=MIN_QC else qc3 if len(qc3)>=MIN_QC else {}
            tier="DWD_QN9_10_fully_checked" if len(qc10)>=MIN_QC else (
                "DWD_QN9_3_auto_checked_ONLY" if len(qc3)>=MIN_QC else "DWD_INSUFFICIENT")
            observed[(f"DE_{sid}",name)]={"series":chosen,"quality_tier":tier,
                "qc_histogram":dict(hist[name]),
                "observed_original_source_SHA256":hashlib.sha256(source).hexdigest()}
    return {p["id"]:p for p in sites.values()},observed

def original_swiss_station_metadata():
    # Existing P8.1E source contract, fixed authoritative metadata.
    url="https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/ogd-smn_meta_stations.csv"
    raw,digest=swiss.fetch(url,max_bytes=14_000_000)
    stations,cols=swiss.parse_meta(raw)
    if not set(SITES["CH"]).issubset(stations):
        raise ValueError("CH_PREREGISTERED_META_NOT_ALL_PRESENT_"+str(set(SITES["CH"])-set(stations)))
    return {sid:{**stations[sid],"id":f"CH_{sid}","altitude_m":stations[sid]["hoehe_m"],
                 "name":stations[sid]["station"],"country":"CH",
                 "native_original_metadata_sha256":digest} for sid in SITES["CH"]}

def fixed_CH_assets():
    """Use original official documented per-station 2020–2029 archive only.

    MeteoSwiss A1 data: /<abbr>/ogd-smn_<abbr>_h_historical_2020-2029.csv
    No STAC full-catalog crawl, no source outcome-dependent replacement.
    """
    return {sid:[f"https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/{sid.lower()}/"
                 f"ogd-smn_{sid.lower()}_h_historical_2020-2029.csv"]
            for sid in SITES["CH"]}

def swiss_timestamp(stamp):
    """Original MeteoSwiss UTC reference time is end of preceding hourly interval."""
    value=dt.datetime.strptime(stamp.strip(),"%d.%m.%Y %H:%M")
    return value.strftime("%Y-%m-%dT%H:%M")


def observed_CH():
    sites=original_swiss_station_metadata(); files=fixed_CH_assets()
    observed={}
    for sid in SITES["CH"]:
        try:
            candidates=files[sid]
            if len(candidates)!=1:raise ValueError("CH_ORIGINAL_SINGLE_HOURLY_HIST_CSV_UNAVAILABLE")
            raw,sha=swiss.fetch(candidates[0],max_bytes=150*1024*1024)
            rows,cols=swiss.decode_csv(raw)
            stampfield=swiss.pick_col(cols,"reference_timestamp","time","timestamp")
            tempfield=swiss.pick_col(cols,"tre200h0")
            if not stampfield or not tempfield:
                raise ValueError("CH_TRE200H0_OR_TIMESTAMPS_NOT_PROVEN_ORIGINAL_"+str(cols[:25]))
            flagcol=swiss.pick_col(cols,"tre200h0_qc","tre200h0_flag")
            idfield=swiss.pick_col(cols,"station_abbr","station")
            vals={name:{} for name,_,_ in PERIODS}
            native_flags=Counter()
            expected={name:set(fixed_times(start)) for name,start,end in PERIODS}
            for row in rows:
                if idfield and (row.get(idfield) or "").strip().upper()!=sid:
                    raise ValueError("CH_HISTORICAL_CSV_FOREIGN_STATION_CODE")
                try:t=swiss_timestamp(row[stampfield])
                except (ValueError,TypeError):continue
                name=next((a for a in expected if t in expected[a]),None)
                if name is None:continue
                if t in vals[name]:raise ValueError("CH_ORIGINAL_DUPLICATE_HOUR")
                native=(row[tempfield] or "").strip()
                if not native or native in ("-","-9999","NaN"):continue
                value=float(native)
                if not math.isfinite(value) or not -90<value<65:continue
                if flagcol:
                    flag=str(row.get(flagcol,""))
                    native_flags[flag]+=1
                    # Unknown original QC flag meaning: accept only empty flag.
                    if flag not in ("",):continue
                vals[name][t]=value
            for name,_,_ in PERIODS:
                observed[(f"CH_{sid}",name)]={"series":vals[name],
                    "quality_tier":"MeteoSwiss_original_published_OGD_hourly_no_explicit_QC_flag"+
                                   ("_unqualified_flag_semantics" if flagcol else ""),
                    "qc_histogram":{"original_published_rows":len(vals[name]),
                                    "native_flags":dict(native_flags)},
                    "reference_timestamp_UTC_is_end_of_observed_hour":True,
                    "model_ERA5_timestamp_represents_instantaneous_nominal_hour":True,
                    "observed_original_source_SHA256":sha}
            print("REGIONAL_CH_SOURCE",sid,{"2022_winter":len(vals["winter"]),
                    "2022_summer":len(vals["summer"])},flush=True)
        except Exception as e:
            # Fail closed for this preregistered site, but do not erase valid
            # original measured source data at other Swiss stations.
            reason=f"{type(e).__name__}: {e}"[:380]
            for name,_,_ in PERIODS:
                observed[(f"CH_{sid}",name)]={"series":{},
                    "quality_tier":"ORIGINAL_CH_STATION_SOURCE_BLOCKED",
                    "qc_histogram":{"source_blocked_reason":reason},
                    "observed_original_source_SHA256":None}
            print("REGIONAL_CH_SOURCE_BLOCKED",sid,reason,flush=True)
    return {r["id"]:r for r in sites.values()},observed

def site_season_score(obs,times,pred):
    paired=[(obs[t],float(pred[t])) for t in times if t in obs and t in pred and pred[t] is not None]
    if len(paired)<MIN_QC:return None
    es=[p-o for o,p in paired]
    return {"n":len(es),"MAE_C":statistics.fmean(abs(v) for v in es),
            "RMSE_C":math.sqrt(statistics.fmean(v*v for v in es)),
            "bias_C":statistics.fmean(es)}

def model_at(s,winter,summer,terrain_src,arco):
    sid=s["id"]
    result={}
    for name,start,end in PERIODS:
        baseurl=era.request_url(s["lat"],s["lon"],start,end)
        src=era.get_original_source(baseurl)
        raw,features,meta=era.parse_source(src,s["lat"],s["lon"],start,end)
        down=era.get_original_source(provider.altitude_url(baseurl,s["altitude_m"]))
        adjusted,down_fields,dmeta=era.parse_source(down,s["lat"],s["lon"],start,end)
        if raw["hourly"]["time"]!=adjusted["hourly"]["time"]:
            raise ValueError("P9H_NOT_IDENTICAL_BASELINE_TIMES")
        gridz=arco["ARCO_025_original_model_height_m"]
        if abs(meta["selected_cell_latitude"]-arco["original_ARCO_lat"])>1e-4 or abs(
            (meta["selected_cell_longitude"]-arco["original_ARCO_lon"]+180)%360-180)>1e-4:
            raise ValueError("P9H_ORIGINAL_WEATHER_AND_OROGRAPHY_CELLS_MISMATCH")
        weather_series={k:{} for k in METHODS}
        active=0;fallback=Counter()
        for i,t in enumerate(raw["hourly"]["time"]):
            wx={"temperature_2m":features["temperature_2m"][i],
                "wind_speed_10m":features["wind_speed_10m"][i],
                "cloud_cover":features["cloud_cover"][i]}
            if any(x is None for x in wx.values()):
                fallback["NO_ORIGINAL_MODEL_WEATHER_HOUR"]+=1
                continue
            prediction=predict_one_frozen_regional_hour(
                country_code=s["country"],timestamp_utc=t+"Z",
                latitude=s["lat"],longitude=s["lon"],source_weather_era5=wx,
                site_height_m=s["altitude_m"],
                source_arco_grid_cell=arco,
                source_original_srtm=terrain_src,
                provider_altitude_2m_c=down_fields["temperature_2m"][i])
            bb=prediction["three_baselines"]
            for key,v in zip(METHODS,(bb["B0_raw_ERA5_C"],bb["B1_native_grid_fixed_lapse_C"],
                                      bb["B2_provider_altitude_C"],
                                      prediction["physically_bounded_temperature_C"])):
                weather_series[key][t]=v
            if prediction["physical_correction_C"]<0:active+=1
            fallback[prediction["physical_status"]]+=1
        result[name]={"predictions":weather_series,
            "source_original_ERA5_SHA256":meta["raw_original_response_sha256"],
            "source_original_provider_adjusted_SHA256":dmeta["raw_original_response_sha256"],
            "N_candidate_active":active,"candidate_status_histogram":dict(fallback),
            "n_raw_source_hours":len(raw["hourly"]["time"])}
    return result

def benchmark(out):
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    frozen=load_manifest()
    report={"phase":"P9H4_SINGLE_FIXED_2022_THREE_COUNTRY_REAL_SOURCE_BENCHMARK",
        "frozen_manifest_SHA256":hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        "registered_site_ids":{k:list(v) for k,v in SITES.items()},
        "target_windows":PERIODS,"methods":METHODS,
        "providers":{},"members":[],
        "no_2021_holdout_read":True,
        "no_additional_countries":True,
        "no_observed_sensor_rows_exported":True,
        "model_parameters_never_retuned":True,
        "production_epw_ready":False,
        "global_arbitrary_point_weather_qualified":False}
    original_sites={};obs={};country_error={}
    for country,fetch in (("AT",observed_AT),("DE",observed_DE),("CH",observed_CH)):
        try:
            sites,source=fetch()
            expected={f"{country}_{x}" for x in SITES[country]}
            if set(sites)!=expected:raise ValueError("SITE_MANIFEST_MISMATCH")
            original_sites.update(sites);obs.update(source)
            report["providers"][country]={"status":"ORIGINAL_OBSERVATION_READ",
                                          "site_n":len(sites)}
            print("REGIONAL_OBS_SOURCE",country,json.dumps(
                {sid:{"site":s["name"],"altitude_m":s["altitude_m"]} for sid,s in sites.items()}),
                  flush=True)
        except Exception as e:
            country_error[country]=f"{type(e).__name__}: {e}"[:500]
            report["providers"][country]={"status":"ORIGINAL_SOURCE_BLOCKED",
                                          "reason":country_error[country]}
            print("REGIONAL_OBS_BLOCKED",country,country_error[country],flush=True)
    # Never select replacement stations based on outcome.
    sites=list(original_sites.values())
    terrain_by={};arco_by={};spatial_provenance={}
    if sites:
        try:
            source,shas=terrain.independent_dem_rings(sites)
            terrain_by=source;spatial_provenance["DEM_source_shas"]=shas
            print("REGIONAL_ORIGINAL_INDEPENDENT_DEM",len(source),flush=True)
        except Exception as e:
            spatial_provenance["DEM_SOURCE_BLOCKED"]=f"{type(e).__name__}: {e}"[:500]
            print("REGIONAL_DEM_SOURCE_BLOCKED",repr(e),flush=True)
        try:
            centres=grid.collect_grid_centers(sites)
            original=grid.read_real_regular_z(centres)
            arco_by={str(x["source_id"]):x for x in original["points"]}
            spatial_provenance["ARCO_ERA5_original_geopotential_SHA256"]=original[
                "digest_selected_original_grid_lat_lon_z_sha256"]
            print("REGIONAL_ARCO_OROGRAPHY",len(arco_by),flush=True)
        except Exception as e:
            spatial_provenance["ARCO_SOURCE_BLOCKED"]=f"{type(e).__name__}: {e}"[:500]
            print("REGIONAL_ARCO_SOURCE_BLOCKED",repr(e),flush=True)
    report["spatial_provenance"]=spatial_provenance
    model_cache={}
    for country in ("AT","DE","CH"):
        for x in SITES[country]:
            sid=f"{country}_{x}"
            for season,start,end in PERIODS:
                row={"country":country,"sid":sid,"season":season,
                     "N_nominal_hours":168,
                     "status":"NOT_YET_ELIGIBLE_OR_SOURCE_BLOCKED"}
                original=obs.get((sid,season))
                if original:
                    row.update({"n_original_QC_or_published_hours":len(original["series"]),
                        "observation_QC_tier":original["quality_tier"],
                        "original_observation_QC_histogram":original["qc_histogram"],
                        "original_observation_source_SHA256":original["observed_original_source_SHA256"]})
                if sid not in original_sites or original is None:
                    row["reason"]=report["providers"][country].get("reason","NO_REAL_ORIGINAL_SOURCE")
                elif len(original["series"])<MIN_QC:
                    row["reason"]=original.get("qc_histogram",{}).get("source_blocked_reason",
                        "INSUFFICIENT_ORIGINAL_OBS_96H")
                elif sid not in terrain_by or sid not in arco_by:
                    row["reason"]="SRTM_OR_ARCO_OROGRAPHY_UNAVAILABLE"
                else:
                    try:
                        s=original_sites[sid]
                        if sid not in model_cache:
                            model_cache[sid]=model_at(s,None,None,terrain_by[sid],arco_by[sid])
                        model=model_cache[sid][season]
                        scores={method:site_season_score(
                            original["series"],fixed_times(start),model["predictions"][method])
                            for method in METHODS}
                        if any(x is None for x in scores.values()):
                            raise ValueError("INSUFFICIENT_IDENTICAL_MODEL_AND_SOURCE_HOURS")
                        count={x["n"] for x in scores.values()}
                        if len(count)!=1:raise ValueError("DIFFERENT_METHOD_HOURLY_QC_SUPPORT")
                        best=min(scores[b]["MAE_C"] for b in ("B0","B1","B2"))
                        row.update({"status":"ORIGINAL_SOURCE_MODELS_SCORED",
                            "metrics":scores,
                            "candidate_mae_minus_best_baseline_C":scores["H"]["MAE_C"]-best,
                            "candidate_worse_than_best_baseline":scores["H"]["MAE_C"]>best,
                            "N_candidate_active_hours":model["N_candidate_active"],
                            "candidate_status_histogram":model["candidate_status_histogram"],
                            "source_ERA5_SHA256":model["source_original_ERA5_SHA256"],
                            "source_OpenMeteo_adjusted_SHA256":model["source_original_provider_adjusted_SHA256"]})
                        print("REGIONAL_SCORE",sid,season,json.dumps({
                            "n":next(iter(count)),"MAE":{k:round(v["MAE_C"],4) for k,v in scores.items()},
                            "deltaH_vs_best":round(row["candidate_mae_minus_best_baseline_C"],4),
                            "active_hours":model["N_candidate_active"]}),flush=True)
                    except Exception as e:
                        row["status"]="MODEL_OR_SOURCE_COMPARISON_BLOCKED"
                        row["reason"]=f"{type(e).__name__}: {e}"[:500]
                        print("REGIONAL_MODEL_BLOCKED",sid,season,row["reason"],flush=True)
                report["members"].append(row)
    good=[r for r in report["members"] if r["status"]=="ORIGINAL_SOURCE_MODELS_SCORED"]
    report["n_frozen_registered_site_seasons"]=18
    report["summaries_by_country"]={}
    for country in ("AT","DE","CH"):
        eligible=[r for r in good if r["country"]==country]
        rows=[r for r in report["members"] if r["country"]==country]
        report["summaries_by_country"][country]={
            "n_registered_site_seasons":6,
            "n_scored_original_site_seasons":len(eligible),
            "n_blocked_or_unqualified_site_seasons":6-len(eligible),
            "blocked_reasons":[{"station":r["sid"],"season":r["season"],
                                 "status":r["status"],"reason":r.get("reason")}
                for r in rows if r["status"]!="ORIGINAL_SOURCE_MODELS_SCORED"],
            "source_published_natively_quality_flagged":all(
                x.get("observation_QC_tier","").startswith(("GeoSphere_","DWD_QN9_10_"))
                for x in eligible) if eligible else False,
            "mae_macro_unweighted_by_site_season_C":{
                m:statistics.fmean(x["metrics"][m]["MAE_C"] for x in eligible)
                for m in METHODS} if eligible else None,
            "worst_cell_H_delta_from_best_baseline_C":max(
                (x["candidate_mae_minus_best_baseline_C"] for x in eligible),default=None),
            "n_negative_cells_H_worse_than_best":sum(
                x["candidate_worse_than_best_baseline"] for x in eligible)}
    report["n_original_observation_and_four_method_scored_site_seasons"]=len(good)
    report["n_real_obs_matched_hours"]=sum(r["metrics"]["H"]["n"] for r in good)
    report["negative_site_seasons_H_worse_than_best"]=sum(
         r["candidate_worse_than_best_baseline"] for r in good)
    report["regional_three_country_qualified"]=False
    report["research_model_observed_skill_shown_not_epw_production"]=bool(good)
    target=root/"P9H4_original_2022_regional_nine_station_comparison.json"
    target.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print("P9H4_FINAL_COUNTRY_SOURCE_STATUS",json.dumps(report["providers"]),flush=True)
    print("P9H4_TOTAL",json.dumps({"eligible_site_seasons":len(good),
        "paired_hours":report["n_real_obs_matched_hours"],
        "negative_cells":report["negative_site_seasons_H_worse_than_best"]}),flush=True)
    return report

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="outputs/p9h4")
    args=p.parse_args()
    benchmark(args.out)
