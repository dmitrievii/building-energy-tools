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
MAX_ITEMS=24
MAX_BYTES=25*1024*1024

def set_context(state,*,page,source,location,df=None,extra=None):
    meta={"page":str(page),"source":str(source),"location":str(location)}
    if df is not None and len(df):
        spec=state.get("_active_global_filter_spec",{})
        meta.update({"first timestamp":str(df.index.min()),"last timestamp":str(df.index.max()),
                     "selected records":len(df),"native interval minutes":str(df.attrs.get("canonical_native_interval_minutes","not declared")),
                     "time basis":str(df.attrs.get("climate_time_basis","Chronological")),
                     "filter":json.dumps(spec,default=str,ensure_ascii=False,sort_keys=True)})
    if extra:meta.update({str(k):str(v) for k,v in extra.items()})
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
        raise ValueError("Report capacity reached (24 charts / 25 MiB figure data). Remove entries before adding another.")
    return [*items,item],"Diagram added to report."
def capture_control(st,fig,key):
    context=st.session_state.get(CONTEXT_KEY)
    if not isinstance(context,dict) or context.get("page")=="Report":return
    if st.button("Add to report",key="p6_capture_"+str(key),help="Save this displayed figure after global presentation settings are applied."):
        try:
            item=snapshot(fig,context,st.session_state.get(INTERPRETATION_KEY,""))
            entries,message=add_snapshot(st.session_state.get(REPORT_KEY,[]),item)
            st.session_state[REPORT_KEY]=entries
            st.caption(message)
        except (ValueError,TypeError) as exc:st.warning(str(exc))

def _safe(value):
    return html.escape(str(value or ""),quote=True)
def _script_json(value):
    return json.dumps(value,ensure_ascii=True).replace("<","\\u003c").replace(">","\\u003e").replace("&","\\u0026")
def printable_html(items,title,paper,orientation):
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    from plotly.offline import get_plotlyjs
    pages=[]
    for i,item in enumerate(items,1):
        meta=" · ".join(f"{k}: {v}" for k,v in item["context"].items())
        fig=json.loads(item["figure"])
        # Keep captured layout/trace data; fit to printable page without
        # modifying the stored figure. JS is embedded, no remote CDN.
        pages.append(f'<section class="sheet"><h2>{i:02d} · {_safe(item["title"])}</h2><p class="meta">{_safe(meta)}</p><div class="plot" id="figure{i}"></div><p>{_safe(item["interpretation"])}</p><p>{_safe(item.get("note",""))}</p><footer>Captured {_safe(item["captured"])} · IGE Climate Analyzer</footer></section><script>const f{i}={_script_json(fig)};Plotly.newPlot("figure{i}",f{i}.data,f{i}.layout,{{responsive:true,displayModeBar:false}});</script>')
    toc="".join(f"<li>{_safe(x['title'])}</li>" for x in items)
    css=f"""@page {{size:{paper} {orientation.lower()};margin:12mm}} body{{font:11pt Arial,sans-serif;color:#202830;margin:12px}} h1{{font-size:25pt}} h2{{font-size:16pt}} .meta,footer{{font-size:8pt;color:#586472;overflow-wrap:anywhere}} p{{white-space:pre-wrap;overflow-wrap:anywhere}} .sheet{{break-before:page;page-break-before:always}} .plot{{width:100%;min-height:250px;overflow:hidden;break-inside:avoid}} button{{padding:8px 16px}} @media print{{button{{display:none}} body{{margin:0}}}}"""
    return ("<!doctype html><html><head><meta charset='utf-8'><title>"+_safe(title)+"</title><style>"+css+"</style><script>"+get_plotlyjs()+"</script></head><body><button onclick='window.print()'>Print / Save as PDF</button><h1>"+_safe(title)+"</h1><p>IGE Climate Analyzer · archived chart snapshots</p><p>Engineering screening, not a certified regulatory calculation. Refer to each figure's source and assumptions.</p><ol>"+toc+"</ol>"+"".join(pages)+"</body></html>").encode("utf-8")

def pdf_report(items,title,paper,orientation,*,image_renderer=None):
    """Server PDF: actual static figure images; fail closed if any cannot render."""
    from reportlab.lib.pagesizes import A4,A3,landscape
    from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Image
    from PIL import Image as PILImage
    if paper not in ("A4","A3") or orientation not in ("Portrait","Landscape"):raise ValueError("Invalid paper settings.")
    if not items:raise ValueError("Add at least one chart.")
    page=A4 if paper=="A4" else A3
    if orientation=="Landscape":page=landscape(page)
    out=io.BytesIO()
    doc=SimpleDocTemplate(out,pagesize=page,rightMargin=32,leftMargin=32,topMargin=30,bottomMargin=34,title=title,author="IGE Climate Analyzer")
    styles=getSampleStyleSheet()
    styles.add(ParagraphStyle(name="MetaP6",fontName="Helvetica",fontSize=8,leading=10,textColor=colors.HexColor("#52606D"),spaceAfter=6,splitLongWords=True))
    def para(value,style="BodyText"):
        return Paragraph(_safe(value).replace("\n","<br/>"),styles[style])
    body=[para(title,"Title"),Spacer(1,16),para("IGE Climate Analyzer · Report of captured diagrams"),para("Engineering screening. Individual source, period, calculation assumptions and data limitations are recorded with each figure. No new calculations are performed."),Spacer(1,12),para("Contents","Heading2")]
    body.extend(para(f"{i:02d} · {item['title']}") for i,item in enumerate(items,1))
    for i,item in enumerate(items,1):
        fig=pio.from_json(item["figure"])
        try:
            if image_renderer is not None:png=image_renderer(fig)
            else:
                # Captured pixel aspect is kept. The higher raster scale
                # improves print resolution without changing chart layout.
                png=fig.to_image(format="png",scale=2)
            raw=io.BytesIO(png)
            with PILImage.open(raw) as im:w,h=im.size
            raw.seek(0)
        except Exception as exc:raise RuntimeError(f"Static rendering failed for chart {i}: {item['title']}. Use the printable HTML export. ({exc})") from exc
        body.extend([PageBreak(),para(f"{i:02d} · {item['title']}","Heading2"),
                     para(" · ".join(f"{k}: {v}" for k,v in item["context"].items()),"MetaP6")])
        scale=min((doc.width-12)/w,(doc.height*.64)/h)
        body.extend([Image(raw,width=w*scale,height=h*scale),Spacer(1,8)])
        if item["interpretation"]:body.append(para(item["interpretation"]))
        else:body.append(para("No separate interpretation captured.","MetaP6"))
        if item.get("note"):body.append(para(item["note"]))
        body.append(para("Captured "+item["captured"],"MetaP6"))
    def footer(canvas,doc):
        canvas.saveState();canvas.setFont("Helvetica",8);canvas.setFillColor(colors.HexColor("#52606D"))
        canvas.drawString(32,18,"IGE Climate Analyzer");canvas.drawRightString(page[0]-32,18,str(doc.page));canvas.restoreState()
    doc.build(body,onFirstPage=footer,onLaterPages=footer)
    return out.getvalue()

def render_report():
    st.header("Climate report")
    st.caption("Captured figures are session-local snapshots. Changing source or filters does not change saved charts. Revisit any diagram and choose Add to report.")
    items=st.session_state.get(REPORT_KEY,[])
    if not items:st.info("Your report is empty. Add a diagram from any analysis page.");return
    title=st.text_input("Report title",value="Climate assessment",key="p6_report_title",max_chars=160)
    a,b=st.columns(2)
    paper=a.radio("Paper format",["A4","A3"],horizontal=True,key="p6_report_paper")
    orientation=b.radio("Orientation",["Landscape","Portrait"],horizontal=True,key="p6_report_orientation")
    st.caption(f"{len(items)} captured diagrams · {sum(len(x['figure'].encode()) for x in items)/1024**2:.2f} MiB")
    for i,item in enumerate(items):
        sid=item["id"]
        with st.expander(f"{i+1:02d} · {item['title']}",expanded=False):
            st.caption(" · ".join(f"{k}: {v}" for k,v in item["context"].items()))
            st.text_area("Additional report note",value=item.get("note",""),key="p6_note_"+sid,max_chars=3000)
            item["note"]=st.session_state.get("p6_note_"+sid,"")
            if item["interpretation"]:st.write(item["interpretation"])
            # Do not apply current presentation to a saved immutable preview.
            original=getattr(st,"_climate_analyzer_original_plotly_chart",st.plotly_chart)
            original(pio.from_json(item["figure"]),use_container_width=True,config={"displaylogo":False},key="p6_preview_"+sid)
            a,b,c=st.columns(3)
            if a.button("Move up",disabled=i==0,key="p6_up_"+sid):
                items[i-1],items[i]=items[i],items[i-1];st.rerun()
            if b.button("Move down",disabled=i==len(items)-1,key="p6_down_"+sid):
                items[i+1],items[i]=items[i],items[i+1];st.rerun()
            if c.button("Remove",key="p6_remove_"+sid):
                items.pop(i);st.rerun()
    if st.button("Clear report",key="p6_clear_report"):
        st.session_state[REPORT_KEY]=[];st.rerun()
    st.download_button("Download printable HTML",data=printable_html(items,title,paper,orientation),
                       file_name="climate_report.html",mime="text/html",key="p6_html")
    fingerprint=hashlib.sha256(json.dumps([items,title,paper,orientation],default=str,sort_keys=True).encode()).hexdigest()
    if st.button("Generate PDF",key="p6_generate_pdf"):
        try:
            with st.spinner("Rendering captured diagrams…"):
                pdf=pdf_report(items,title,paper,orientation)
            st.session_state["_p6_pdf"]=(fingerprint,pdf)
        except (Exception,) as exc:
            st.error(str(exc))
            st.caption("The printable HTML contains all captured charts and can be opened locally, then printed to PDF in your browser.")
    cache=st.session_state.get("_p6_pdf")
    if cache and cache[0]==fingerprint:
        st.download_button("Download PDF",data=cache[1],file_name="climate_report.pdf",mime="application/pdf",key="p6_pdf_download")
