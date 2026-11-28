"""Production-interpreter smoke; actual imports, contours, psychrometrics, SVG/PDF."""
import sys
import importlib
from importlib.metadata import version
import numpy as np
import pandas as pd
import contourpy
import plotly.graph_objects as go
import plotly.io as pio
assert sys.version_info[:2] == (3, 14), sys.version
assert version("numpy") == "2.3.5"
assert version("contourpy") == "1.3.3"
for module in ("streamlit", "streamlit_folium", "scipy", "scipy.interpolate",
               "scipy.optimize", "pvlib", "numba", "llvmlite", "pythermalcomfort.models",
               "pyarrow", "h5py", "reportlab", "openpyxl", "PIL",
               "epw_climate_analyzer.psychrometrics", "epw_climate_analyzer.p6_report",
               "epw_climate_analyzer.p66_render"):
    importlib.import_module(module)
    print("IMPORT PASS", module, flush=True)
from pythermalcomfort.models import utci
r=utci(tdb=[25.],tr=[25.],v=[1.],rh=[50.],limit_inputs=True,round_output=False)
assert 24 < float(r.utci[0]) < 26
generator=contourpy.contour_generator(z=np.array([[0.,1.],[1.,2.]]))
assert generator.lines(1.)
fig=go.Figure(go.Scatter(x=[0,1],y=[0,1]))
assert "scatter" in pio.to_json(fig)
for fmt,signature in (("png",b"\x89PNG"),("pdf",b"%PDF")):
    image=pio.to_image(fig,format=fmt,width=500,height=300)
    assert image.startswith(signature), fmt
    print("STATIC EXPORT PASS",fmt,len(image),flush=True)
print("PYTHON 3.14 PRODUCTION IMPORT AND FUNCTIONAL SMOKE PASS", flush=True)
