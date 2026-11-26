"""Drive the actual R2.19 grouped widgets in public Streamlit route tests."""
from epw_climate_analyzer.sidebar_layout import GROUPS,EXPANDABLE
from epw_climate_analyzer.ui_contract import NAVIGATION_KEY

def navigate_app(app,page):
    """Preserve the old acceptance tests' user-driven navigation semantics."""
    for group,members in GROUPS:
        if page not in members:
            continue
        key="_r219_nav_"+group.replace(" ","_")
        if group in EXPANDABLE:
            if not any(r.key==key for r in app.sidebar.radio):
                app.sidebar.button(key="_r219_group_"+group).click().run()
            app.sidebar.radio(key=key).set_value(page).run()
        else:
            app.sidebar.button(key=key+"_button").click().run()
        if app.session_state[NAVIGATION_KEY]!=page:
            raise AssertionError(f"Navigation did not select {page!r}")
        return app
    raise AssertionError(f"Unregistered analysis page {page!r}")
