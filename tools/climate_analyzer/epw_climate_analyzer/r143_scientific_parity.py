"""Explicit test-only reproducible fingerprints of actual displayed and saved charts."""
import hashlib
import json

def _digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,default=str).encode()).hexdigest()

CAPTURE_KEY="_r143_parity_last_capture"

def _row(figure,context,interpretation):
    graph=json.loads(figure)
    # Only transient Plotly trace UID is excluded by normal report serialization.
    # All scientific arrays, trace properties, full layout and context remain.
    traces=graph.get("data",[])
    arrays=[{k:v for k,v in trace.items() if k in ("x","y","z","r","theta","values","lat","lon","open","high","low","close")}
            for trace in traces]
    if not any(arrays):raise ValueError("No scientific coordinate arrays in registered figure")
    return {"arrays":_digest(arrays),"data":_digest(traces),"figure":_digest(graph),
            "layout":_digest(graph.get("layout",{})),
            "context":_digest(context),
            "context_fields":{str(k):_digest(v) for k,v in sorted(context.items())},
            "interpretation":_digest(str(interpretation or "")),
            "complete":_digest({"figure":graph,"context":context,"interpretation":str(interpretation or "")})}

def record_capture(state,fig,context,interpretation,button_key,items,item_id):
    """Fingerprint the exact callback source and the selected persisted record."""
    from plotly.io import to_json
    prior=_row(to_json(fig,validate=True,remove_uids=True),context,interpretation)
    matches=[item for item in items if item["id"]==item_id]
    if len(matches)!=1:raise AssertionError("Captured report ID missing or ambiguous")
    saved=_row(matches[0]["figure"],matches[0]["context"],matches[0]["interpretation"])
    state[CAPTURE_KEY]={"key":button_key,"before":prior,"saved":saved,
                        "count":len(items),"sequence":state.get(CAPTURE_KEY,{}).get("sequence",0)+1}


def evidence(state):
    from plotly.io import to_json
    from .chart_lifecycle import DISPLAYED
    from .p6_report import REPORT_KEY
    return {"capture":state.get(CAPTURE_KEY), "displayed":[dict(_row(to_json(fig,validate=True,remove_uids=True),context,interpretation),key=key)
                         for fig,context,interpretation,key in state.get(DISPLAYED,[])],
            "saved":[_row(item["figure"],item["context"],item["interpretation"])
                     for item in state.get(REPORT_KEY,[])]}
