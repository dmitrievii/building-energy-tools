from pathlib import Path

path = Path("tools/climate_analyzer/app.py")
text = path.read_text(encoding="utf-8")


def replace_once(old: str, new: str, label: str) -> None:
    global text
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    text = text.replace(old, new, 1)


replace_once(
    '''    NAVIGATION_PAGES,
    navigation_label,
)''',
    '''    NAVIGATION_KEY,
    NAVIGATION_PAGES,
    apply_queued_navigation,
    navigation_label,
    queue_navigation,
    queue_navigation_reset,
)''',
    "navigation imports",
)
replace_once(
    '''NAVIGATION_KEY = "climate_analyzer_navigation"
st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")''',
    '''st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")''',
    "local navigation constant",
)
replace_once(
    '''    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    st.session_state[NAVIGATION_KEY] = "Overview"''',
    '''    st.session_state["active_climate_file"] = ClimateFilePayload(name=name, payload=payload, source=source)
    queue_navigation(st.session_state, "Overview")''',
    "activate queued navigation",
)
replace_once(
    '''    st.session_state.pop("active_climate_file", None)
    st.session_state.pop(NAVIGATION_KEY, None)''',
    '''    st.session_state.pop("active_climate_file", None)
    queue_navigation_reset(st.session_state)''',
    "clear queued navigation",
)
replace_once(
    '''    st.sidebar.caption("Building Energy Tools")
    st.sidebar.title(APP_NAME)
    active_file = get_active_climate_file()''',
    '''    st.sidebar.caption("Building Energy Tools")
    st.sidebar.title(APP_NAME)
    apply_queued_navigation(st.session_state)
    active_file = get_active_climate_file()''',
    "apply queued navigation before widget",
)

path.write_text(text, encoding="utf-8")
print("WEB-0.6 navigation state fix PASS")
