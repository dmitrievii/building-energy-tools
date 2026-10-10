#!/usr/bin/env python3
"""Run one NASA NEX-GDDP CMIP6 solar model using the separately validated v0.3 downloader.

One model/realization per GH matrix job. Uses exactly the historical and future windows
in the original study; any missing year, invalid unit, calendar or daily data fails.
"""
from __future__ import annotations
import argparse,importlib.util,sys
from pathlib import Path

MODELS=("MRI-ESM2-0","MPI-ESM1-2-HR","CanESM5","GFDL-ESM4",
        "IPSL-CM6A-LR","NorESM2-MM","EC-Earth3")
def main():
 parser=argparse.ArgumentParser()
 parser.add_argument("--model",required=True,choices=MODELS)
 parser.add_argument("--member",default="r1i1p1f1")
 args=parser.parse_args()
 if args.member!="r1i1p1f1":
  raise ValueError("Member mismatch with remotely verified historical/scenario catalog")
 path=Path(__file__).with_name("nasa_rsds_full_graz.py")
 spec=importlib.util.spec_from_file_location("ige_nasa_rsds_base",path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 module.MODEL=args.model
 module.MEMBER=args.member
 module.OUT=Path("outputs/nasa_ensemble")/args.model
 module.OUT.mkdir(parents=True,exist_ok=True)
 module.YEARROWS.clear()
 print("RUN_MODEL",args.model,args.member,flush=True)
 module.main()
 print("COMPLETE_MODEL",args.model,len(module.YEARROWS),flush=True)
if __name__=="__main__": main()
