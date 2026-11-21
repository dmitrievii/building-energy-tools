"""P6.7 reproducible renderer benchmark; baseline and candidate run separately."""
import argparse
import json
import time
from pathlib import Path
import numpy as np
from PIL import Image
import plotly.graph_objects as go
from epw_climate_analyzer import p6_static_render as r

def figure(i):
    x=np.arange(8760)
    k=i%5
    if k==0:
        f=go.Figure(go.Scatter(x=x,y=np.sin(x/200+i)*10,mode="lines"))
    elif k==1:
        f=go.Figure(go.Heatmap(z=np.sin(np.arange(24*365).reshape(24,365)/60+i)))
    elif k==2:
        f=go.Figure(go.Barpolar(theta=np.arange(0,360,22.5),r=2+np.sin(np.arange(16)+i)))
    elif k==3:
        a=np.linspace(-2,2,32);xx,yy=np.meshgrid(a,a)
        f=go.Figure(go.Surface(x=xx,y=yy,z=np.sin(xx**2+yy**2+i)))
    else:
        f=go.Figure(go.Scatter(x=x[::6],y=np.cos(x[::6]/50+i),mode="markers",marker={"size":3}))
    return f.update_layout(template="plotly_white",title=f"Benchmark {i}",width=1000,height=550)

def compare(a,b):
    with Image.open(a) as ia, Image.open(b) as ib:
        x=np.asarray(ia.convert("RGB"),dtype=np.int16)
        y=np.asarray(ib.convert("RGB"),dtype=np.int16)
        if x.shape!=y.shape:raise AssertionError("Image geometry changed")
        delta=np.abs(x-y)
        return {"mean_abs":float(delta.mean()),"fraction_pixels_gt_2":float(np.mean(np.max(delta,axis=2)>2))}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--count",type=int,choices=[20,50,100,200],required=True)
    p.add_argument("--mode",choices=["disposable","adaptive","cache"],required=True)
    p.add_argument("--out",type=Path,required=True)
    a=p.parse_args()
    a.out.mkdir(parents=True,exist_ok=True)
    folder=a.out/a.mode;folder.mkdir(exist_ok=True)
    cache=a.out/"cache" if a.mode!="disposable" else None
    metrics=[];comparisons=[]
    memory=r.container_memory()
    if memory is None or memory[1]!=3072*r.MIB:raise AssertionError(f"Expected actual 3 GiB cgroup limit; got {memory}")
    t=time.perf_counter()
    with r.render_session(mode="disposable" if a.mode=="disposable" else "adaptive",cache_dir=cache,metrics=metrics) as s:
        for i in range(a.count):
            target=folder/f"{i:03d}.png"
            r.render_png(figure(i),target)
            if a.mode!="disposable":
                diff=compare(a.out/"disposable"/target.name,target);comparisons.append(diff)
    elapsed=time.perf_counter()-t
    result={"mode":a.mode,"count":a.count,"elapsed_s":elapsed,"sampled_peak_mib":s.peak/r.MIB,
            "worker_starts":s.starts,"renders":s.renders,"cache_hits":s.hits,"fallbacks":s.fallbacks,
            "metrics":metrics,"pixel_comparisons":comparisons}
    (a.out/f"{a.mode}.json").write_text(json.dumps(result,indent=2))
    print(json.dumps({k:v for k,v in result.items() if k not in ("metrics","pixel_comparisons")}),flush=True)
    if a.mode=="adaptive":
        if s.fallbacks or not 0<s.starts<a.count:raise AssertionError("Persistent worker reuse not demonstrated")
    if a.mode=="cache" and s.hits==0 and a.count==20:raise AssertionError("No cache reuse")
    if any(d["mean_abs"]>.2 or d["fraction_pixels_gt_2"]>.005 for d in comparisons):
        raise AssertionError("Image fidelity differs from disposable baseline")

if __name__=="__main__":main()
