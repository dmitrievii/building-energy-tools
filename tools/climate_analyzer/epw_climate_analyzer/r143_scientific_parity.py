"""Explicit test-only reproducible fingerprints of actual displayed and saved charts."""
import hashlib
import json

def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()

def _row(figure,context,interpretation):
    graph=json.loads(figure)
    # Only transient Plotly trace UID is excluded by normal report serialization.
    # All scientific arrays, trace properties, full layout and context remain.
    traces=graph.get("data",[])
    arrays=[{k:v for k,v in trace.items() if k in ("x","y","z","r","theta","values","lat","lon","open","high","low","close")}
            for trace in traces]
    if not any(arrays):raise ValueError("No scientific coordinate arrays in registered figure")
    return {"arrays":_digest(arrays),"data":_digest(traces),"figure":_digest(graph),
            "complete":_digest({"figure":graph,"context":context,"interpretation":str(interpretation or "")})}

def evidence(state):
    from plotly.io import to_json
    from .chart_lifecycle import DISPLAYED
    from .p6_report import REPORT_KEY
    return {"displayed":[_row(to_json(fig,validate=True,remove_uids=True),context,interpretation)
                         for fig,context,interpretation,key in state.get(DISPLAYED,[])],
            "saved":[_row(item["figure"],item["context"],item["interpretation"])
                     for item in state.get(REPORT_KEY,[])]}
