"""Offline UI acceptance; original weather and one original terrain receipt only."""
import json
from pathlib import Path
import runpy
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/climate_analyzer'))
from epw_climate_analyzer import site_elevation
receipts=json.loads((ROOT/'deployment/audits/ige-workspace-20261030/elevation-source.json').read_text())
def terrain(lat,lon):
    for row in receipts:
        if (row['latitude'],row['longitude']) == (lat,lon): return row
    raise ValueError('Offline acceptance has no original terrain receipt for this point')
site_elevation.lookup_elevation=terrain
runpy.run_path(str(ROOT/'deployment/ige_h1_s1_f1_visual_harness.py'),run_name='__main__')
