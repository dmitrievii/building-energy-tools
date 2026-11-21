"""P6.6 bounded synchronous atlas export, independent of the curated basket."""
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
import tempfile
import gc
import threading
from .p66_memory import require_headroom,EXPORT_LOCK as _EXPORT_LOCK
from .p6_static_render import render_png,export_headroom,release_render_worker
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
from html import escape
import pandas as pd
import plotly.io as pio
from .p66_catalogue import LEVELS
from .p66_render import make_figure,NotApplicable
from .p6_report_structure import CHAPTERS,concise_context,site_details,locator_figure,capture_statistics,report_figure,zone_legend_entries,complex_figure
from .p6_report import _script_json

MAX_ARCHIVE_BYTES=32*1024*1024
HTML_PART_BYTES=4*1024*1024
MAX_BATCH=50
PDF_MODES=("Chapter PDFs (ZIP)","Single PDF","Interactive HTML by chapter (ZIP)")
def slug(text):
    return re.sub(r"[^a-z0-9]+","-",text.lower()).strip("-") or "chapter"

def manifest_csv(rows):
    stream=io.StringIO()
    fields=["id","chapter","title","kind","column","unit","args","status","reason"]
    w=csv.DictWriter(stream,fieldnames=fields);w.writeheader()
    for r in rows:
        row=dict(r);row["args"]=json.dumps(row.get("args",()),ensure_ascii=False);w.writerow({k:row.get(k,"") for k in fields})
    return stream.getvalue().encode("utf-8-sig")

class PdfWriter:
    """Render one figure at a time, never store the atlas as a figure basket."""
    def __init__(self,*,title,paper,orientation,per_page,context,df,image_renderer=None):
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.lib.pagesizes import A4,A3,landscape
        from reportlab.lib.styles import ParagraphStyle
        self.out=io.BytesIO()
        self.size=A4 if paper=="A4" else A3
        if orientation=="Landscape":self.size=landscape(self.size)
        self.canvas=Canvas(self.out,pagesize=self.size,pageCompression=1)
        self.canvas.setTitle(title)
        self.title=title;self.context=context;self.df=df;self.per_page=per_page
        self.image_renderer=image_renderer
        self.page=0;self.n=0;self.chapter=""
        self.margin=30
        self.body_style=ParagraphStyle("body",fontName="Helvetica",fontSize=11,leading=13.2,splitLongWords=True)
        self.small_style=ParagraphStyle("caption",fontName="Helvetica",fontSize=8.5,leading=10.2,splitLongWords=True)
        self.header_style=ParagraphStyle("header",fontName="Helvetica-Bold",fontSize=15,leading=17.5,splitLongWords=True)
        self.cover()
    @property
    def width(self):return self.size[0]-2*self.margin
    @property
    def height(self):return self.size[1]-2*self.margin
    def text(self,text,x,top,w,style=None,limit=None):
        from reportlab.platypus import Paragraph
        style=style or self.body_style
        # Truncation is for compact figure notes only; full note in manifest
        # is preserved separately. Do not truncate scientific axes or values.
        txt=str(text)
        if limit is not None and len(txt)>limit:txt=txt[:limit-1]+"…"
        para=Paragraph(escape(txt).replace("\n","<br/>"),style)
        _,h=para.wrap(w,self.height);para.drawOn(self.canvas,x,top-h)
        return top-h
    def footer(self):
        self.canvas.setFont("Helvetica",8.5)
        self.canvas.setFillColorRGB(.28,.33,.38)
        self.canvas.drawString(self.margin,15,"IGE Climate Analyzer · Diagram Atlas")
        self.canvas.drawRightString(self.size[0]-self.margin,15,str(self.page+1))
        self.canvas.setFillColorRGB(0,0,0)
    def end(self):
        self.footer();self.canvas.showPage();self.page+=1;self.n=0
    def img(self,fig,x,top,w,h,font=11):
        from reportlab.lib.utils import ImageReader
        from PIL import Image
        export_headroom("Atlas chart preparation")
        f=report_figure(fig,width_pt=w,height_pt=h,font_pt=font,external_zone_legend=bool(zone_legend_entries(fig)))
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix="ige-atlas-figure-") as tmp:
            target=Path(tmp)/"figure.png"
            if self.image_renderer:target.write_bytes(self.image_renderer(f))
            else:render_png(f,target,scale=1.5)
            del f
            with Image.open(target) as im:iw,ih=im.size
            ratio=min(w/iw,h/ih)
            self.canvas.drawImage(str(target),x+(w-iw*ratio)/2,top-ih*ratio,width=iw*ratio,height=ih*ratio,mask="auto")
        gc.collect()
        export_headroom("Atlas image embedded")

    def stats(self,rows,top):
        from reportlab.lib.colors import HexColor
        from reportlab.platypus import Table,TableStyle,Paragraph
        if not rows:return self.text("Statistics unavailable for this source scope.",self.margin,top,self.width)
        p=lambda v:Paragraph(escape(str(v)),self.body_style)
        table=Table([[p("Indicator"),p("Selected-period statistics"),p("Valid records")]]+[[p(v) for v in row] for row in rows],
                    colWidths=[self.width*.28,self.width*.52,self.width*.20],repeatRows=1)
        table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),HexColor("#EEF2F4")),("VALIGN",(0,0),(-1,-1),"TOP"),("LINEBELOW",(0,0),(-1,-1),.4,HexColor("#D7DDE1"))]))
        tw,th=table.wrap(self.width,self.height)
        if top-th<self.margin:self.end();top=self.size[1]-self.margin
        table.drawOn(self.canvas,self.margin,top-th);return top-th
    def cover(self):
        y=self.text(self.title,self.margin,self.size[1]-self.margin,self.width,self.header_style)-8
        y=self.text("Climate and station overview",self.margin,y,self.width,self.header_style)-6
        y=self.text(concise_context(self.context),self.margin,y,self.width)-5
        details=site_details(self.context)
        if details:y=self.text(" · ".join(f"{a}: {v}" for a,v,_ in details),self.margin,y,self.width)-5
        from .p6_osm_map import export_locator
        loc,attribution=export_locator(self.context,use_osm=bool(self.context.get("_report_osm",False)))
        if loc is not None:
            h=min(205,self.height*.36)
            try:self.img(loc,self.margin,y,self.width,h)
            except MemoryError:raise
            except Exception as exc:
                y=self.text("Station map rendering unavailable; coordinates above are retained.",self.margin,y,self.width)-5
            else:y-=h+4;y=self.text(attribution,self.margin,y,self.width,self.small_style)-5
        y=self.stats(capture_statistics(self.df,"Overview")["overview"],y-4)-6
        self.text("Diagram atlas · selected source data and documented reference configurations. Coverage and omitted charts are listed in the separate manifest.",self.margin,y,self.width,self.small_style)
        self.end()
    def begin_chapter(self,chapter):
        if self.n:self.end()
        self.chapter=chapter
        y=self.text(CHAPTERS.get(chapter,chapter),self.margin,self.size[1]-self.margin,self.width,self.header_style)-8
        self.stats(capture_statistics(self.df,chapter)["chapter"],y)
        self.end()
    def add(self,d,fig,note):
        """Readability overrides panel density; full interpretations retained."""
        from reportlab.platypus import Paragraph
        zones=zone_legend_entries(fig)
        complex_chart=complex_figure(fig)
        panels=1 if complex_chart else self.per_page
        def geometry(panels,n):
            cols=2 if panels==4 else 1;rows=2 if panels>1 else 1;gap=12
            w=(self.width-(cols-1)*gap)/cols;h=(self.height-20-(rows-1)*gap)/rows
            return self.margin+(n%cols)*(w+gap),self.size[1]-self.margin-20-(n//cols)*(h+gap),w,h
        def paragraphs(w):
            title=Paragraph(escape(d.title),self.header_style if panels==1 else self.body_style)
            n=Paragraph(escape(note).replace("\n","<br/>"),self.body_style)
            _,th=title.wrap(w,self.height);_,nh=n.wrap(w,self.height)
            return title,n,th,nh
        if complex_chart and self.n:self.end()
        x,top,w,h=geometry(panels,self.n)
        title,n,th,nh=paragraphs(w)
        if panels>1 and (h-th-nh-12<155 or nh>h*.43):
            if self.n:self.end()
            panels=1;x,top,w,h=geometry(1,0);title,n,th,nh=paragraphs(w)
        zone_h=0
        zone_rows=[]
        if zones:
            for i in range(0,len(zones),2):
                cells=[]
                for _,name,color in zones[i:i+2]:
                    p=Paragraph(escape(name),self.body_style);_,hh=p.wrap(w/2-22,self.height)
                    cells.append((p,hh,color))
                row_h=max(v[1] for v in cells)+4
                zone_rows.append((cells,row_h));zone_h+=row_h
            zone_h+=20
        image_h=h-th-zone_h-nh-15
        continued=image_h<max(155,h*.50) and panels==1
        if continued:image_h=h-th-zone_h-12
        if image_h<80:raise ValueError("Too little panel area for readable scientific figure. Choose A3.")
        # Rendering before adding page text keeps failed charts absent from PDF.
        self.img(fig,x,top-th-5,w,image_h,font=11)
        title.drawOn(self.canvas,x,top-th)
        y=top-th-5-image_h-4
        if zone_rows:
            from reportlab.lib.colors import HexColor
            y=self.text("Bioclimatic zones",x,y,w,self.body_style)-3
            for cells,rh in zone_rows:
                for col,(para,hh,color) in enumerate(cells):
                    xx=x+col*w/2
                    self.canvas.setStrokeColor(HexColor("#39447d"))
                    # Text provides the exact zone mapping; the printed
                    # outlined key is consistent with the dashed chart polygons.
                    self.canvas.rect(xx,y-10,11,7,stroke=1,fill=0)
                    para.drawOn(self.canvas,xx+16,y-hh)
                y-=rh
        if self.n==0:self.text(CHAPTERS.get(self.chapter,self.chapter),self.margin,self.size[1]-self.margin,self.width,self.small_style)
        self.n+=1
        if continued:
            self.end()
            y=self.text(d.title+" — Interpretation",self.margin,self.size[1]-self.margin,self.width,self.header_style)-10
            # Long explanatory text may continue on further pages; no truncation.
            remaining=Paragraph(escape(note).replace("\n","<br/>"),self.body_style)
            while remaining:
                _,need=remaining.wrap(self.width,self.height)
                if need<=y-self.margin:
                    remaining.drawOn(self.canvas,self.margin,y-need);self.end();break
                chunks=remaining.split(self.width,max(1,y-self.margin))
                if not chunks:raise ValueError("Interpretation cannot fit printable page.")
                first=chunks[0];_,hh=first.wrap(self.width,y-self.margin);first.drawOn(self.canvas,self.margin,y-hh)
                self.end()
                if len(chunks)<2:break
                remaining=chunks[1];y=self.size[1]-self.margin
            return
        n.drawOn(self.canvas,x,y-nh)
        if self.n>=panels:self.end()
    def finish(self):
        from .p6_static_render import release_render_worker
        release_render_worker()
        if self.n:self.end()
        self.canvas.save();return self.out.getvalue()

def _html_header(title,context,chapter,df):
    stats=capture_statistics(df,chapter)["chapter"]
    table="<table>"+ "".join("<tr>"+"".join("<td>"+escape(str(v))+"</td>" for v in row)+"</tr>" for row in stats)+"</table>"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>"+escape(title)+"</title><style>body{font:11pt Arial,sans-serif;margin:28px;color:#202830} h1,h2,h3{margin:10px 0} table{border-collapse:collapse;width:100%}td{padding:5px;border-bottom:1px solid #ddd}.panel{break-inside:avoid;margin:24px 0}.plot{width:100%;min-height:400px} @media print{button{display:none}} </style><script src='plotly.min.js'></script></head><body><h1>"+escape(title)+"</h1><h2>"+escape(CHAPTERS.get(chapter,chapter))+"</h2><p>"+escape(concise_context(context))+"</p>"+table)
def _html_panel(d,fig,note,seq):
    zones=zone_legend_entries(fig)
    from .extended_visualization import diurnal_panel_rows
    rows=diurnal_panel_rows(fig)
    h=max(380,rows*155) if rows else (540 if complex_figure(fig) else 380)
    f=report_figure(fig,width_pt=780,height_pt=h,external_zone_legend=bool(zones))
    raw=json.loads(pio.to_json(f))
    key=""
    if zones:key='<p><b>Bioclimatic zones</b></p><div style="display:grid;grid-template-columns:1fr 1fr;gap:4px">'+ "".join('<div><span style="display:inline-block;width:12px;height:9px;border:1px dashed #39447d;background:'+escape(color,quote=True)+'"></span> '+escape(name)+'</div>' for _,name,color in zones)+'</div>'
    return f'<section class="panel"><h3>{escape(d.title)}</h3><div class="plot" id="chart{seq}"></div>'+key+f'<p style="white-space:pre-wrap">{escape(note)}</p></section><script>const f{seq}={_script_json(raw)};f{seq}.layout.autosize=true;delete f{seq}.layout.width;Plotly.newPlot("chart{seq}",f{seq}.data,f{seq}.layout,{{responsive:true}});</script>'

def catalogue_batches(diagrams,batch_size=20):
    if not 1<=batch_size<=MAX_BATCH:raise ValueError("Batch size outside supported range.")
    admitted=[d for d in diagrams if d.status=="available"]
    return [admitted[i:i+batch_size] for i in range(0,len(admitted),batch_size)]

def generate_atlas(diagrams,df,context,**kwargs):
    """One bounded export per server process at a time."""
    if not _EXPORT_LOCK.acquire(blocking=False):
        raise RuntimeError("Another atlas export is in progress. Try again after it finishes.")
    try:
        require_headroom()
        from .p6_static_render import render_session
        with render_session(cache_dir=kwargs.pop("render_cache_dir",None)):
            return _generate_atlas(diagrams,df,context,**kwargs)
    finally:
        gc.collect()
        _EXPORT_LOCK.release()

def _generate_atlas(diagrams,df,context,*,reference_df=None,title="Comprehensive Diagram Atlas",paper="A4",orientation="Landscape",
                   mode=PDF_MODES[0],per_page=2,progress=None,image_renderer=None,coverage=LEVELS[-1]):
    """Explicitly process every requested admitted variant; report all outcomes."""
    if mode not in PDF_MODES or paper not in ("A4","A3") or orientation not in ("Landscape","Portrait") or per_page not in (1,2,4):
        raise ValueError("Invalid atlas output configuration.")
    manifest=[asdict(d) for d in diagrams]
    available=[(i,d) for i,d in enumerate(diagrams) if d.status=="available"]
    if not available:raise ValueError("No supported diagrams in the selected chapters.")
    if mode!=PDF_MODES[2] and len(available)>MAX_BATCH:raise ValueError("Select a bounded export batch (at most 50 admitted diagrams per request). The full catalogue remains available across batches.")
    groups={}
    for i,d in available:groups.setdefault(d.chapter,[]).append((i,d))
    zbuf=tempfile.TemporaryFile(mode="w+b")
    archive=zipfile.ZipFile(zbuf,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=4) if mode!="Single PDF" else None
    writer=None
    if mode=="Single PDF":writer=PdfWriter(title=title,paper=paper,orientation=orientation,per_page=per_page,context=context,df=df,image_renderer=image_renderer)
    processed=0
    notes={}
    html_files=[]
    def check_archive():
        if zbuf.tell()>MAX_ARCHIVE_BYTES:
            raise MemoryError("Atlas exceeds the 32 MiB download budget. Select fewer chapters or a smaller export batch.")
    try:
        if mode==PDF_MODES[2]:
            # One offline library per ZIP, not one compressed copy per HTML part.
            from plotly.offline import get_plotlyjs
            archive.writestr("plotly.min.js",get_plotlyjs())
            check_archive()
        for chapter,entries in groups.items():
            cache={} # expensive shared kernels cached per chapter only
            if mode=="Chapter PDFs (ZIP)":writer=PdfWriter(title=title,paper=paper,orientation=orientation,per_page=per_page,context=context,df=df,image_renderer=image_renderer)
            if writer:writer.begin_chapter(chapter)
            parts=[];part_size=0;part_no=1;seq=0
            chapter_header=_html_header(title,context,chapter,df) if mode==PDF_MODES[2] else ""
            def flush_html():
                nonlocal parts,part_size,part_no
                if not parts:return
                name=f"{slug(chapter)}-{part_no:03d}.html"
                # Stream the bounded part to the disk-backed ZIP instead of
                # materializing another copy of the entire HTML document.
                with archive.open(name,"w") as output:
                    output.write(chapter_header.encode("utf-8"))
                    for panel in parts:output.write(panel.encode("utf-8"))
                    output.write(b"</body></html>")
                html_files.append((name,CHAPTERS.get(chapter,chapter),part_no,len(parts)))
                parts=[];part_size=0;part_no+=1
                check_archive()
            for i,d in entries:
                if progress:progress(processed,len(available),d.title)
                processed+=1
                export_headroom(f"Atlas before chart {processed}: {d.title}")
                fig=None
                try:
                    fig,note=make_figure(d,df,context,reference_df,cache)
                    export_headroom(f"Atlas prepared chart {processed}: {d.title}")
                    if writer:writer.add(d,fig,note)
                    else:
                        seq+=1;panel=_html_panel(d,fig,note,seq)
                        size=len(panel.encode("utf-8"))
                        if parts and part_size+size>HTML_PART_BYTES:flush_html()
                        parts.append(panel);part_size+=size
                        del panel
                    manifest[i]["status"]="generated";manifest[i]["reason"]=""
                    notes[d.id]=note
                except MemoryError:raise
                except NotApplicable as exc:manifest[i]["status"]="not applicable";manifest[i]["reason"]=str(exc)
                except Exception as exc:manifest[i]["status"]="failed";manifest[i]["reason"]=f"{type(exc).__name__}: {exc}"
                finally:
                    del fig
                if processed%5==0:gc.collect()
                export_headroom(f"Atlas after chart {processed}: {d.title}")
                # Explicit memory budget; never pretend to have generated the
                # unprocessed tail if the deployment cannot contain an atlas.
                if zbuf.tell()>MAX_ARCHIVE_BYTES or writer and writer.out.tell()>MAX_ARCHIVE_BYTES:
                    raise MemoryError("Atlas batch exceeds 32 MiB. Select fewer diagrams per batch.")
            if mode=="Chapter PDFs (ZIP)":
                release_render_worker()
                export_headroom(f"Atlas chapter assembly: {chapter}")
                pdf=writer.finish()
                if len(pdf)>MAX_ARCHIVE_BYTES:raise MemoryError("Chapter PDF exceeds 32 MiB; reduce batch size.")
                archive.writestr(slug(chapter)+".pdf",pdf);del pdf;writer=None
                gc.collect()
            elif mode==PDF_MODES[2]:flush_html()
        if progress:progress(len(available),len(available),"Atlas complete")
        metadata={"coverage":coverage,"title":title,"created_utc":datetime.now(timezone.utc).isoformat(),"context":context,
                  "paper":paper,"orientation":orientation,"diagrams_per_page":per_page,"counts":dict(Counter(row["status"] for row in manifest)),
                  "calculation_notes":notes,"manifest":manifest}
        if archive:
            if mode==PDF_MODES[2]:
                counts=metadata["counts"]
                links="".join(f'<li><a href="{escape(name,quote=True)}">{escape(label)} · Part {part} ({count} diagrams)</a></li>' for name,label,part,count in html_files)
                index=("<!doctype html><html lang='en'><meta charset='utf-8'><title>"+escape(title)+"</title>"
                    "<style>body{font:11pt Arial,sans-serif;margin:32px;max-width:850px}li{margin:7px 0}</style><h1>"+escape(title)+"</h1>"
                    f"<p>{counts.get('generated',0)} diagrams generated from {len(available)} admitted diagrams. Full outcomes: <a href='coverage.csv'>coverage CSV</a> and <a href='atlas_metadata.json'>metadata</a>.</p><ul>"+links+"</ul></html>")
                archive.writestr("index.html",index)
                metadata["html_files"]=[name for name,_,_,_ in html_files]
                check_archive()
            archive.writestr("coverage.csv",manifest_csv(manifest))
            archive.writestr("atlas_metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2,default=str))
            archive.close()
            if zbuf.tell()>MAX_ARCHIVE_BYTES:raise MemoryError("Atlas batch exceeds 32 MiB; reduce batch size.")
            require_headroom()
            zbuf.seek(0);output=zbuf.read()
        else:
            release_render_worker()
            export_headroom("Atlas final PDF assembly")
            output=writer.finish()
        if len(output)>MAX_ARCHIVE_BYTES:raise MemoryError("Atlas batch exceeds 32 MiB; reduce batch size.")
        return output,manifest,metadata
    finally:
        if archive:archive.close()
        zbuf.close()
