"""Kaleido renderer: one-shot baseline or sequential export-scoped worker."""
import sys
import json
import time
from pathlib import Path
import plotly.io as pio

def render(source,target,scale):
    t=time.perf_counter()
    fig=pio.from_json(Path(source).read_text(encoding="utf-8"))
    decoded=time.perf_counter()
    pio.write_image(fig,target,format="png",scale=float(scale),engine="kaleido")
    return {"ok":True,"decode_s":decoded-t,"render_and_encode_s":time.perf_counter()-decoded}

def persistent(ready):
    Path(ready).touch()
    for line in sys.stdin:
        job=json.loads(line)
        result=Path(job["result"])
        try:answer=render(job["source"],job["target"],job["scale"])
        except Exception as exc:answer={"ok":False,"error":str(exc)[:2000]}
        pending=result.with_suffix(".tmp")
        pending.write_text(json.dumps(answer),encoding="utf-8")
        pending.replace(result)

if __name__=="__main__":
    try:
        if sys.argv[1]=="--persistent":persistent(sys.argv[2])
        else:render(*sys.argv[1:])
    finally:
        scope=pio.kaleido.scope
        if scope is not None:scope._shutdown_kaleido()
