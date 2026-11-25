"""Full Atlas/standard report palette evidence on existing R2.8 fixtures."""
from __future__ import annotations
import argparse,csv,json
from collections import Counter
from pathlib import Path
import pandas as pd
from r28_interpretation_audit import fixture,GENERIC
from test_r28_variable_interpretation_parity import explorer_figure
from r28_specialized_routes import atlas_live,standard_live
from epw_climate_analyzer import p66_catalogue as cat, charts as ch
from epw_climate_analyzer.p66_render import make_figure,NotApplicable
from epw_climate_analyzer.p6_report_structure import available_catalog,standard_figure,report_figure
from epw_climate_analyzer.palette_audit import inspect_palette

def compare(fig,live):
    a=inspect_palette(fig)
    b=inspect_palette(live) if live is not None else None
    printed=inspect_palette(report_figure(fig,width_pt=500,height_pt=310))
    return dict(implicit_channels="; ".join(a["implicit_channels"]),
                explorer_implicit="; ".join(b["implicit_channels"]) if b else "",
                atlas_signature=a["signature"],explorer_signature=b["signature"] if b else "",
                report_signature=printed["signature"],
                palette_status="REVIEW_IMPLICIT" if a["implicit_channels"] or (b and b["implicit_channels"]) else
                    "REVIEW_PRINT" if a["signature"]!=printed["signature"] else
                    "RENDER_ONLY" if b is None else "MATCH" if a["signature"]==b["signature"] else "REVIEW_DIFFERENCE")

def cases(df,context,scope):
    for d in cat.catalogue(df,context,cat.FULL):
        row=dict(scope=scope,surface="Atlas",id=d.id,kind=d.kind)
        if d.status!="available":yield dict(row,palette_status="UNSUPPORTED",reason=d.reason);continue
        try:
            fig,_=make_figure(d,df,context,reference_df=df)
            live=None;reason=""
            try:
                if d.kind=="native":live=ch.time_series_profile_chart(df,d.column,"Native","Website",d.unit,"Observed values")
                elif d.kind in GENERIC:_,live,_=explorer_figure(d,df)
                else:live,_=atlas_live(d,df,context)
            except Exception as exc:reason=f"Explorer: {type(exc).__name__}: {exc}"
            yield dict(row,reason=reason,**compare(fig,live))
        except NotApplicable as exc:yield dict(row,palette_status="NOT_APPLICABLE",reason=str(exc))
        except Exception as exc:yield dict(row,palette_status="ERROR",reason=f"{type(exc).__name__}: {exc}")
    for entry in available_catalog(df,context):
        ident,chapter,label,column,unit,kind=entry
        row=dict(scope=scope,surface="Standard",id=ident,kind=kind)
        try:
            fig,_=standard_figure(entry,df,context,reference_df=df)
            live=None;reason=""
            try:
                if kind=="duration":live=ch.duration_chart(df,column,"Website",unit,ascending=False)
                elif kind=="heatmap":live=ch.temporal_heatmap_chart(df,column,"month","Hour of day","Mean","Website",unit)
                elif kind=="profile":
                    monthly=str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly"
                    live=ch.time_series_profile_chart(df,column,"Native" if monthly else "Monthly","Website",unit,"Observed values" if monthly else "Min–mean–max")
                else:live,_=standard_live(entry,df,context)
            except Exception as exc:reason=f"Explorer: {type(exc).__name__}: {exc}"
            yield dict(row,reason=reason,**compare(fig,live))
        except Exception as exc:yield dict(row,palette_status="ERROR",reason=f"{type(exc).__name__}: {exc}")

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",default="artifacts/r218_palette_audit.csv")
    parser.add_argument("--require-complete",action="store_true")
    args=parser.parse_args();path=Path(args.output);path.parent.mkdir(parents=True,exist_ok=True)
    counts=Counter()
    fields=["scope","surface","id","kind","palette_status","reason","implicit_channels","explorer_implicit","atlas_signature","explorer_signature","report_signature"]
    df=fixture()
    monthly=df.resample("MS").mean(numeric_only=True)
    monthly.attrs.update(df.attrs);monthly.attrs["canonical_native_resolution"]="monthly"
    with path.open("w",newline="",encoding="utf-8-sig") as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for frame,scope in ((df,"Subdaily"),(monthly,"Native monthly")):
            for row in cases(frame,{"latitude":47.07},scope):
                writer.writerow(row);counts[row["palette_status"]]+=1
                if row["palette_status"]=="ERROR":print(row["id"],row["reason"],flush=True)
    print(json.dumps(dict(counts),indent=2),flush=True)
    return int(bool(counts["ERROR"] or (args.require_complete and any(counts[x] for x in ("REVIEW_IMPLICIT","REVIEW_PRINT","REVIEW_DIFFERENCE","RENDER_ONLY")))))

if __name__=="__main__":raise SystemExit(main())
