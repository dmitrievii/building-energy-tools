"""Independent, bounded per-chart heatmap presentation preferences.

The canonical chart figure and source data never enter the preference store.
Semantic chart keys are independent of data values and filter selections.
"""
from __future__ import annotations
from hashlib import sha256
import json
from .heatmap_presentation import (
    CONTOURS, TILES, MODES, _eligible, _meta,
    CONTOUR_MIN_WIDTH, CONTOUR_DEFAULT_WIDTH, CONTOUR_MAX_WIDTH,
)

STORE="_r219_heatmap_settings"
COUNTERS="_r219_heatmap_occurrences"
MAX_PREFERENCES=128
DEFAULT={"mode":CONTOURS,"interval":0.,"labels":True,"width":CONTOUR_DEFAULT_WIDTH,"contrast":"Auto"}

def semantic_key(fig,page):
    # Include chart family, physical quantity and axes, not variable dates,
    # source values, font sizes or global styles. Distinguish duplicate slots.
    traces=[]
    for t in fig.data:
        if t.type!="heatmap":continue
        meta=_meta(t)
        if meta.get("presentation_only_trace"):continue
        ref=t.coloraxis
        color=getattr(fig.layout,ref,None) if ref else t
        traces.append((str(t.name or ""),str(meta.get("heatmap_quantity","")),
                       str(meta.get("heatmap_semantics","")),str(color.colorbar.title.text or ""),
                       str(t.xaxis or "x"),str(t.yaxis or "y")))
    axes=[(str(k),str(getattr(fig.layout,k).title.text or ""))
          for k in fig.layout if str(k).startswith(("xaxis","yaxis"))]
    identity=(str(page),str(fig.layout.title.text or ""),traces,axes)
    return sha256(json.dumps(identity,ensure_ascii=False,sort_keys=True).encode()).hexdigest()[:20]

def chart_key(fig,state):
    base=semantic_key(fig,state.get("climate_analyzer_navigation","source"))
    counts=state.setdefault(COUNTERS,{})
    ordinal=counts.get(base,0)
    counts[base]=ordinal+1
    return base+"_"+str(ordinal)

def get_preferences(state,key):
    return {**DEFAULT,**state.get(STORE,{}).get(key,{})}

def save_preferences(state,key,values):
    store=dict(state.get(STORE,{}))
    store.pop(key,None)
    store[key]={k:values[k] for k in DEFAULT}
    while len(store)>MAX_PREFERENCES:store.pop(next(iter(store)))
    state[STORE]=store

def local_heatmap_settings(st,fig):
    if fig is None or not hasattr(fig,"data"):return {**DEFAULT,"mode":TILES}
    if not any(t.type=="heatmap" for t in fig.data):return {**DEFAULT,"mode":TILES}
    # Eligibility remains owned by the scientific presentation guard. Invalid,
    # categorical, circular and incomplete grids retain their original tiles.
    if not any(_eligible(fig,t) is not None for t in fig.data if t.type=="heatmap"):
        return {**DEFAULT,"mode":TILES}
    state=st.session_state
    key=chart_key(fig,state)
    saved=get_preferences(state,key)
    prefix="_r219_hm_"+key+"_"
    state.setdefault(prefix+"mode",saved["mode"])
    with st.container():
        columns=st.columns([2,1])
        mode=columns[0].radio("Heat-map visualization",MODES,key=prefix+"mode",horizontal=True,
                              help="This setting applies only to this diagram.")
        labels=saved["labels"]
        if mode!=TILES:
            state.setdefault(prefix+"labels",saved["labels"])
            labels=columns[1].checkbox("Contour labels",key=prefix+"labels")
        values={**saved,"mode":mode,"labels":labels}
        if mode!=TILES:
            for field in ("interval","width","contrast"):state.setdefault(prefix+field,saved[field])
            with st.expander("Contour settings",expanded=False):
                values["interval"]=st.number_input("Contour interval (0 = automatic)",min_value=0.,step=.5,key=prefix+"interval")
                values["width"]=st.slider("Contour line thickness [px]", min_value=CONTOUR_MIN_WIDTH,
                                          max_value=CONTOUR_MAX_WIDTH, step=.25, key=prefix+"width")
                values["contrast"]=st.selectbox("Contour line contrast",["Auto","Dark","Light"],key=prefix+"contrast")
    save_preferences(state,key,values)
    return values
