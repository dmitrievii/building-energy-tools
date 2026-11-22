"""Fail closed on missing/mismatched cross-arm real-app evidence."""
import json
import sys
from pathlib import Path

def compare(left,right):
    for value in (left,right):
        if value.get("schema")!="R143-EF" or value.get("error") or value.get("completed")!=value.get("cycles"):
            raise AssertionError("Incomplete scientific qualification")
        if value["cycles"]<4:raise AssertionError("Insufficient cycles")
        expected={f"{n}:scientific-{stage}" for n in range(1,value["cycles"]+1)
                  for stage in ("temperature-a","wind-a","temperature-b","solar-b")}
        expected|={f"{value['cycles']+1}:{stage}" for stage in ("concurrent-a","concurrent-b","concurrent-b-after-reset")}
        if set(value["observations"])!=expected:
            raise AssertionError("Incomplete stage coverage")
    a,b=left["observations"],right["observations"]
    differences=[key for key in sorted(a) if a[key]!=b.get(key)]
    if differences:raise AssertionError("Scientific/report digest mismatch: "+", ".join(differences))
    print(f"PASS: {len(a)} matched observations; exact figure data/layout, report content and context")

if __name__=="__main__":
    compare(*(json.loads(Path(p).read_text()) for p in sys.argv[1:]))
