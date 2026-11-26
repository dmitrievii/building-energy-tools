"""R2.19 source-neutral navigation and compact sidebar layout.

Internal page IDs remain canonical and all widgets have session-local state.
No scientific frames, figures, or Streamlit containers are retained in state.
"""
from __future__ import annotations
from .ui_contract import NAVIGATION_KEY, NAVIGATION_LABELS

GROUPS=(
    ("Climate source",("Climate File Source",)),
    ("Overview",("Overview",)),
    ("Climate",("Temperature","Humidity and Psychrometrics","Solar and Radiation","Wind and Ventilation","Sky and Daylight","Precipitation and Snow")),
    ("Explore",("Time Series and Overlay",)),
    ("Design",("Natural Ventilation","Shading analysis","HVAC and Passive Design","Outdoor Thermal Comfort")),
    ("Compare Climates",("Compare Climates",)),
    ("Report",("Report",)),
    ("Data Quality",("Data Quality",)),
)
SERVICE_KEY="_r219_service_open"
PRESSURE_STATE="_r219_pressure_preferences"

def grouped_pages(pages):
    available=set(pages)
    return tuple((label,tuple(p for p in members if p in available))
                 for label,members in GROUPS if available.intersection(members))

def short_label(page):
    return NAVIGATION_LABELS.get(page,page).split(" — ",1)[-1]

def select_page(state,page):
    state[NAVIGATION_KEY]=page
    state[SERVICE_KEY]=False

def render_navigation(st,pages,area=None):
    """Use one selection per group; retain canonical routing and queued navigation."""
    area=area if area is not None else st.sidebar
    state=st.session_state
    pages=tuple(pages)
    if not pages:return None
    if state.get(NAVIGATION_KEY) not in pages:
        state[NAVIGATION_KEY]="Overview" if "Overview" in pages else pages[0]
    active=state[NAVIGATION_KEY]
    state["_r219_available_pages"]=pages
    area.markdown("**Analysis**")
    for group,members in grouped_pages(pages):
        key="_r219_nav_"+group.replace(" ","_")
        if group in ("Climate","Design","Explore"):
            # Streamlit resets the inactive group's widget before instantiation.
            # The canonical selection is independent of these widget keys.
            selected=active if active in members else None
            if state.get(key)!=selected:state[key]=selected
            with area.expander(group,expanded=active in members):
                st.radio(group+" pages",members,index=None,key=key,format_func=short_label,
                         label_visibility="collapsed",on_change=_group_changed,args=(state,key))
        else:
            area.button(group,key=key+"_button",use_container_width=True,
                        type="primary" if active in members and not state.get(SERVICE_KEY) else "secondary",
                        on_click=select_page,args=(state,members[0]))
    return state[NAVIGATION_KEY]

def _group_changed(state,key):
    page=state.get(key)
    if page is not None:select_page(state,page)

def render_service(st,area,render_memory):
    """A deliberate route, not a collapsed diagnostics tree rendered on every run."""
    state=st.session_state
    def toggle():
        state[SERVICE_KEY]=not state.get(SERVICE_KEY,False)
    area.button("Service & Diagnostics",key="_r219_service_button",on_click=toggle,
                use_container_width=True,type="secondary")
    if not state.get(SERVICE_KEY,False):return False
    st.header("Service & Diagnostics")
    st.button("Back to analysis",key="_r219_service_back",on_click=toggle)
    from .runtime_identity import RUNTIME_BUILD_ID
    from .release_info import TOOL_VERSION
    st.caption(f"Climate Analyzer {TOOL_VERSION} · runtime {RUNTIME_BUILD_ID[:12]}")
    render_memory(st)
    return True

FILTER_STORE="_r219_filter_preferences"
FILTER_KEYS=("global_data_range_mode","global_data_range_year","global_data_range_start_date",
             "global_data_range_end_date","global_data_range_start_time","global_data_range_end_time",
             "global_time_basis","global_months_hourly_source","global_hours_hourly_source",
             "global_months_monthly_source","historical_analysis_clock","historical_quality_policy",
             "historical_timeseries_resolution","historical_native_derived")

def reset_filters(state):
    for key in FILTER_KEYS:state.pop(key,None)
    state.pop(FILTER_STORE,None)

def restore_filters(state,source_start=None,source_end=None,years=()):
    # Historical clock/quality controls are read before the canonical frame is
    # built. Date-dependent controls are restored only once its bounds exist.
    for key in FILTER_KEYS:
        if source_start is None and not key.startswith("historical_"):continue
        value=state.get(key,state.get(FILTER_STORE,{}).get(key))
        if value is None:continue
        invalid=(key=="global_data_range_year" and bool(years) and value not in years)
        if key.endswith("_date") and source_start is not None:
            invalid=not source_start.date()<=value<=source_end.date()
        if invalid:state.pop(key,None)
        elif key not in state:state[key]=value

def remember_filters(state):
    saved=dict(state.get(FILTER_STORE,{}))
    saved.update({key:state[key] for key in FILTER_KEYS if key in state})
    state[FILTER_STORE]=saved

def filter_panel(st,area=None):
    area=area if area is not None else st.sidebar
    panel=area.expander("Data filters",expanded=False)
    panel.button("Reset filters",key="_r219_reset_filters",on_click=reset_filters,args=(st.session_state,))
    return panel

def filter_summary(panel,spec):
    if not isinstance(spec,dict):return
    mode=spec.get("range_mode","All available")
    if mode=="Year":mode=str(spec.get("year",mode))
    if mode=="Custom":mode=f"{spec.get('start','')} → {spec.get('end','')}"
    months=spec.get("months",())
    hours=spec.get("hours")
    text=f"{mode} · {'All months' if len(months)==12 else str(len(months))+' months'}"
    if hours:text+=f" · {min(hours):02d}–{max(hours):02d} h"
    panel.caption(text)

def pressure_selection(st,page,modes,*,source,default=0,mode_key=None,custom_key=None,help=None):
    """Keep the physical pressure preference persistent across page changes."""
    state=st.session_state
    store=dict(state.get(PRESSURE_STATE,{}))
    mode_key=mode_key or "_r219_"+source+"_pressure_mode"
    custom_key=custom_key or "_r219_"+source+"_custom_pressure"
    mode,custom=store.get(source,(state.get(mode_key,modes[default]),state.get(custom_key,101325.)))
    if mode not in modes:mode=modes[default]
    if page=="Humidity and Psychrometrics":
        with st.expander("Psychrometric pressure",expanded=False):
            if mode_key not in state or state[mode_key] not in modes:state[mode_key]=mode
            mode=st.selectbox("Psychrometric pressure mode",modes,key=mode_key,help=help)
            if mode=="Custom constant pressure":
                if custom_key not in state:state[custom_key]=float(custom)
                custom=st.number_input("Custom pressure [Pa]",min_value=30000.,max_value=120000.,
                                       step=100.,key=custom_key)
            st.caption("Applies to psychrometric derivation for this climate source, including dependent design analyses.")
    store[source]=(mode,custom)
    state[PRESSURE_STATE]=store
    return mode,custom if mode=="Custom constant pressure" else None
