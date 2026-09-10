from pathlib import Path

app_path = Path("tools/climate_analyzer/app.py")
source = app_path.read_text(encoding="utf-8")
needle = 'st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")\n\n\n@st.cache_data(show_spinner=True)\n'
replacement = '''st.set_page_config(page_title=APP_BROWSER_TITLE, layout="wide", page_icon="🌦️")\n\n# Streamlit 1.63 renders the file-uploader size/type hint with a 0.6-alpha\n# foreground color that fails WCAG AA contrast on the default light background.\n# Inherit the surrounding instruction color through a stable Streamlit test id;\n# do not bind this override to generated Emotion class names.\nst.markdown(\n    """\n    <style>\n    [data-testid="stFileUploaderDropzoneInstructions"] span {\n        color: inherit !important;\n    }\n    </style>\n    """,\n    unsafe_allow_html=True,\n)\n\n\n@st.cache_data(show_spinner=True)\n'''
if source.count(needle) != 1:
    raise SystemExit(f"Expected exactly one page-config insertion point, found {source.count(needle)}")
app_path.write_text(source.replace(needle, replacement, 1), encoding="utf-8")
print("WEB_0_9_1_PATCH_APPLIED=PASS")
