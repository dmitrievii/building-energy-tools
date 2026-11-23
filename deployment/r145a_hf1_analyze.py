"""Read original and fresh inventories. Record identity stability and two gates."""
import json
import sys
from pathlib import Path
from epw_climate_analyzer.cloud_memory_ownership import summarize_ownership

def read(path):
    v=json.loads(path.read_text())
    return {"capture":v.get("captured_at_utc"),
            "ownership":summarize_ownership(v)}

def main():
    output=Path(sys.argv[1]);paths=[Path(p) for p in sys.argv[2:]]
    results=[read(p) for p in paths]
    # First artifact is historical. At least two fresh captures are mandatory.
    if len(results)<3:raise AssertionError("Historical and two fresh captures required")
    fresh=results[1:]
    current=[r["ownership"]["processes"]["current"] for r in fresh]
    ids=[(r["pid"],r["start_ticks"]) for r in current]
    stable=ids[0][0] is not None and ids[0][1] is not None and len(set(ids))==1
    candidates=[{(r["pid"],r["start_ticks"]) for r in x["ownership"]["processes"]["other_matching_targets"] if r["pid"] is not None and r["start_ticks"] is not None} for x in fresh]
    repeated=set.intersection(*candidates)
    admission=stable and all(x["ownership"]["admission"]=="EVIDENCE_GATES_PASS_NOT_PROMOTED" for x in fresh)
    result={"schema":"R145A-HF1-REPEATED","captures":results,"same_current_process":stable,
            "repeated_other_targets":[{"pid":p,"start_ticks":t} for p,t in sorted(repeated)],
            "admission":"EVIDENCE_GATES_PASS_NOT_PROMOTED" if admission else "BLOCKED",
            "scope":"Two public observer snapshots, without resetting other sessions or changing allocator. Same process identity does not establish an orphan's lifecycle."}
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
    if not admission:raise SystemExit(1)
if __name__=="__main__":main()
