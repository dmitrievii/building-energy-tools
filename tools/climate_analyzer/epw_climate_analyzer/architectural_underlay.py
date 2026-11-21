"""Presentation-only uploaded architectural reference image, no network access."""
from __future__ import annotations
import base64
from io import BytesIO
from PIL import Image, ImageOps

def prepare_underlay(payload,rotation=0.):
    if len(payload)>12*1024*1024:
        raise ValueError("Reference image exceeds 12 MiB.")
    with Image.open(BytesIO(payload)) as original:
        if original.format not in {"PNG","JPEG","WEBP"}:
            raise ValueError("Only PNG, JPEG and WebP are supported.")
        if original.width*original.height>25_000_000:
            raise ValueError("Reference image exceeds 25 megapixels.")
        im=ImageOps.exif_transpose(original).convert("RGBA")
        im.thumbnail((1800,1800))
        if rotation:
            im=im.rotate(-float(rotation),resample=Image.Resampling.BICUBIC,expand=True)
        out=BytesIO();im.save(out,format="PNG")
    return "data:image/png;base64,"+base64.b64encode(out.getvalue()).decode("ascii")

def apply_underlay(fig,source,*,scale=1.,x=0.,y=0.,opacity=.75):
    meta=fig.layout.meta if isinstance(fig.layout.meta,dict) else {}
    if not meta.get("compass_polar") or not any(t.type in {"barpolar","scatterpolar","scatterpolargl"} for t in fig.data):
        return False
    fig.layout.polar.bgcolor="rgba(0,0,0,0)"
    domain=fig.layout.polar.domain
    xd=domain.x or (0.,1.);yd=domain.y or (0.,1.)
    cx=(xd[0]+xd[1])/2;cy=(yd[0]+yd[1])/2
    fig.add_layout_image(dict(source=source,xref="paper",yref="paper",
        x=cx+float(x),y=cy+float(y),sizex=(xd[1]-xd[0])*float(scale),
        sizey=(yd[1]-yd[0])*float(scale),xanchor="center",yanchor="middle",
        sizing="contain",opacity=float(opacity),layer="below",name="Architectural reference underlay"))
    return True
