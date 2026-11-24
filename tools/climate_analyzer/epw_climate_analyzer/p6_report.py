"""Session-local report snapshots and self-contained print/PDF output."""
from __future__ import annotations
import hashlib
from copy import deepcopy
import html
import io
import json
import re
from datetime import datetime,timezone
from .chart_lifecycle import register_figure,begin_page
RUNTIME_REPORT_SCHEMA="MEM-PERF-R7"
import plotly.io as pio
import plotly.graph_objects as go
import streamlit as st

REPORT_KEY="_p6_report_items"
CONTEXT_KEY="_p6_report_context"
INTERPRETATION_KEY="_p6_report_interpretation"
MAX_BYTES=65*1024*1024

def set_context(state,*,page,source,location,df=None,extra=None,site=None,source_id=None):
    meta={"page":str(page),"source":str(source),"location":str(location)}
    if df is not None and len(df):
        spec=state.get("_active_global_filter_spec",{})
        meta.update({"first timestamp":str(df.index.min()),"last timestamp":str(df.index.max()),
                     "selected records":len(df),"native interval minutes":str(df.attrs.get("canonical_native_interval_minutes","not declared")),
                     "time basis":str(df.attrs.get("climate_time_basis","Chronological")),
                     "filter":json.dumps(spec,default=str,ensure_ascii=False,sort_keys=True)})
    if extra:meta.update({str(k):str(v) for k,v in extra.items()})
    if site is not None:
        for name in ("latitude","longitude","elevation_m","station_id"):
            value=getattr(site,name,None)
            if value is not None:meta[name]=str(value)
    if source_id is not None:meta["source id"]=str(source_id)
    meta["temperature thresholds"]=list(state.get("_p6_temperature_thresholds",(18.,26.)))
    if df is not None and len(df):
        from .p6_report_structure import capture_statistics
        from .aggregations import native_interval_hours
        meta["statistics"]=capture_statistics(df,page)
        from .report_synthesis import cross_chapter_synthesis
        meta["cross-chapter synthesis"]=cross_chapter_synthesis(df)
        if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly":
            meta["native interval minutes"]="monthly"
        else:meta["native interval minutes"]=str(df.attrs.get("canonical_native_interval_minutes",native_interval_hours(df)*60))
    state[CONTEXT_KEY]=meta

def snapshot(fig,context,interpretation=""):
    from .figure_interpretation_contract import bind_figure_interpretation
    bind_figure_interpretation(fig,interpretation)
    title=str(fig.layout.title.text or "Untitled diagram")
    payload=pio.to_json(fig,validate=True,remove_uids=True)
    meta=deepcopy(context)
    return {"id":hashlib.sha256((payload+json.dumps(meta,sort_keys=True,default=str)+str(interpretation)).encode()).hexdigest(),
            "title":title,"figure":payload,"context":meta,"interpretation":str(interpretation or ""),
            "captured":datetime.now(timezone.utc).isoformat(),"note":""}
def add_snapshot(items,item):
    if any(x["id"]==item["id"] for x in items):return items,"This exact diagram is already in the report."
    if sum(len(x["figure"].encode()) for x in items)+len(item["figure"].encode())>MAX_BYTES:
        raise ValueError("Report figure-data budget reached (65 MiB). Remove entries or use the Diagram Atlas for larger exports.")
    return [*items,item],"Diagram added to report."
CAPTURE_MESSAGE_KEY="_p6_report_capture_message"

def _capture_settings(state):
    """Only explicit calculation controls, not arbitrary session content."""
    exact={"humidity_analysis_type","wind_analysis_type","solar_facade_tilt","solar_facade_chart_type",
           "p6_overview_view","p6_dashboard_year","global_time_basis"}
    prefixes=("p3_","p4_","p6_nv_","p6_night_","p6_hgt_","p6_kgt_","p6_utci","p6_flow",
              "solar_facade_","nv_directional_","canonical_compare_","shading_")
    controls={}
    for name,value in state.items():
        if not isinstance(name,str) or not (name in exact or name.startswith(prefixes)):continue
        scalar=(str,int,float,bool,type(None))
        if isinstance(value,scalar) or isinstance(value,(list,tuple)) and all(isinstance(v,scalar) for v in value):
            controls[name]=value
    return json.dumps(controls,default=str,ensure_ascii=False,sort_keys=True)

def save_displayed_chart(state,fig,context,interpretation,button_key):
    """Click callback: persists prior rendered figure before the script reruns."""
    try:
        item=snapshot(fig,context,interpretation)
        entries,message=add_snapshot(state.get(REPORT_KEY,[]),item)
        state[REPORT_KEY]=entries
        # Test-only hashes; no extra figure serialization in normal production.
        import os
        if os.environ.get("IGE_R143_PARITY")=="1":
            from .r143_scientific_parity import record_capture
            record_capture(state,fig,context,interpretation,button_key,entries,item["id"])
        state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":True,
                                    "message":f"{message} {len(entries)} chart(s) in report."}
    except Exception as exc:
        state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":False,"message":f"Chart not saved: {exc}"}

def save_chart_by_token(button_key,token):
    """Resolve the exact prior rendered chart in the current session."""
    state=st.session_state
    if token!=state.get("_p6_page_token"):
        state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":False,"message":"Chart page changed before capture. Render it again before saving."}
        return
    for fig,context,interpretation,key in state.get("_p6_displayed_charts",[]):
        if key==button_key:
            save_displayed_chart(state,fig,context,interpretation,key)
            return
    state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":False,
                                "message":"Chart is no longer displayed. Render it again before saving."}

def save_current_page(token):
    state=st.session_state
    if token==state.get("_p6_page_token"):save_all_displayed(state)

def capture_control(st,fig,key):
    context=st.session_state.get(CONTEXT_KEY)
    if not isinstance(context,dict) or context.get("page")=="Report":return
    if context.get("page")=="Compare Climates" and "compared sources" not in context:return
    # The caller passes a deterministic per-render ordinal, not the app's
    # incrementing Plotly widget key. Callback arguments belong to the chart
    # actually displayed when the user clicks, before any rerun changes inputs.
    button_key="p6_capture_"+str(context.get("page"))+"_"+str(key)
    saved_context={**context,"keyed chart settings":_capture_settings(st.session_state),
                   "temperature thresholds":list(st.session_state.get("_p6_temperature_thresholds",(18.,26.)))}
    interpretation=st.session_state.get(INTERPRETATION_KEY,"")
    state=st.session_state
    token=state.get("_p6_page_token")
    if token is None:token=begin_page(state)
    register_figure(state,fig,saved_context,interpretation,button_key)
    st.button("Add to report",key=button_key,
              on_click=save_chart_by_token,
              args=(button_key,token),
              help="Save this displayed figure after global presentation settings are applied.")
    notice=st.session_state.get(CAPTURE_MESSAGE_KEY,{})
    if notice.get("key")==button_key:
        if notice.get("ok"):st.success(notice["message"])
        else:st.warning(notice["message"])
    st.caption(f"Report: {len(st.session_state.get(REPORT_KEY,[]))} saved diagram(s).")

def save_all_displayed(state):
    previous=state.get(REPORT_KEY,[])
    try:
        items=previous
        for fig,context,interpretation,_ in state.get("_p6_displayed_charts",[]):
            items,_=add_snapshot(items,snapshot(fig,context,interpretation))
        state[REPORT_KEY]=items
        state["_p6_bulk_notice"]=f"{len(items)-len(previous)} new diagrams added. {len(items)} saved."
    except Exception as exc:
        state["_p6_bulk_notice"]=f"Bulk capture not saved: {exc}"

def render_report_status(st):
    """Visible basket count and capture of the prior displayed page."""
    state=st.session_state
    st.sidebar.caption(f"Report: {len(state.get(REPORT_KEY,[]))} saved diagram(s)")
    from .ui_contract import NAVIGATION_KEY
    token=begin_page(state)
    if state.get(NAVIGATION_KEY) not in ("Report","Climate File Source"):
        st.sidebar.button("Add all displayed diagrams",key="p6_capture_all",
                          on_click=save_current_page,args=(token,),
                          help="Capture every Plotly diagram on the current analysis page.")
        if state.get("_p6_bulk_notice"):st.sidebar.caption(state.pop("_p6_bulk_notice"))


def _safe(value):
    return html.escape(str(value or ""),quote=True)
def _script_json(value):
    return json.dumps(value,ensure_ascii=True).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
def printable_html(items,title,paper,orientation,*,use_osm=False):
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    from plotly.offline import get_plotlyjs
    from .p6_report_structure import contexts,ordered_groups,concise_context,site_details,locator_figure,report_figure,zone_legend_entries,figure_height,complex_figure
    from .report_synthesis import synthesis_rows,synthesis_interpretation
    from reportlab.lib.pagesizes import A4,A3,landscape
    page=A4 if paper=="A4" else A3
    if orientation=="Landscape":page=landscape(page)
    width=page[0]-64
    height=page[1]-64
    seq=0
    def plot(fig,h):
        nonlocal seq
        seq+=1
        zones=zone_legend_entries(fig)
        f=report_figure(fig,width_pt=width,height_pt=h,external_zone_legend=bool(zones))
        raw=json.loads(pio.to_json(f))
        key=""
        if zones:
            key='<div class="zone-key"><b>Bioclimatic zones</b><div class="zone-grid">'+ "".join('<div><span class="zone-swatch" style="background:'+_safe(colour)+'"></span>'+_safe(name)+'</div>' for _,name,colour in zones)+'</div></div>'
        return f'<div class="plot" id="figure{seq}"></div><script>const f{seq}={_script_json(raw)};Plotly.newPlot("figure{seq}",f{seq}.data,f{seq}.layout,{{responsive:false,displayModeBar:false}});</script>'+key
    def table(rows):
        if not rows:return "<p>Statistics unavailable for this saved scope.</p>"
        return "<table><thead><tr><th>Indicator</th><th>Selected-period statistics</th><th>Valid records</th></tr></thead><tbody>"+"".join("<tr>"+"".join("<td>"+_safe(cell)+"</td>" for cell in row)+"</tr>" for row in rows)+"</tbody></table>"
    groups=ordered_groups(items)
    pages=[]
    for idx,context in enumerate(contexts(items)):
        section="<h1>"+_safe(title)+"</h1><h2>Climate and station overview</h2>" if idx==0 else '<section class="sheet"><h2>Additional climate / analysis period</h2>'
        section+="<p>"+_safe(concise_context(context))+"</p>"
        from .p6_osm_map import export_locator
        loc,attribution=export_locator(context,use_osm=use_osm)
        if loc is not None:section+=plot(loc,min(height*.40,240))+"<p>"+_safe(attribution)+"</p>"
        if site_details(context):section+="<p>"+_safe(" · ".join(f"{a}: {v}" for a,v,_ in site_details(context)))+"</p>"
        section+=table(context.get("statistics",{}).get("overview",[]))
        if synthesis_rows(context):
            section+="<h3>Cross-chapter climatic findings</h3>"
            section+=table(synthesis_rows(context))
            if synthesis_interpretation(context):
                section+="<p>"+_safe(synthesis_interpretation(context))+"</p>"
        if idx==0:section+="<p><b>Report chapters:</b> "+_safe(" · ".join(name for name,_ in groups))+"</p>"
        if idx>0:section+="</section>"
        pages.append(section)
    for chapter_no,(chapter,entries) in enumerate(groups,1):
        pages.append(f'<section class="sheet"><h2>{chapter_no:02d} · {_safe(chapter)}</h2>')
        for c in contexts(entries):
            pages.append("<p>"+_safe(concise_context(c))+"</p>"+table(c.get("statistics",{}).get("chapter",[])))
        pages.append("</section>")
        for k,item in enumerate(entries,1):
            fig=pio.from_json(item["figure"])
            from .figure_interpretation_contract import validate_figure_interpretation
            validate_figure_interpretation(fig,item["interpretation"])
            from .calendar_heatmap_axes import set_period_axis_scope
            set_period_axis_scope(fig,context=item.get("context"))
            scope_line="<p>"+_safe(concise_context(item["context"]))+"</p>" if len(contexts(entries))>1 else ""
            zones=zone_legend_entries(fig)
            h=figure_height(fig,width,height)
            if zones:h=min(h,height*.60)
            pages.append(f'<section class="sheet"><h3>{chapter_no}.{k} · {_safe(item["title"])}</h3>'+scope_line+plot(fig,h)+"<p>"+_safe(item["interpretation"])+"</p><p>"+_safe(item.get("note",""))+"</p></section>")
    css=f"""@page {{size:{paper} {orientation.lower()};margin:11.3mm}} *{{box-sizing:border-box}} body{{font:11pt Arial,sans-serif;color:#202830;margin:12px;width:{width}pt}} h1{{font-size:23pt;margin:0 0 9pt}} h2{{font-size:17pt;margin:0 0 8pt}} h3{{font-size:13pt;margin:0 0 6pt}} p{{white-space:pre-wrap;overflow-wrap:anywhere;margin:5pt 0;line-height:1.25}} table{{width:100%;border-collapse:collapse;font:inherit;margin:5pt 0}} td,th{{padding:4pt 5pt;text-align:left;border-bottom:1px solid #D7DDE1}} th{{color:#314652;background:#EEF2F4}} .sheet{{break-before:page;page-break-before:always}} .plot{{width:100%;break-inside:avoid}} .zone-key{{break-inside:avoid;margin:4pt 0}} .zone-grid{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:3pt 10pt}} .zone-swatch{{display:inline-block;width:12pt;height:7pt;border:1px dashed #39447d;margin-right:5pt}} button{{padding:8px 16px}} @media print{{button{{display:none}} body{{margin:0}}}}"""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>"+_safe(title)+"</title><style>"+css+"</style><script>"+get_plotlyjs()+"</script></head><body><button onclick='window.print()'>Print / Save as PDF</button>"+"".join(pages)+"</body></html>").encode("utf-8")

def pdf_report(items,title,paper,orientation,*,image_renderer=None,use_osm=False,progress=None,render_cache_dir=None):
    """Disk-staged static report export with one shared export owner."""
    from .p66_memory import EXPORT_LOCK,require_headroom
    import gc
    import tempfile
    if not EXPORT_LOCK.acquire(blocking=False):raise RuntimeError("Another PDF or Atlas export is already running.")
    try:
        require_headroom()
        from .p6_static_render import render_session
        with render_session(cache_dir=render_cache_dir), tempfile.TemporaryDirectory(prefix="ige-report-") as staging:
            return _pdf_report(items,title,paper,orientation,image_renderer=image_renderer,use_osm=use_osm,staging=staging,progress=progress)
    finally:
        gc.collect()
        EXPORT_LOCK.release()

def _pdf_report(items,title,paper,orientation,*,image_renderer=None,use_osm=False,staging,progress=None):
    """Professional chapter-organized PDF; no raw widget/diagnostic dumps."""
    from reportlab.lib.pagesizes import A4,A3,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image,Table,TableStyle
    from PIL import Image as PILImage
    from pathlib import Path
    from .p6_static_render import render_png,export_headroom
    import gc
    from .p6_report_structure import contexts,ordered_groups,concise_context,site_details,locator_figure,report_figure,zone_legend_entries,figure_height,complex_figure
    from .report_synthesis import synthesis_rows,synthesis_interpretation
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    if not items:raise ValueError("Add at least one chart.")
    page=A4 if paper=="A4" else A3
    if orientation=="Landscape":page=landscape(page)
    out=Path(staging)/"report.pdf"
    doc=SimpleDocTemplate(str(out),pagesize=page,rightMargin=32,leftMargin=32,topMargin=30,bottomMargin=34,title=title,author="IGE Climate Analyzer")
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ReportBody",fontName="Helvetica",fontSize=11,leading=13.5,spaceAfter=6,splitLongWords=True))
    styles.add(ParagraphStyle(name="ReportTitle",fontName="Helvetica-Bold",fontSize=23,leading=26,spaceAfter=9))
    styles.add(ParagraphStyle(name="ReportChapter",fontName="Helvetica-Bold",fontSize=17,leading=20,spaceAfter=8))
    styles.add(ParagraphStyle(name="ReportFigure",fontName="Helvetica-Bold",fontSize=13,leading=16,spaceAfter=6))
    def para(value,style="ReportBody"):
        return Paragraph(_safe(value).replace("\n","<br/>"),styles[style])
    width=doc.width-12
    def stats_table(rows):
        if not rows:return para("Statistics unavailable for this saved scope.")
        data=[[para("Indicator"),para("Selected-period statistics"),para("Valid records")]]+[[para(v) for v in row] for row in rows]
        t=Table(data,colWidths=[width*.28,width*.52,width*.20],repeatRows=1,hAlign="LEFT")
        t.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#EEF2F4")),("VALIGN",(0,0),(-1,-1),"TOP"),
                                ("LINEBELOW",(0,0),(-1,-1),.4,colors.HexColor("#D7DDE1")),("TOPPADDING",(0,0),(-1,-1),3),("BOTTOMPADDING",(0,0),(-1,-1),3)]))
        return t
    image_number=0
    def image(fig,h,label):
        nonlocal image_number
        image_number+=1
        if progress:progress(image_number,label)
        target=Path(staging)/f"figure-{image_number:06d}.png"
        try:
            export_headroom(f"prepare chart {image_number}: {label}")
            f=report_figure(fig,width_pt=width,height_pt=h,external_zone_legend=bool(zone_legend_entries(fig)))
            if image_renderer is not None:target.write_bytes(image_renderer(f))
            else:render_png(f,target,scale=1.5)
            del f
            with PILImage.open(target) as im:w,ih=im.size
            gc.collect()
            export_headroom(f"after chart {image_number}: {label}")
            scale=min(width/w,h/ih)
            return Image(str(target),width=w*scale,height=ih*scale,hAlign="CENTER",lazy=2)
        except MemoryError as exc:raise MemoryError(f"{exc} Chart {image_number}: {label}.") from exc
        except Exception as exc:raise RuntimeError(f"Static rendering failed for {label}. Use the printable HTML export. ({exc})") from exc
    def zone_table(zones):
        # Native text stays 11 pt, retains every visible named zone and is
        # never placed in the Plotly scrollable legend viewport.
        from reportlab.lib.colors import Color,HexColor
        import re
        def swatch(value):
            if value.startswith("rgba("):
                vals=[float(v) for v in re.findall(r"[0-9.]+",value)]
                if len(vals)==4:
                    r,g,b,a=vals
                    return Color(1-a+a*r/255,1-a+a*g/255,1-a+a*b/255)
            try:return HexColor(value)
            except ValueError:return HexColor("#F1F5F9")
        rows=[];commands=[("VALIGN",(0,0),(-1,-1),"TOP"),("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1)]
        for i in range(0,len(zones),2):
            row=[]
            for j in range(2):
                if i+j<len(zones):
                    _,name,colour=zones[i+j]
                    row.extend(["",para(name.replace("<br>"," ").replace("<br/>"," "))])
                    commands.append(("BACKGROUND",(2*j,i//2),(2*j,i//2),swatch(colour)))
                    commands.append(("BOX",(2*j,i//2),(2*j,i//2),.45,HexColor("#39447D")))
                else:row.extend(["",""])
            rows.append(row)
        table=Table(rows,colWidths=[10,width/2-10,10,width/2-10],hAlign="LEFT")
        table.setStyle(TableStyle(commands))
        return table
    groups=ordered_groups(items);body=[]
    for idx,context in enumerate(contexts(items)):
        if idx:body.append(PageBreak())
        if not idx:body.append(para(title,"ReportTitle"))
        body.extend([para("Climate and station overview" if idx==0 else "Additional climate / analysis period","ReportChapter"),
                     para(concise_context(context))])
        from .p6_osm_map import export_locator
        loc,attribution=export_locator(context,use_osm=use_osm)
        if loc is not None:
            body.extend([image(loc,min(doc.height*.37,220),"station location"),para(attribution)])
        site=site_details(context)
        # Compact location row rather than another table.
        if site:body.append(para(" · ".join(f"{a}: {v}" for a,v,_ in site)))
        body.extend([stats_table(context.get("statistics",{}).get("overview",[])),Spacer(1,7)])
        if synthesis_rows(context):
            body.extend([para("Cross-chapter climatic findings","ReportFigure"),
                         stats_table(synthesis_rows(context)),Spacer(1,7)])
            if synthesis_interpretation(context):
                body.append(para(synthesis_interpretation(context)))
        if not idx:body.append(para("Report chapters: "+" · ".join(n for n,_ in groups)))
    for chapter_no,(chapter,entries) in enumerate(groups,1):
        body.extend([PageBreak(),para(f"{chapter_no:02d} · {chapter}","ReportChapter")])
        for c in contexts(entries):
            body.extend([para(concise_context(c)),stats_table(c.get("statistics",{}).get("chapter",[])),Spacer(1,7)])
        for k,item in enumerate(entries,1):
            heading=f"{chapter_no}.{k} · {item['title']}"
            before=[para(heading,"ReportFigure")]
            if len(contexts(entries))>1:before.append(para(concise_context(item["context"])))
            export_headroom(f"load saved chart {chapter_no}.{k}: {item['title']}")
            fig=pio.from_json(item["figure"])
            from .calendar_heatmap_axes import set_period_axis_scope
            set_period_axis_scope(fig,context=item.get("context"))
            zones=zone_legend_entries(fig)
            legend=[para("Bioclimatic zones"),zone_table(zones),Spacer(1,6)] if zones else []
            explanation=[]
            from .figure_interpretation_contract import validate_figure_interpretation
            validate_figure_interpretation(fig,item["interpretation"])
            if item["interpretation"]:explanation.extend([para("Interpretation","ReportFigure"),para(item["interpretation"])])
            if item.get("note"):explanation.append(para(item["note"]))
            # SimpleDocTemplate's default frame has 6 pt padding on each
            # side. Reserve all wrapped text, external legends and spacing
            # before selecting the physical chart render size. Summing both
            # adjacent spaces is intentionally conservative.
            available=doc.height-12
            def occupied(flowables):
                return sum(f.wrap(width,available)[1]+f.getSpaceBefore()+f.getSpaceAfter()
                           for f in flowables)
            overhead=occupied(before+legend)+5+2
            preferred=figure_height(fig,width,doc.height)
            room=available-overhead
            # If the full note would make the chart too small, keep the
            # complete explanation on a deliberately titled continuation.
            min_chart=min(155.,preferred)
            continued=bool(explanation) and room-occupied(explanation)<min_chart
            h=min(preferred,room if continued else room-occupied(explanation))
            if h<80:raise ValueError(f"Too little printable chart area for {item['title']}. Choose A3.")
            body.extend([PageBreak(),*before,image(fig,h,item["title"]),Spacer(1,5),*legend])
            del fig
            if continued:
                body.extend([PageBreak(),para(heading+" — Interpretation","ReportFigure")])
                from .figure_interpretation_contract import validate_figure_interpretation
            validate_figure_interpretation(fig,item["interpretation"])
            if item["interpretation"]:body.append(para(item["interpretation"]))
                if item.get("note"):body.append(para(item["note"]))
            else:body.extend(explanation)
    def footer(canvas,doc):
        export_headroom(f"PDF assembly, page {doc.page}")
        canvas.saveState();canvas.setFont("Helvetica",9);canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(32,18,"IGE Climate Analyzer");canvas.drawRightString(page[0]-32,18,str(doc.page));canvas.restoreState()
    from .p6_static_render import release_render_worker
    release_render_worker()
    if progress:progress(image_number,"Assembling PDF")
    export_headroom("before PDF assembly")
    doc.build(body,onFirstPage=footer,onLaterPages=footer)
    gc.collect()
    export_headroom("after PDF assembly")
    if out.stat().st_size>32*1024*1024:raise MemoryError("PDF exceeds the 32 MiB download budget. Select fewer diagrams for this export.")
    return out.read_bytes()

def render_report(df=None,reference_df=None):
    from .p6_report_structure import (PRESETS,available_catalog,standard_figure,capture_statistics,
                                      concise_context,chapter_name,scope_key,CHAPTERS)
    st.header("Climate report")
    mode=st.radio("Report mode",["Climate assessment","Comprehensive Diagram Atlas"],horizontal=True,key="p66_report_mode")
    if mode=="Comprehensive Diagram Atlas":
        from .p66_ui import render_atlas
        render_atlas(df,st.session_state.get(CONTEXT_KEY,{}),reference_df)
        return
    st.caption("Captured charts, their interpretations and cross-chapter climatic findings are frozen to each source and filter scope. Chapters follow the scientific report sequence.")
    context=st.session_state.get(CONTEXT_KEY,{})
    available=available_catalog(df,context)
    if available:
        with st.expander("Add standard diagrams / presets",expanded=True):
            keys={entry[0]:entry for entry in available}
            user_presets=st.session_state.get("_p6_custom_presets",{})
            presets={**PRESETS,**user_presets}
            options=["Custom selection",*presets]
            if st.session_state.get("p6_catalog_preset") not in options:
                prior=st.session_state.get("_p6_last_preset","Custom selection")
                st.session_state["p6_catalog_preset"]=prior if prior in options else "Custom selection"
            preset=st.selectbox("Report preset",options,key="p6_catalog_preset")
            chosen_key="p6_catalog_selection"
            current=st.session_state.get(chosen_key,st.session_state.get("_p6_catalog_saved",[]))
            if st.session_state.get("_p6_last_preset")!=preset:
                current=[k for k in presets.get(preset,()) if k in keys]
                st.session_state["_p6_last_preset"]=preset
            st.session_state[chosen_key]=[k for k in current if k in keys]
            a,b=st.columns(2)
            if a.button("Select all standard diagrams",key="p6_all_standard"):
                st.session_state[chosen_key]=list(keys)
            if b.button("Clear standard selection",key="p6_clear_standard"):
                st.session_state[chosen_key]=[]
            chosen=st.multiselect("Available standard diagrams",list(keys),
                        format_func=lambda k:f"{CHAPTERS.get(keys[k][1],keys[k][1])} — {keys[k][2]}",key=chosen_key)
            st.session_state["_p6_catalog_saved"]=chosen
            custom_name=st.text_input("Save custom preset as",key="p6_custom_preset_name",max_chars=60)
            if st.button("Save preset",disabled=not chosen or not custom_name.strip(),key="p6_save_custom_preset"):
                name=custom_name.strip()
                if name in PRESETS or name=="Custom selection":st.warning("Choose a different preset name.")
                else:
                    st.session_state["_p6_custom_presets"]={**user_presets,name:tuple(chosen)}
                    st.rerun()
            st.caption("One standard configuration per diagram. Custom variants can be added from the analysis pages. Unavailable quantities are omitted; selected-period totals are not annualized. Custom presets are session-local.")
            if st.button("Add selected standard diagrams",disabled=not chosen,key="p6_add_standard"):
                entries=st.session_state.get(REPORT_KEY,[]);before=len(entries);failures=[]
                with st.spinner("Preparing selected diagrams…"):
                    for id in chosen:
                        entry=keys[id]
                        try:
                            fig,note=standard_figure(entry,df,context,reference_df)
                            c={**context,"page":entry[1],"statistics":capture_statistics(df,entry[1]),"preset diagram":id}
                            item=snapshot(fig,c,note)
                            entries,_=add_snapshot(entries,item)
                        except Exception as exc:failures.append(f"{entry[2]}: {exc}")
                    st.session_state[REPORT_KEY]=entries
                st.success(f"{len(entries)-before} new diagrams added.")
                if failures:st.warning("Diagrams not added: "+"; ".join(failures))
    items=st.session_state.get(REPORT_KEY,[])
    # Earlier snapshots lack a source fingerprint. Do not silently attribute
    # new statistics to a potentially different uploaded file with same name.
    if df is not None and context:
        for item in items:
            c=item["context"]
            if not c.get("source id") or c.get("source id")!=context.get("source id"):continue
            fields=("source","location","first timestamp","last timestamp","selected records","filter","pressure mode","custom pressure","quality policy")
            if all(str(c.get(k,""))==str(context.get(k,"")) for k in fields):
                for key in ("latitude","longitude","elevation_m","station_id"):
                    if key in context:c.setdefault(key,context[key])
                stats=c.get("statistics",{})
                fresh=capture_statistics(df,c.get("page","Overview"))
                for kind in ("overview","chapter"):
                    rows=stats.setdefault(kind,[])
                    known={row[0] for row in rows}
                    rows.extend(row for row in fresh[kind] if row[0] not in known)
                c["statistics"]=stats
                if "cross-chapter synthesis" not in c:
                    from .report_synthesis import cross_chapter_synthesis
                    c["cross-chapter synthesis"]=cross_chapter_synthesis(df)
    if any(not item["context"].get("statistics") for item in items):
        st.caption("Some older saved charts have no verified captured statistics. Re-add them to include their station and chapter overview.")
    if not items:st.info("Your report is empty. Add a diagram from any analysis page or select a standard preset above.");return
    title=st.text_input("Report title",value="Climate assessment",key="p6_report_title",max_chars=160)
    a,b=st.columns(2)
    paper=a.radio("Paper format",["A4","A3"],horizontal=True,key="p6_report_paper")
    orientation=b.radio("Orientation",["Landscape","Portrait"],horizontal=True,key="p6_report_orientation")
    st.caption(f"{len(items)} captured diagrams · {sum(len(x['figure'].encode()) for x in items)/1024**2:.2f} MiB")
    ids=[item["id"] for item in items];by_id={item["id"]:item for item in items}
    selected_key="p6_report_selected"
    previous_ids=st.session_state.get("_p6_previous_ids",[])
    current=st.session_state.get(selected_key,st.session_state.get("_p6_saved_selection",ids))
    st.session_state[selected_key]=[id for id in ids if id in current or id not in previous_ids]
    st.session_state["_p6_previous_ids"]=ids
    a,b=st.columns(2)
    if a.button("Select all saved diagrams",key="p6_select_all_saved"):st.session_state[selected_key]=ids
    if b.button("Deselect all",key="p6_deselect_saved"):st.session_state[selected_key]=[]
    selected=st.multiselect("Diagrams included in report",ids,format_func=lambda id:f"{chapter_name(by_id[id])} — {by_id[id]['title']}",key=selected_key)
    st.session_state["_p6_saved_selection"]=selected
    st.caption("Report chapters follow the scientific climate sequence; diagrams within each chapter retain their saved order.")
    preview_options=["No preview",*ids]
    if st.session_state.get("p6_preview_choice") not in preview_options:
        st.session_state["p6_preview_choice"]="No preview"
    preview=st.selectbox("Preview diagram",preview_options,format_func=lambda id:id if id=="No preview" else by_id[id]["title"],key="p6_preview_choice")
    for i,item in enumerate(items):
        sid=item["id"]
        with st.expander(f"{i+1:02d} · {chapter_name(item)} — {item['title']}",expanded=False):
            st.caption(concise_context(item["context"]))
            st.text_area("Additional report note",value=item.get("note",""),key="p6_note_"+sid,max_chars=3000)
            item["note"]=st.session_state.get("p6_note_"+sid,"")
            if item["interpretation"]:st.write(item["interpretation"])
            if preview==sid:
                original=getattr(st,"_climate_analyzer_original_plotly_chart",st.plotly_chart)
                from .calendar_heatmap_axes import apply_calendar_heatmap_axes,apply_monthly_axes
                preview_fig=pio.from_json(item["figure"])
                from .figure_interpretation_contract import validate_figure_interpretation
                validate_figure_interpretation(preview_fig,item["interpretation"])
                from .calendar_heatmap_axes import set_period_axis_scope
                set_period_axis_scope(preview_fig,context=item.get("context"))
                apply_calendar_heatmap_axes(preview_fig);apply_monthly_axes(preview_fig)
                from .extended_visualization import reflow_diurnal_panels
                reflow_diurnal_panels(preview_fig)
                original(preview_fig,use_container_width=True,config={"displaylogo":False},key="p6_preview_"+sid)
            a,b,c=st.columns(3)
            if a.button("Move up",disabled=i==0,key="p6_up_"+sid):
                items[i-1],items[i]=items[i],items[i-1];st.rerun()
            if b.button("Move down",disabled=i==len(items)-1,key="p6_down_"+sid):
                items[i+1],items[i]=items[i],items[i+1];st.rerun()
            if c.button("Remove",key="p6_remove_"+sid):
                items.pop(i);st.session_state.pop(CAPTURE_MESSAGE_KEY,None);st.rerun()
    if st.button("Clear report",key="p6_clear_report"):
        st.session_state[REPORT_KEY]=[]
        st.session_state.pop(CAPTURE_MESSAGE_KEY,None)
        st.session_state.pop("_p6_previous_ids",None)
        st.session_state.pop("_p6_saved_selection",None)
        st.session_state.pop("_p6_pdf",None)
        st.rerun()
    included=[item for item in items if item["id"] in selected]
    if not included:st.info("Select at least one diagram to export.");return
    # Avoid rebuilding the entire HTML report on every widget rerun.
    from .p66_memory import require_html_headroom
    from .memory_lifecycle import prepare_export,finish_export,manual_cleanup
    html_key=hashlib.sha256()
    for item in included:
        html_key.update(item["id"].encode());html_key.update(str(item.get("note","")).encode())
    html_key.update(json.dumps([title,paper,orientation]).encode())
    html_signature=html_key.hexdigest()
    if st.session_state.get("_p6_html_result") and st.session_state["_p6_html_result"][0]!=html_signature:
        st.session_state.pop("_p6_html_result",None)
    # Match the PDF lifecycle: a single slot, mutually exclusive controls,
    # rerun after generation, and no rerun on download.
    html_slot=st.empty()
    html_result=st.session_state.get("_p6_html_result")
    if html_result and html_result[0]==html_signature:
        html_slot.download_button("Download printable HTML",data=html_result[1],file_name="climate_report.html",mime="text/html",key="p6_html",on_click="ignore")
    elif html_slot.button("Generate printable HTML",key="p6_html_generate",
                          on_click=prepare_export,args=(st.session_state,)):
        try:
            require_html_headroom("Printable report admission")
            data=printable_html(included,title,paper,orientation,use_osm=True)
            require_html_headroom("Printable report download buffer")
            st.session_state["_p6_html_result"]=(html_signature,data)
            st.rerun()
        except Exception as exc:st.error(str(exc))
        finally:finish_export(st.session_state)
    # Full machine-readable audit trail as optional independent export, not
    # printed underneath each figure.
    st.download_button("Download technical metadata",data=json.dumps([{k:v for k,v in i.items() if k!="figure"} for i in included],ensure_ascii=False,indent=2,default=str).encode("utf-8"),
                       file_name="climate_report_metadata.json",mime="application/json",key="p6_meta")
    fingerprint=html_signature+"-pdf-p67-hf1"
    if st.session_state.get("_p6_pdf") and st.session_state["_p6_pdf"][0]!=fingerprint:
        st.session_state.pop("_p6_pdf",None)
    # One stable control region; downloads do not trigger a full rerun.
    pdf_slot=st.empty()
    cache=st.session_state.get("_p6_pdf")
    if cache and cache[0]==fingerprint:
        pdf_slot.download_button("Download PDF",data=cache[1],file_name="climate_report.pdf",mime="application/pdf",key="p6_pdf_download",on_click="ignore")
    elif pdf_slot.button("Generate PDF",key="p6_generate_pdf",
                          on_click=prepare_export,args=(st.session_state,)):
        try:
            status=st.empty()
            try:
                from .p6_static_render import session_cache_dir,export_headroom
                export_headroom("report export admission")
                pdf=pdf_report(included,title,paper,orientation,use_osm=True,render_cache_dir=session_cache_dir(st.session_state),
                               progress=lambda i,label:status.info(f"Rendering figure {i}: {label}"))
                export_headroom("report download buffer")
            finally:status.empty()
            st.session_state["_p6_pdf"]=(fingerprint,pdf)
            st.rerun()
        except Exception as exc:
            st.error(str(exc))
            st.caption("The printable HTML contains all captured charts and can be opened locally, then printed to PDF in your browser.")
        finally:finish_export(st.session_state)
    with st.expander("Export memory management",expanded=False):
        st.caption("Release generated downloads and rendered image cache. Saved diagrams are retained.")
        st.button("Release export resources",key="p6_pdf_release",on_click=manual_cleanup,args=(st.session_state,))
