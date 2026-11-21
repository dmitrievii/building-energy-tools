"""Disposable Kaleido renderer (invoked by absolute script path)."""
import sys
from pathlib import Path
import plotly.io as pio
if __name__=="__main__":
    source,target,scale=sys.argv[1:]
    try:
        fig=pio.from_json(Path(source).read_text(encoding="utf-8"))
        pio.write_image(fig,target,format="png",scale=float(scale),engine="kaleido")
    finally:
        scope=pio.kaleido.scope
        if scope is not None:scope._shutdown_kaleido()
