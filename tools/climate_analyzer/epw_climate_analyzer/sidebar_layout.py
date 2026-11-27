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
    ("Explore",("Time Series and Overlay","Compare Climates","Data Quality")),
    ("Design",("Natural Ventilation","Shading analysis","HVAC and Passive Design","Outdoor Thermal Comfort")),
    ("Report",("Report",)),
)
SERVICE_KEY="_r219_service_open"
PRESSURE_STATE="_r219_pressure_preferences"
OPEN_GROUPS="_r219_open_navigation_groups"
LAST_PAGE="_r219_last_navigation_page"
EXPANDABLE=("Climate","Design","Explore")

def grouped_pages(pages):
    available=set(pages)
    return tuple((label,tuple(p for p in members if p in available))
                 for label,members in GROUPS if available.intersection(members))

# Native Material Symbols, not platform-dependent coloured emoji.
ICONS={
    "Climate source":"location_on","Overview":"dashboard","Climate":"partly_cloudy_day",
    "Explore":"explore","Design":"architecture","Report":"description",
    "Temperature":"thermostat","Humidity and Psychrometrics":"humidity_percentage",
    "Solar and Radiation":"wb_sunny","Wind and Ventilation":"air",
    "Sky and Daylight":"partly_cloudy_day","Precipitation and Snow":"rainy",
    "Time Series and Overlay":"show_chart","Compare Climates":"compare_arrows",
    "Data Quality":"database","Natural Ventilation":"air","Shading analysis":"wb_twilight",
    "HVAC and Passive Design":"home","Outdoor Thermal Comfort":"device_thermostat",
}
LABELS={"Humidity and Psychrometrics":"Humidity & psychrometrics",
        "Compare Climates":"Compare climates","Data Quality":"Data quality",
        "Shading analysis":"Shading","HVAC and Passive Design":"Passive design & HVAC"}

def short_label(page):
    return LABELS.get(page,NAVIGATION_LABELS.get(page,page).split(" — ",1)[-1])

def page_button_key(page):
    return "_r220_page_"+page.replace(" ","_")

NAV_CSS="""<style>
section[data-testid="stSidebar"] .st-key-_r220_navigation_tree,
section[data-testid="stSidebar"] .st-key-_r220_navigation_tree [data-testid="stVerticalBlock"] {
    gap:.15rem!important;
}
section[data-testid="stSidebar"] [class*="st-key-_r219_group_"] button,
section[data-testid="stSidebar"] [class*="st-key-_r219_nav_"] button,
section[data-testid="stSidebar"] [class*="st-key-_r220_page_"] button,
section[data-testid="stSidebar"] .st-key-_r219_service_button button {
    justify-content:flex-start; text-align:left; min-height:2rem;
    padding:.3rem .55rem; border:0!important; box-shadow:none!important;
    color:inherit!important; border-radius:.35rem; background:transparent!important;
    font-weight:400;
}
section[data-testid="stSidebar"] [class*="st-key-_r220_page_"] button {
    padding-left:1.55rem; font-size:.92rem;
}
section[data-testid="stSidebar"] [class*="st-key-_r219_group_"] button {
    font-weight:550;
}
section[data-testid="stSidebar"] .st-key-_r220_page_Temperature [data-testid="stIconMaterial"],
section[data-testid="stSidebar"] .st-key-_r220_page_Solar_and_Radiation [data-testid="stIconMaterial"] {color:#D97706}
section[data-testid="stSidebar"] .st-key-_r220_page_Humidity_and_Psychrometrics [data-testid="stIconMaterial"] {color:#0891B2}
section[data-testid="stSidebar"] .st-key-_r220_page_Precipitation_and_Snow [data-testid="stIconMaterial"] {color:#2563EB}
section[data-testid="stSidebar"] .st-key-_r220_page_Wind_and_Ventilation [data-testid="stIconMaterial"],
section[data-testid="stSidebar"] .st-key-_r220_page_Natural_Ventilation [data-testid="stIconMaterial"] {color:#059669}
section[data-testid="stSidebar"] [class*="st-key-_r219_group_"] button[data-testid="stBaseButton-primary"],
section[data-testid="stSidebar"] [class*="st-key-_r219_nav_"] button[data-testid="stBaseButton-primary"],
section[data-testid="stSidebar"] [class*="st-key-_r220_page_"] button[data-testid="stBaseButton-primary"] {
    background:color-mix(in srgb,currentColor 9%,transparent)!important;
    font-weight:600;
}
section[data-testid="stSidebar"] [class*="st-key-_r219_group_"] button:hover,
section[data-testid="stSidebar"] [class*="st-key-_r219_nav_"] button:hover,
section[data-testid="stSidebar"] [class*="st-key-_r220_page_"] button:hover,
section[data-testid="stSidebar"] .st-key-_r219_service_button button:hover {
    background:color-mix(in srgb,currentColor 6%,transparent)!important;
}
section[data-testid="stSidebar"] [class*="st-key-_r219_group_"] button:focus-visible,
section[data-testid="stSidebar"] [class*="st-key-_r219_nav_"] button:focus-visible,
section[data-testid="stSidebar"] [class*="st-key-_r220_page_"] button:focus-visible,
section[data-testid="stSidebar"] .st-key-_r219_service_button button:focus-visible {
    outline:2px solid currentColor!important; outline-offset:1px;
}
</style>"""

def render_nav_style(st):
    st.html(NAV_CSS)

def _nav_row(area,label,key,icon,selected,on_click,args):
    area.button(label,key=key,icon=f":material/{icon}:",use_container_width=True,
                type="primary" if selected else "tertiary",on_click=on_click,args=args)

def select_page(state,page):
    state[NAVIGATION_KEY]=page
    state[SERVICE_KEY]=False

def sync_open_groups(state,active,groups):
    """Own expansion on the server, not in a transient frontend details node.

    A route transition opens its containing group exactly once. An explicit
    user collapse stays collapsed on all ordinary analysis/widget reruns.
    """
    eligible=tuple(group for group,_ in groups if group in EXPANDABLE)
    opened=set(state.get(OPEN_GROUPS,())).intersection(eligible)
    if state.get(LAST_PAGE)!=active:
        opened.update(group for group,members in groups if group in EXPANDABLE and active in members)
    state[OPEN_GROUPS]=tuple(group for group in eligible if group in opened)
    state[LAST_PAGE]=active

def toggle_group(state,group):
    opened=set(state.get(OPEN_GROUPS,()))
    if group in opened:opened.remove(group)
    else:opened.add(group)
    state[OPEN_GROUPS]=tuple(g for g in EXPANDABLE if g in opened)

def render_navigation(st,pages,area=None):
    """Persistent server-owned group toggles and canonical page selection."""
    area=area if area is not None else st.sidebar
    state=st.session_state
    pages=tuple(pages)
    if not pages:return None
    if state.get(NAVIGATION_KEY) not in pages:
        state[NAVIGATION_KEY]="Overview" if "Overview" in pages else pages[0]
    active=state[NAVIGATION_KEY]
    state["_r219_available_pages"]=pages
    groups=grouped_pages(pages)
    sync_open_groups(state,active,groups)
    tree=area.container(key="_r220_navigation_tree")
    for group,members in groups:
        key="_r219_nav_"+group.replace(" ","_")
        selected=active in members and not state.get(SERVICE_KEY)
        if group in EXPANDABLE:
            opened=group in state[OPEN_GROUPS]
            _nav_row(tree,group+(" ▾" if opened else " ▸"),"_r219_group_"+group,
                     ICONS[group],selected and not opened,toggle_group,(state,group))
            if opened:
                for page in members:
                    _nav_row(tree,short_label(page),page_button_key(page),ICONS[page],
                             active==page and not state.get(SERVICE_KEY),select_page,(state,page))
        else:
            _nav_row(tree,group,key+"_button",ICONS[group],selected,select_page,(state,members[0]))
    return state[NAVIGATION_KEY]


def render_service(st,area,render_memory):
    """A deliberate route, not a collapsed diagnostics tree rendered on every run."""
    state=st.session_state
    def toggle():
        state[SERVICE_KEY]=not state.get(SERVICE_KEY,False)
    area.button("Service & Diagnostics",key="_r219_service_button",icon=":material/build:",on_click=toggle,
                use_container_width=True,type="tertiary")
    if not state.get(SERVICE_KEY,False):return False
    st.header("Service & Diagnostics")
    st.button("Back to analysis",key="_r219_service_back",on_click=toggle)
    from .runtime_identity import RUNTIME_BUILD_ID
    from .ui_contract import APP_RELEASE_LABEL
    st.caption(f"{APP_RELEASE_LABEL} · runtime {RUNTIME_BUILD_ID[:12]}")
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
    panel=area.expander("Data filters",expanded=False,icon=":material/calendar_month:")
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
