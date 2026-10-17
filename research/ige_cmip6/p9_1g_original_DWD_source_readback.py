#!/usr/bin/env python3
"""P9.1G original DWD German station geo/QC independent ingest qualification."""
from pathlib import Path
import argparse,json
import p9_1g_dwd_original_2019_observations as source

def run(out):
    target=Path(out);target.mkdir(parents=True,exist_ok=True)
    sites,original,meta=source.retrieve_all()
    cases=[]
    for site_id in source.STATION_IDS:
        for name,start,end in source.SEASONS:
            a=original[site_id]
            cases.append({
                "source_station_id":site_id,
                "location_from_original_DWD_metadata":sites[site_id],
                "season":name,
                "original_QN9_histogram":a["original_QC_histograms"][name],
                "original_ZIP_SHA256":a["source_zip_original_SHA256"],
                "real_QC10_hour_count":a["QC_accepted_original_source_hours"][name],
                "source_hourly_DWD_temperatures_unpublished":True,
            })
    res={
        "phase":"P9_1G_ORIGINAL_GERMAN_DWD_INDEPENDENT_SOURCE_ONLY",
        "n_original_frozen_German_source_sites":len(sites),
        "n_frozen_site_seasons":len(cases),
        "n_orig_QC10_hours":sum(x["real_QC10_hour_count"] for x in cases),
        "all_stations_available_with_strict_QC10":
            all(x["real_QC10_hour_count"]>=120 for x in cases),
        "original_DWD_station_archive_metadata":meta,
        "no_foreign_source_data_used_for_training":True,
        "production_epw_ready":False,
        "cases":cases}
    (target/"p9_1g_DWD_original_2019_independent_source_readback.json").write_text(
        json.dumps(res,indent=2,ensure_ascii=False)+"\n")
    print("P9G_DWD_2019_ORIGINAL_READBACK",json.dumps({
        "sites":len(sites),"cases":len(cases),
        "QC10_total_hours":res["n_orig_QC10_hours"],
        "strict_original_source_QC_pass":res["all_stations_available_with_strict_QC10"],
        "production_ready":False}),flush=True)
    if not res["all_stations_available_with_strict_QC10"]:
        raise ValueError("P9G_ORIGINAL_DWD_2019_QC10_SOURCE_INCOMPLETE")
    return res

if __name__=="__main__":
    a=argparse.ArgumentParser();a.add_argument("--out",required=True)
    run(a.parse_args().out)
