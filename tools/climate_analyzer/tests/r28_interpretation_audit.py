"""Exhaustive catalogue qualification runner. Writes one row per registered case.

Run from repository root:
PYTHONPATH=tools/climate_analyzer python tools/climate_analyzer/tests/r28_interpretation_audit.py --output artifacts/r28.csv

Independent explorer construction or actual UI-render capture plus exact text identity earns PARITY_PASS.
The evidence identifies which verification path was used. A bound report alone
is RENDER_ONLY, never proof of cross-surface equality.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd

from test_r28_variable_interpretation_parity import weather, explorer_figure
from r28_specialized_routes import atlas_live, standard_live, UnmatchedRoute
from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer.p66_render import make_figure, NotApplicable
from epw_climate_analyzer.p6_report_structure import CATALOG, available_catalog, standard_figure
from epw_climate_analyzer.profile_interpretation import generic_figure_interpretation
from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation

GENERIC={"profile","percentile","time_series","native","heatmap","duration",
         "histogram","box","violin","diurnal","occurrence","amplitude"}


def fixture():
    base=weather()
    other=base.copy()
    other.index=other.index+pd.DateOffset(years=1)
    df=pd.concat([base,other])
    df.attrs.update(base.attrs)
    i=np.arange(len(df))
    cycle=np.sin(i*2*np.pi/24.)
    hour=df.index.hour.to_numpy()
    sin=np.maximum(0.,np.sin((hour-6)*np.pi/12.))
    values={
        "dry_bulb_temperature_min_c":df[cat.T]-1.,
        "dry_bulb_temperature_max_c":df[cat.T]+1.,
        "ground_temperature_0_10m_c":12+3*cycle,
        "ground_temperature_0_20m_c":12+2*cycle,
        "ground_temperature_0_50m_c":12+cycle,
        "wind_gust_speed_m_s":df[cat.V]+2.,
        "wind_gust_direction_deg":df[cat.WD]+5.,
        "direct_normal_illuminance_lux":40000*sin,
        "diffuse_horizontal_illuminance_lux":8000*sin,
        "opaque_sky_cover_tenths":4+2*cycle,
        "sunshine_duration_s":np.where(sin>0,1800.,0.),
        "precipitation_duration_min":np.where(df[cat.P]>0,20.,0.),
        "solar_apparent_zenith_deg":90-60*np.sin((hour-6)*np.pi/12.),
        "solar_elevation_deg":60*np.sin((hour-6)*np.pi/12.),
        "solar_azimuth_deg":(hour*15.)%360,
        "horizontal_infrared_radiation_intensity_wh_m2":300+20*cycle,
        cat.N:500*sin,cat.D:100*sin,
        cat.G:500*sin*np.sin(np.deg2rad(60*sin))+100*sin,
    }
    for c,v in values.items():df[c]=v
    df.attrs["solar_geometry_site"]={"latitude":47.07,"longitude":15.44,
        "elevation_m":350.,"utc_offset_hours":1.,"reference_year":2026}
    return cat.prepare_frame(df)


def hash_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def record(surface,ident,chapter,kind,args,status,reason="",note="",expected=""):
    actual={"sunpath_view","monthly_radiation","degree","day_indicators","cumulative",
            "freeze_cycles","snow_calendar","correlation","joint","condensation","moisture","illumination"}
    verification="actual UI renderer" if (surface=="Atlas" and (kind in actual or kind=="utci" or kind.startswith("utci_"))) or (
        surface=="Standard report" and (kind in ("sunpath","degree","utci","utci_shading","illumination") or ident=="ghi")) else "independent chart construction"
    if status!="PARITY_PASS" and status!="PARITY_FAIL":verification="not qualified"
    return dict(surface=surface,diagram_id=ident,chapter=chapter,kind=kind,
        args=repr(args),status=status,reason=reason,verification=verification,
        interpretation_sha256=hash_text(note) if note else "",
        explorer_sha256=hash_text(expected) if expected else "",
        interpretation=note,explorer_interpretation=expected)


def audit(df,context):
    rows=cat.catalogue(df,context,cat.FULL)
    for d in rows:
        common=("Atlas",d.id,d.chapter,d.kind,d.args)
        if d.status!="available":
            yield record(*common,"UNSUPPORTED",d.reason)
            continue
        try:
            fig,note=make_figure(d,df,context,reference_df=df)
            if not note.strip():raise ValueError("Empty scientific interpretation")
            validate_figure_interpretation(fig,note,require_binding=True)
            if d.kind in GENERIC and d.kind!="native":
                scope,live,alias=explorer_figure(d,df)
                expected=generic_figure_interpretation(scope,live,alias,
                    domain=d.chapter,column=d.column,args=d.args,latitude=context.get("latitude"))
            else:
                try:
                    live,expected=atlas_live(d,df,context)
                except UnmatchedRoute as exc:
                    yield record(*common,"RENDER_ONLY",str(exc),note)
                    continue
            status="PARITY_PASS" if note==expected else "PARITY_FAIL"
            yield record(*common,status,"" if status=="PARITY_PASS" else "Different text for matched settings",note,expected)
        except NotApplicable as exc:
            yield record(*common,"NOT_APPLICABLE",str(exc))
        except Exception as exc:
            yield record(*common,"ERROR",f"{type(exc).__name__}: {exc}")
    available={e[0] for e in available_catalog(df,context)}
    for e in CATALOG:
        ident,chapter,label,column,unit,kind=e
        common=("Standard report",ident,chapter,kind,())
        if ident not in available:
            yield record(*common,"UNSUPPORTED","Source admission rejected")
            continue
        try:
            fig,note=standard_figure(e,df,context,reference_df=df)
            if not note.strip():raise ValueError("Empty scientific interpretation")
            validate_figure_interpretation(fig,note,require_binding=True)
            if kind in ("duration","heatmap","profile"):
                from epw_climate_analyzer import charts as ch
                if kind=="duration":
                    args=("all",False,"hours")
                    live=ch.duration_chart(df,column,"Website",unit,ascending=False)
                    alias="Duration curve"
                elif kind=="heatmap":
                    args=("month","Hour of day","Mean")
                    live=ch.temporal_heatmap_chart(df,column,*args,"Website",unit)
                    alias="Heat map"
                else:
                    args=("Monthly",)
                    live=ch.time_series_profile_chart(df,column,"Monthly",
                        "Website · Monthly · Min–mean–max",unit,"Min–mean–max")
                    alias="Time series / Profile"
                expected=generic_figure_interpretation(df,live,alias,domain=chapter,
                    column=column,args=args,latitude=context.get("latitude"))
                status="PARITY_PASS" if note==expected else "PARITY_FAIL"
                yield record(*common,status,"" if status=="PARITY_PASS" else "Different text for matched settings",note,expected)
            else:
                try:
                    live,expected=standard_live(e,df,context)
                except UnmatchedRoute as exc:
                    yield record(*common,"RENDER_ONLY",str(exc),note)
                    continue
                status="PARITY_PASS" if note==expected else "PARITY_FAIL"
                yield record(*common,status,"" if status=="PARITY_PASS" else "Different text for matched settings",note,expected)
        except Exception as exc:
            yield record(*common,"ERROR",f"{type(exc).__name__}: {exc}")


def additional_scopes():
    """Short targeted matrices for source conditions absent from the main fixture."""
    from epw_climate_analyzer import charts as ch, extended_visualization as ex
    from epw_climate_analyzer.p6_report_structure import standard_figure, available_catalog
    context={"latitude":47.07}
    # One genuinely complete calendar month, rather than filling a partial month.
    idx=pd.date_range("2026-02-01","2026-03-01",freq="h",inclusive="left")
    full=pd.DataFrame({cat.T:10.+5.*np.sin(np.arange(len(idx))*2*np.pi/24),
                       cat.P:np.where(np.arange(len(idx))%24==0,1.,0.)},index=idx)
    full.attrs["canonical_native_interval_minutes"]=60.
    table=ex.climate_summary_table(full)
    for d in cat.catalogue(full,context,cat.REP):
        if d.kind!="climate_summary":continue
        common=("Atlas complete month",d.id,d.chapter,d.kind,d.args)
        try:
            fig,note=make_figure(d,full,context)
            validate_figure_interpretation(fig,note,require_binding=True)
            live,expected=atlas_live(d,full,context)
            status="PARITY_PASS" if note==expected else "PARITY_FAIL"
            yield record(*common,status,"",note,expected)
        except Exception as exc:
            yield record(*common,"ERROR",f"{type(exc).__name__}: {exc}")
    entry=next(e for e in CATALOG if e[0]=="climograph")
    common=("Standard report complete month",entry[0],entry[1],entry[-1],())
    try:
        assert entry in available_catalog(full,context)
        assert not table.empty
        fig,note=standard_figure(entry,full,context)
        validate_figure_interpretation(fig,note,require_binding=True)
        live,expected=standard_live(entry,full,context)
        yield record(*common,"PARITY_PASS" if note==expected else "PARITY_FAIL","",note,expected)
    except Exception as exc:
        yield record(*common,"ERROR",f"{type(exc).__name__}: {exc}")

    idx=pd.date_range("2026-01-01",periods=12,freq="MS")
    months=np.arange(12)
    monthly=pd.DataFrame({cat.T:10.+months,cat.DEW:2.+months,cat.RH:50.+months,
        cat.W:5.+months/10,cat.V:2.+months/10,cat.WD:180.+months,
        cat.P:20.+months,cat.G:50000.+1000.*months,
        "total_sky_cover_tenths":4.+months/10},index=idx)
    monthly.attrs["canonical_native_resolution"]="monthly"
    for d in cat.catalogue(monthly,context,cat.REP):
        if d.kind!="native" or d.status!="available":continue
        common=("Atlas native monthly",d.id,d.chapter,d.kind,d.args)
        try:
            fig,note=make_figure(d,monthly,context)
            validate_figure_interpretation(fig,note,require_binding=True)
            live=ch.time_series_profile_chart(monthly,d.column,"Native",
                    "Website · Native · Observed values",d.unit,"Observed values")
            expected=generic_figure_interpretation(monthly,live,"Time series / Profile",
                        domain=d.chapter,column=d.column)
            assert "native monthly" in note.lower()
            assert "observed hours" not in note.lower()
            yield record(*common,"PARITY_PASS" if note==expected else "PARITY_FAIL","",note,expected)
        except Exception as exc:
            yield record(*common,"ERROR",f"{type(exc).__name__}: {exc}")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="artifacts/r28_interpretation_audit.csv")
    parser.add_argument("--require-complete",action="store_true")
    args=parser.parse_args()
    path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    counts=Counter();by_kind=Counter();verification_counts=Counter()
    with path.open("w",newline="",encoding="utf-8-sig") as out:
        writer=None
        from itertools import chain
        for row in chain(audit(fixture(),{"latitude":47.07}),additional_scopes()):
            if writer is None:
                writer=csv.DictWriter(out,fieldnames=list(row))
                writer.writeheader()
            writer.writerow(row);counts[row["status"]]+=1
            by_kind[(row["status"],row["kind"])]+=1
            if row["status"]=="PARITY_PASS":verification_counts[row["verification"]]+=1
            if row["status"] in ("PARITY_FAIL","ERROR"):
                print(row["status"],row["diagram_id"],row["reason"],flush=True)
    print(dict(counts),flush=True)
    print('Verification paths:',dict(verification_counts),flush=True)
    for (status,kind),count in sorted(by_kind.items()):
        if status!='PARITY_PASS':print(f'{status} {kind}: {count}',flush=True)
    # Completeness is distinct from successful rendering.
    return int(bool(counts["PARITY_FAIL"] or counts["ERROR"] or
                    (args.require_complete and counts["RENDER_ONLY"])))


if __name__=="__main__":
    raise SystemExit(main())
