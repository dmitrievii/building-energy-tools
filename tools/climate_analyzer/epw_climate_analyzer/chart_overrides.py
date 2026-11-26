"""R2.20 first chart-local presentation editor.

Only scalar presentation preferences are retained, never figures or data.
Scientific values, interpretation metadata, geometry, and trace identities
remain owned by canonical chart builders. Unsupported scales stay canonical.
"""
from __future__ import annotations
from hashlib import sha256
from itertools import islice
from numbers import Real
import json
import math
import re

STORE="_r220_chart_preferences"
COUNTERS="_r220_chart_occurrences"
OPEN="_r220_chart_editor_open"
META="r220_chart_overrides"
MAX_CHARTS=128
AXIS_RE=re.compile(r"^[xy]axis\d*$")
MAX_TEXT=160

def _meta(fig):
    return fig.layout.meta if isinstance(fig.layout.meta,dict) else {}

def chart_identity(fig,state):
    traces=[(t.type,str(t.name or ""),str(getattr(t,"xaxis",None) or ""),
             str(getattr(t,"yaxis",None) or ""),str(getattr(t,"subplot",None) or ""),
             str(getattr(t,"legendgroup",None) or "")) for t in fig.data]
    axes=[(k,str(getattr(fig.layout,k).title.text or ""))
          for k in sorted(fig.layout.to_plotly_json()) if AXIS_RE.fullmatch(k)]
    identity=(state.get("climate_analyzer_navigation","source"),str(fig.layout.title.text or ""),
              str(_meta(fig).get("layout_kind","")),traces,axes)
    base=sha256(json.dumps(identity,ensure_ascii=False).encode()).hexdigest()[:20]
    counts=state.setdefault(COUNTERS,{})
    n=counts.get(base,0)
    counts[base]=n+1
    return base+"_"+str(n)

def cartesian_axes(fig):
    keys={k for k in fig.layout.to_plotly_json() if AXIS_RE.fullmatch(k)}
    for t in fig.data:
        for coord in ("x","y"):
            if getattr(t,coord,None) is not None:
                ref=getattr(t,coord+"axis",None) or coord
                keys.add(coord+"axis"+ref[1:])
    return tuple(sorted(keys,key=lambda k:(k[0],int(k[5:] or "1"))))

def range_allowed(fig,key):
    if key not in cartesian_axes(fig):return False
    meta=_meta(fig)
    if meta.get("fixed_physical_axis_relationship") or getattr(fig,"frames",()):return False
    # Preserve coordinated calendar grids, heatmap geometry, categories,
    # existing nonlinear scales, anchored and shared physical axes.
    if any(t.type in ("heatmap","contour","surface","image") for t in fig.data):return False
    axis=getattr(fig.layout,key)
    if axis.type not in (None,"linear") or axis.scaleanchor or axis.matches or axis.autorange=="reversed":return False
    if axis.tickmode=="array" or re.search(r"\b(month|year|day|hour of day|week|date|calendar|season)\b",
                    str(axis.title.text or ""),re.I):return False
    ref=key.replace("axis","")
    for k in cartesian_axes(fig):
        other=getattr(fig.layout,k)
        if other.scaleanchor==ref or other.matches==ref:return False
    coord=key[0]
    traces=[t for t in fig.data if (getattr(t,coord+"axis",None) or coord)==ref and getattr(t,coord,None) is not None]
    samples=[v for t in traces for v in islice(getattr(t,coord),32) if v is not None]
    return bool(samples) and all(isinstance(v,Real) and not isinstance(v,bool) for v in samples)

def _valid_bounds(value):
    try:
        lo,hi=value
        return math.isfinite(float(lo)) and math.isfinite(float(hi)) and float(lo)<float(hi)
    except (TypeError,ValueError):return False

def apply_chart_overrides(fig,prefs,*,include_title=True):
    """Apply validated display-only edits after canonical chart reflow."""
    if not isinstance(prefs,dict):return fig
    title=prefs.get("title","")
    if include_title and isinstance(title,str) and title.strip():
        fig.layout.title.text=title[:MAX_TEXT]
    legend=prefs.get("legend_title","")
    if isinstance(legend,str) and legend.strip():fig.layout.legend.title.text=legend[:MAX_TEXT]
    for key,edit in prefs.get("axes",{}).items():
        if key not in cartesian_axes(fig) or not isinstance(edit,dict):continue
        axis=getattr(fig.layout,key)
        # Re-evaluate the scientific guard before changing any label.
        allow=range_allowed(fig,key)
        label=edit.get("title","")
        if isinstance(label,str) and label.strip():axis.title.text=label[:MAX_TEXT]
        bounds=edit.get("range")
        if allow and _valid_bounds(bounds):
            lo,hi=map(float,bounds)
            axis.range=[lo,hi]
            axis.autorange=False
            step=edit.get("tick")
            if isinstance(step,Real) and math.isfinite(step) and step>0 and (hi-lo)/step<=500:
                axis.tickmode="linear"
                axis.dtick=float(step)
    return fig

def replay_chart_overrides(fig,*,include_title=True):
    return apply_chart_overrides(fig,_meta(fig).get(META,{}),include_title=include_title)

def toggle_editor(state,key):
    state[OPEN]=None if state.get(OPEN)==key else key

def reset_editor(state,key):
    store=dict(state.get(STORE,{}))
    store.pop(key,None)
    state[STORE]=store
    prefix="_r220_edit_"+key+"_"
    for k in list(state.keys()):
        if isinstance(k,str) and k.startswith(prefix):state.pop(k,None)

def _remember(state,key,prefs):
    store=dict(state.get(STORE,{}))
    store.pop(key,None)
    if prefs:store[key]=prefs
    while len(store)>MAX_CHARTS:store.pop(next(iter(store)))
    state[STORE]=store

def render_chart_editor(st,fig,key):
    state=st.session_state
    prefs=dict(state.get(STORE,{}).get(key,{}))
    prefix="_r220_edit_"+key+"_"
    opened=state.get(OPEN)==key
    st.button("Close chart settings" if opened else "Chart settings",icon=":material/tune:",
              type="tertiary",key="_r220_toggle_"+key,on_click=toggle_editor,args=(state,key))
    if opened:
        with st.container(border=True):
            st.caption("Overrides apply only to this chart and its saved report copy. Blank labels use the original.")
            title=st.text_input("Chart title",value=prefs.get("title",""),placeholder=str(fig.layout.title.text or "Original"),
                                max_chars=MAX_TEXT,key=prefix+"title")
            legend=st.text_input("Legend title",value=prefs.get("legend_title",""),
                                 placeholder=str(fig.layout.legend.title.text or "Original"),
                                 max_chars=MAX_TEXT,key=prefix+"legend")
            edits=dict(prefs.get("axes",{}))
            axes=cartesian_axes(fig)
            if axes:
                chosen=st.selectbox("Axis",axes,format_func=lambda k:f"{k.upper()} · {getattr(fig.layout,k).title.text or 'Untitled'}",
                                    key=prefix+"axis")
                current=dict(edits.get(chosen,{}))
                suffix=prefix+chosen+"_"
                label=st.text_input("Axis title",value=current.get("title",""),
                                    placeholder=str(getattr(fig.layout,chosen).title.text or "Original"),
                                    max_chars=MAX_TEXT,key=suffix+"title")
                entry={"title":label} if label.strip() else {}
                if range_allowed(fig,chosen):
                    fixed=st.checkbox("Custom axis range",value="range" in current,key=suffix+"fixed")
                    if fixed:
                        bounds=current.get("range",(None,None))
                        c1,c2=st.columns(2)
                        lo=c1.number_input("Minimum",value=bounds[0],key=suffix+"min")
                        hi=c2.number_input("Maximum",value=bounds[1],key=suffix+"max")
                        tick=st.number_input("Tick interval (blank = automatic)",min_value=0.,value=current.get("tick"),key=suffix+"tick")
                        if _valid_bounds((lo,hi)):
                            entry["range"]=[float(lo),float(hi)]
                            if tick is not None and tick>0 and (hi-lo)/tick<=500:entry["tick"]=float(tick)
                            elif tick is not None and tick>0:st.warning("Tick interval would create more than 500 intervals.")
                        else:st.caption("Enter finite bounds with minimum below maximum.")
                else:st.caption("Scale follows the chart's physical or calendar definition.")
                if entry:edits[chosen]=entry
                else:edits.pop(chosen,None)
            prefs={}
            if title.strip():prefs["title"]=title
            if legend.strip():prefs["legend_title"]=legend
            if edits:prefs["axes"]=edits
            _remember(state,key,prefs)
            st.button("Reset this chart",key=prefix+"reset",on_click=reset_editor,args=(state,key))
    if prefs:
        # Keep the canonical axis identities for report reflow and ensure
        # only validated local state is serialized alongside the chart.
        apply_chart_overrides(fig,prefs)
        meta=dict(_meta(fig))
        meta[META]=prefs
        fig.update_layout(meta=meta)
    return fig
