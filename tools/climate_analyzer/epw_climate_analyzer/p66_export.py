"""P6.6 bounded synchronous atlas export, independent of the curated basket."""
from __future__ import annotations
import csv
import io
import json
import re
import zipfile
from collections import Counter
from dataclasses import asdict
from datetime import datetime,timezone
from html import escape
import pandas as pd
import plotly.io as pio
from .p66_catalogue import LEVELS
from .p66_render import make_figure,NotApplicable
from .p6_report_structure import CHAPTERS,concise_context,site_details,locator_figure,capture_statistics,report_figure
from .p6_report import _script_json

MAX_ARCHIVE_BYTES=200*1024*1024
HTML_PART_BYTES=16*1024*1024
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
        f=report_figure(fig,width_pt=w,height_pt=h,font_pt=font)
        png=self.image_renderer(f) if self.image_renderer else f.to_image(format="png",scale=1.5)
        data=io.BytesIO(png)
        with Image.open(data) as im:iw,ih=im.size
        data.seek(0);ratio=min(w/iw,h/ih)
        self.canvas.drawImage(ImageReader(data),x+(w-iw*ratio)/2,top-ih*ratio,width=iw*ratio,height=ih*ratio,mask="auto")
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
        loc=locator_figure(self.context)
        if loc is not None:
            h=min(134,self.height*.27)
            try:self.img(loc,self.margin,y,self.width,h)
            except Exception as exc:
                y=self.text("Station map rendering unavailable; coordinates above are retained.",self.margin,y,self.width)-5
            else:y-=h+4;y=self.text("Station locator: Natural Earth, 1:110m.",self.margin,y,self.width,self.small_style)-5
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
        # 1/2 vertically stacked or 4 in 2x2 grid. Render before writing any
        # new figure text so a failed static export cannot leave a false panel.
        cols=2 if self.per_page==4 else 1
        rows=2 if self.per_page>1 else 1
        gap=12
        cellw=(self.width-(cols-1)*gap)/cols
        cellh=(self.height-20-(rows-1)*gap)/rows
        row=self.n//cols;col=self.n%cols
        x=self.margin+col*(cellw+gap)
        top=self.size[1]-self.margin-20-row*(cellh+gap)
        title_style=self.header_style if self.per_page==1 else self.body_style
        note_style=self.body_style if self.per_page==1 else self.small_style
        from reportlab.platypus import Paragraph
        title=Paragraph(escape(d.title),title_style);_,th=title.wrap(cellw,cellh)
        # Wrap notes at the physical cell size; compact notes remain in the
        # manifest even when the visible block needs to be abbreviated.
        short=note if self.per_page==1 else note[:175]+("…" if len(note)>175 else "")
        n=Paragraph(escape(short),note_style);_,nh=n.wrap(cellw,cellh)
        h=cellh-th-nh-12
        if h<65:raise ValueError("Too little panel area for readable figure; choose fewer diagrams per page.")
        self.img(fig,x,top-th-5,cellw,h,font=11 if self.per_page<4 else 8.5)
        title.drawOn(self.canvas,x,top-th)
        n.drawOn(self.canvas,x,top-th-5-h-nh-3)
        if self.n==0:self.text(CHAPTERS.get(self.chapter,self.chapter),self.margin,self.size[1]-self.margin,self.width,self.small_style)
        self.n+=1
        if self.n==self.per_page:self.end()
    def finish(self):
        if self.n:self.end()
        self.canvas.save();return self.out.getvalue()

def _html_header(title,context,chapter,df):
    from plotly.offline import get_plotlyjs
    stats=capture_statistics(df,chapter)["chapter"]
    table="<table>"+ "".join("<tr>"+"".join("<td>"+escape(str(v))+"</td>" for v in row)+"</tr>" for row in stats)+"</table>"
    return ("<!doctype html><html><head><meta charset='utf-8'><title>"+escape(title)+"</title><style>body{font:11pt Arial,sans-serif;margin:28px;color:#202830} h1,h2,h3{margin:10px 0} table{border-collapse:collapse;width:100%}td{padding:5px;border-bottom:1px solid #ddd}.panel{break-inside:avoid;margin:24px 0}.plot{width:100%;min-height:400px} @media print{button{display:none}} </style><script>"+get_plotlyjs()+"</script></head><body><h1>"+escape(title)+"</h1><h2>"+escape(CHAPTERS.get(chapter,chapter))+"</h2><p>"+escape(concise_context(context))+"</p>"+table)
def _html_panel(d,fig,note,seq):
    raw=json.loads(pio.to_json(fig))
    return f'<section class="panel"><h3>{escape(d.title)}</h3><div class="plot" id="chart{seq}"></div><p>{escape(note)}</p></section><script>const f{seq}={_script_json(raw)};f{seq}.layout.autosize=true;delete f{seq}.layout.width;Plotly.newPlot("chart{seq}",f{seq}.data,f{seq}.layout,{{responsive:true}});</script>'

def generate_atlas(diagrams,df,context,*,reference_df=None,title="Comprehensive Diagram Atlas",paper="A4",orientation="Landscape",
                   mode=PDF_MODES[0],per_page=2,progress=None,image_renderer=None,coverage=LEVELS[-1]):
    """Explicitly process every requested admitted variant; report all outcomes."""
    if mode not in PDF_MODES or paper not in ("A4","A3") or orientation not in ("Landscape","Portrait") or per_page not in (1,2,4):
        raise ValueError("Invalid atlas output configuration.")
    manifest=[asdict(d) for d in diagrams]
    available=[(i,d) for i,d in enumerate(diagrams) if d.status=="available"]
    if not available:raise ValueError("No supported diagrams in the selected chapters.")
    groups={}
    for i,d in available:groups.setdefault(d.chapter,[]).append((i,d))
    zbuf=io.BytesIO()
    archive=zipfile.ZipFile(zbuf,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=4) if mode!="Single PDF" else None
    writer=None
    if mode=="Single PDF":writer=PdfWriter(title=title,paper=paper,orientation=orientation,per_page=per_page,context=context,df=df,image_renderer=image_renderer)
    processed=0
    notes={}
    try:
        for chapter,entries in groups.items():
            cache={} # expensive shared kernels cached per chapter only
            if mode=="Chapter PDFs (ZIP)":writer=PdfWriter(title=title,paper=paper,orientation=orientation,per_page=per_page,context=context,df=df,image_renderer=image_renderer)
            if writer:writer.begin_chapter(chapter)
            parts=[];part_size=0;part_no=1;seq=0
            def flush_html():
                nonlocal parts,part_size,part_no
                if not parts:return
                html=_html_header(title,context,chapter,df)+"".join(parts)+"</body></html>"
                archive.writestr(f"{slug(chapter)}-{part_no:03d}.html",html)
                parts=[];part_size=0;part_no+=1
            for i,d in entries:
                if progress:progress(processed,len(available),d.title)
                processed+=1
                try:
                    fig,note=make_figure(d,df,context,reference_df,cache)
                    if writer:writer.add(d,fig,note)
                    else:
                        seq+=1;panel=_html_panel(d,fig,note,seq)
                        size=len(panel.encode("utf-8"))
                        if parts and part_size+size>HTML_PART_BYTES:flush_html()
                        parts.append(panel);part_size+=size
                    manifest[i]["status"]="generated";manifest[i]["reason"]=""
                    notes[d.id]=note
                except NotApplicable as exc:manifest[i]["status"]="not applicable";manifest[i]["reason"]=str(exc)
                except Exception as exc:manifest[i]["status"]="failed";manifest[i]["reason"]=f"{type(exc).__name__}: {exc}"
                # Explicit memory budget; never pretend to have generated the
                # unprocessed tail if the deployment cannot contain an atlas.
                if zbuf.tell()>MAX_ARCHIVE_BYTES or writer and writer.out.tell()>MAX_ARCHIVE_BYTES:
                    raise MemoryError("Atlas archive exceeds 200 MiB. Select fewer chapters or use interactive HTML parts.")
            if mode=="Chapter PDFs (ZIP)":
                archive.writestr(slug(chapter)+".pdf",writer.finish());writer=None
            elif mode==PDF_MODES[2]:flush_html()
        if progress:progress(len(available),len(available),"Atlas complete")
        metadata={"coverage":coverage,"title":title,"created_utc":datetime.now(timezone.utc).isoformat(),"context":context,
                  "paper":paper,"orientation":orientation,"diagrams_per_page":per_page,"counts":dict(Counter(row["status"] for row in manifest)),
                  "calculation_notes":notes,"manifest":manifest}
        if archive:
            archive.writestr("coverage.csv",manifest_csv(manifest))
            archive.writestr("atlas_metadata.json",json.dumps(metadata,ensure_ascii=False,indent=2,default=str))
            archive.close()
            output=zbuf.getvalue()
        else:output=writer.finish()
        if len(output)>MAX_ARCHIVE_BYTES:raise MemoryError("Atlas exceeds the 200 MiB download budget. Split into smaller chapter selections.")
        return output,manifest,metadata
    finally:
        if archive:archive.close()
