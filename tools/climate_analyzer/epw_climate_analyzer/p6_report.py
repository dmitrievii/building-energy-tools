"""Session-local report snapshots and self-contained print/PDF output."""
from __future__ import annotations
import hashlib
import html
import io
import json
import re
from datetime import datetime,timezone
import plotly.io as pio
import plotly.graph_objects as go
import streamlit as st

REPORT_KEY="_p6_report_items"
CONTEXT_KEY="_p6_report_context"
INTERPRETATION_KEY="_p6_report_interpretation"
MAX_ITEMS=80
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
        if str(df.attrs.get("canonical_native_resolution","")).lower()=="monthly":
            meta["native interval minutes"]="monthly"
        else:meta["native interval minutes"]=str(df.attrs.get("canonical_native_interval_minutes",native_interval_hours(df)*60))
    state[CONTEXT_KEY]=meta

def snapshot(fig,context,interpretation=""):
    title=str(fig.layout.title.text or "Untitled diagram")
    payload=pio.to_json(fig,validate=True,remove_uids=True)
    meta=dict(context)
    return {"id":hashlib.sha256((payload+json.dumps(meta,sort_keys=True,default=str)+str(interpretation)).encode()).hexdigest(),
            "title":title,"figure":payload,"context":meta,"interpretation":str(interpretation or ""),
            "captured":datetime.now(timezone.utc).isoformat(),"note":""}
def add_snapshot(items,item):
    if any(x["id"]==item["id"] for x in items):return items,"This exact diagram is already in the report."
    if len(items)>=MAX_ITEMS or sum(len(x["figure"].encode()) for x in items)+len(item["figure"].encode())>MAX_BYTES:
        raise ValueError("Report capacity reached (80 charts / 65 MiB figure data). Remove entries before adding another.")
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
        state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":True,
                                    "message":f"{message} {len(entries)} chart(s) in report."}
    except Exception as exc:
        state[CAPTURE_MESSAGE_KEY]={"key":button_key,"ok":False,"message":f"Chart not saved: {exc}"}

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
    displayed=st.session_state.get("_p6_displayed_charts",[])
    displayed.append((fig,saved_context,interpretation,button_key))
    st.session_state["_p6_displayed_charts"]=displayed
    st.button("Add to report",key=button_key,
              on_click=save_displayed_chart,
              args=(st.session_state,fig,saved_context,interpretation,button_key),
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
    if state.get(NAVIGATION_KEY) not in ("Report","Climate File Source"):
        st.sidebar.button("Add all displayed diagrams",key="p6_capture_all",
                          on_click=save_all_displayed,args=(state,),
                          help="Capture every Plotly diagram on the current analysis page.")
        if state.get("_p6_bulk_notice"):st.sidebar.caption(state.pop("_p6_bulk_notice"))
    state["_p6_displayed_charts"]=[]


def _safe(value):
    return html.escape(str(value or ""),quote=True)
def _script_json(value):
    return json.dumps(value,ensure_ascii=True).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
def printable_html(items,title,paper,orientation):
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    from plotly.offline import get_plotlyjs
    from .p6_report_structure import contexts,ordered_groups,concise_context,site_details,locator_figure,report_figure
    from reportlab.lib.pagesizes import A4,A3,landscape
    page=A4 if paper=="A4" else A3
    if orientation=="Landscape":page=landscape(page)
    width=page[0]-64
    height=page[1]-64
    seq=0
    def plot(fig,h):
        nonlocal seq
        seq+=1
        f=report_figure(fig,width_pt=width,height_pt=h)
        raw=json.loads(pio.to_json(f))
        return f'<div class="plot" id="figure{seq}"></div><script>const f{seq}={_script_json(raw)};Plotly.newPlot("figure{seq}",f{seq}.data,f{seq}.layout,{{responsive:false,displayModeBar:false}});</script>'
    def table(rows):
        if not rows:return "<p>Statistics unavailable for this saved scope.</p>"
        return "<table><thead><tr><th>Indicator</th><th>Selected-period statistics</th><th>Valid records</th></tr></thead><tbody>"+"".join("<tr>"+"".join("<td>"+_safe(cell)+"</td>" for cell in row)+"</tr>" for row in rows)+"</tbody></table>"
    groups=ordered_groups(items)
    pages=[]
    for idx,context in enumerate(contexts(items)):
        section="<h1>"+_safe(title)+"</h1><h2>Climate and station overview</h2>" if idx==0 else '<section class="sheet"><h2>Additional climate / analysis period</h2>'
        section+="<p>"+_safe(concise_context(context))+"</p>"
        loc=locator_figure(context)
        if loc is not None:section+=plot(loc,min(height*.32,170))+"<p>Station locator · Natural Earth, 1:110m · geographic context, not a street map.</p>"
        if site_details(context):section+="<p>"+_safe(" · ".join(f"{a}: {v}" for a,v,_ in site_details(context)))+"</p>"
        section+=table(context.get("statistics",{}).get("overview",[]))
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
            scope_line="<p>"+_safe(concise_context(item["context"]))+"</p>" if len(contexts(entries))>1 else ""
            pages.append(f'<section class="sheet"><h3>{chapter_no}.{k} · {_safe(item["title"])}</h3>'+scope_line+plot(fig,min(height*.65,430))+"<p>"+_safe(item["interpretation"])+"</p><p>"+_safe(item.get("note",""))+"</p></section>")
    css=f"""@page {{size:{paper} {orientation.lower()};margin:11.3mm}} *{{box-sizing:border-box}} body{{font:11pt Arial,sans-serif;color:#202830;margin:12px;width:{width}pt}} h1{{font-size:23pt;margin:0 0 9pt}} h2{{font-size:17pt;margin:0 0 8pt}} h3{{font-size:13pt;margin:0 0 6pt}} p{{white-space:pre-wrap;overflow-wrap:anywhere;margin:5pt 0;line-height:1.25}} table{{width:100%;border-collapse:collapse;font:inherit;margin:5pt 0}} td,th{{padding:4pt 5pt;text-align:left;border-bottom:1px solid #D7DDE1}} th{{color:#314652;background:#EEF2F4}} .sheet{{break-before:page;page-break-before:always}} .plot{{width:100%;break-inside:avoid}} button{{padding:8px 16px}} @media print{{button{{display:none}} body{{margin:0}}}}"""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>"+_safe(title)+"</title><style>"+css+"</style><script>"+get_plotlyjs()+"</script></head><body><button onclick='window.print()'>Print / Save as PDF</button>"+"".join(pages)+"</body></html>").encode("utf-8")

def pdf_report(items,title,paper,orientation,*,image_renderer=None):
    """Professional chapter-organized PDF; no raw widget/diagnostic dumps."""
    from reportlab.lib.pagesizes import A4,A3,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image,Table,TableStyle
    from PIL import Image as PILImage
    from .p6_report_structure import contexts,ordered_groups,concise_context,site_details,locator_figure,report_figure
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    if not items:raise ValueError("Add at least one chart.")
    page=A4 if paper=="A4" else A3
    if orientation=="Landscape":page=landscape(page)
    out=io.BytesIO()
    doc=SimpleDocTemplate(out,pagesize=page,rightMargin=32,leftMargin=32,topMargin=30,bottomMargin=34,title=title,author="IGE Climate Analyzer")
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
    def image(fig,h,label):
        try:
            f=report_figure(fig,width_pt=width,height_pt=h)
            png=image_renderer(f) if image_renderer is not None else f.to_image(format="png",scale=2)
            raw=io.BytesIO(png)
            with PILImage.open(raw) as im:w,ih=im.size
            raw.seek(0)
            scale=min(width/w,h/ih)
            return Image(raw,width=w*scale,height=ih*scale,hAlign="CENTER")
        except Exception as exc:raise RuntimeError(f"Static rendering failed for {label}. Use the printable HTML export. ({exc})") from exc
    groups=ordered_groups(items);body=[]
    for idx,context in enumerate(contexts(items)):
        if idx:body.append(PageBreak())
        if not idx:body.append(para(title,"ReportTitle"))
        body.extend([para("Climate and station overview" if idx==0 else "Additional climate / analysis period","ReportChapter"),
                     para(concise_context(context))])
        loc=locator_figure(context)
        if loc is not None:
            body.extend([image(loc,min(doc.height*.28,145),"station location"),para("Station locator · Natural Earth 1:110m · geographic context, not a street map.")])
        site=site_details(context)
        # Compact location row rather than another table.
        if site:body.append(para(" · ".join(f"{a}: {v}" for a,v,_ in site)))
        body.extend([stats_table(context.get("statistics",{}).get("overview",[])),Spacer(1,7)])
        if not idx:body.append(para("Report chapters: "+" · ".join(n for n,_ in groups)))
    for chapter_no,(chapter,entries) in enumerate(groups,1):
        body.extend([PageBreak(),para(f"{chapter_no:02d} · {chapter}","ReportChapter")])
        for c in contexts(entries):
            body.extend([para(concise_context(c)),stats_table(c.get("statistics",{}).get("chapter",[])),Spacer(1,7)])
        for k,item in enumerate(entries,1):
            body.extend([PageBreak(),para(f"{chapter_no}.{k} · {item['title']}","ReportFigure")])
            if len(contexts(entries))>1:body.append(para(concise_context(item["context"])))
            body.extend([image(pio.from_json(item["figure"]),min(doc.height*.65,430),item["title"]),Spacer(1,7)])
            if item["interpretation"]:body.append(para(item["interpretation"]))
            if item.get("note"):body.append(para(item["note"]))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont("Helvetica",9);canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(32,18,"IGE Climate Analyzer");canvas.drawRightString(page[0]-32,18,str(doc.page));canvas.restoreState()
    doc.build(body,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()

def render_report(df=None,reference_df=None):
    from .p6_report_structure import (PRESETS,available_catalog,standard_figure,capture_statistics,
                                      concise_context,chapter_name,scope_key,CHAPTERS)
    st.header("Climate report")
    mode=st.radio("Report mode",["Climate assessment","Comprehensive Diagram Atlas"],horizontal=True,key="p66_report_mode")
    if mode=="Comprehensive Diagram Atlas":
        from .p66_ui import render_atlas
        render_atlas(df,st.session_state.get(CONTEXT_KEY,{}),reference_df)
        return
    st.caption("Saved diagrams remain unchanged when the active climate or filters change. The report groups selected diagrams by chapter and opens with station and climate statistics.")
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
    st.caption("Report chapters follow their first occurrence; diagrams within a chapter follow the saved order.")
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
                original(pio.from_json(item["figure"]),use_container_width=True,config={"displaylogo":False},key="p6_preview_"+sid)
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
    st.download_button("Download printable HTML",data=printable_html(included,title,paper,orientation),
                       file_name="climate_report.html",mime="text/html",key="p6_html")
    # Full machine-readable audit trail as optional independent export, not
    # printed underneath each figure.
    st.download_button("Download technical metadata",data=json.dumps([{k:v for k,v in i.items() if k!="figure"} for i in included],ensure_ascii=False,indent=2,default=str).encode("utf-8"),
                       file_name="climate_report_metadata.json",mime="application/json",key="p6_meta")
    fingerprint=hashlib.sha256(json.dumps([included,title,paper,orientation,"layout-hf2"],default=str,sort_keys=True).encode()).hexdigest()
    if st.button("Generate PDF",key="p6_generate_pdf"):
        try:
            st.session_state.pop("_p6_pdf",None)
            with st.spinner("Rendering captured diagrams…"):
                pdf=pdf_report(included,title,paper,orientation)
            st.session_state["_p6_pdf"]=(fingerprint,pdf)
        except Exception as exc:
            st.error(str(exc))
            st.caption("The printable HTML contains all captured charts and can be opened locally, then printed to PDF in your browser.")
    cache=st.session_state.get("_p6_pdf")
    if cache and cache[0]==fingerprint:
        st.download_button("Download PDF",data=cache[1],file_name="climate_report.pdf",mime="application/pdf",key="p6_pdf_download")
