"""Fail closed on missing source evidence or any scientific hash mismatch."""
import json
from pathlib import Path
import sys

def main():
    left,right=map(Path,sys.argv[1:])
    for kind in ("ten-minute","hourly","monthly"):
        a=json.loads((left/(kind+".json")).read_text())
        b=json.loads((right/(kind+".json")).read_text())
        if a!=b or set(a["observations"])!={"Temperature","Precipitation and Snow","return"}:
            raise AssertionError("Extended source parity mismatch: "+kind)
        print("PASS",kind,"exact chart and saved Report evidence")

if __name__=="__main__":main()
