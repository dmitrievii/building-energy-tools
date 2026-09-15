from pathlib import Path
import re

APP = Path(__file__).resolve().parent / "app.py"
text = APP.read_text(encoding="utf-8")

fn_start = text.index("def render_temperature(")
fn_end = text.index("\ndef render_humidity(", fn_start)
block = text[fn_start:fn_end]

controls_start = block.index("        st.caption(\n", block.index('if chart_group == "Degree days":'))
controls_end = block.index("        method_col, aggregation_col = st.columns(2)", controls_start)
new_controls = '''        st.caption(
            "HGT/KGT use two independent temperatures each: the limit selects the heating/cooling period, "
            "while the temperature difference is measured to the corresponding indoor-air reference."
        )
        st.markdown("**Heating degree metric (HGT)**")
        heat_col1, heat_col2 = st.columns(2)
        heating_indoor = heat_col1.slider(
            "Heating indoor air temperature [°C]",
            10.0,
            30.0,
            20.0,
            0.5,
            key="degree_heating_indoor_c",
            help="Indoor-air reference used for the HGT temperature difference.",
        )
        heating_limit = heat_col2.slider(
            "Heating limit [°C]",
            -5.0,
            25.0,
            12.0,
            0.5,
            key="degree_heating_limit_c",
            help="Only intervals/days with mean outdoor temperature below this limit contribute to HGT.",
        )
        if heating_limit > heating_indoor:
            st.error("Heating limit must not exceed heating indoor air temperature.")
            return

        st.markdown("**Cooling degree metric (KGT)**")
        cool_col1, cool_col2 = st.columns(2)
        cooling_indoor = cool_col1.slider(
            "Cooling indoor air temperature [°C]",
            10.0,
            30.0,
            20.0,
            0.5,
            key="degree_cooling_indoor_c",
            help="Indoor-air reference used for the KGT temperature difference.",
        )
        cooling_limit = cool_col2.slider(
            "Cooling limit [°C]",
            10.0,
            35.0,
            18.3,
            0.1,
            key="degree_cooling_limit_c",
            help="Only intervals/days with mean outdoor temperature above this limit contribute to KGT.",
        )
        st.caption(
            f"Current definitions: HGT {heating_indoor:g}/{heating_limit:g} and "
            f"KGT {cooling_indoor:g}/{cooling_limit:g}."
        )

'''
block = block[:controls_start] + new_controls + block[controls_end:]

pattern = re.compile(
    r"(?P<indent>^[ \t]*)heating_base_c=heat_threshold,\n(?P=indent)cooling_base_c=cool_threshold,",
    flags=re.MULTILINE,
)

def replace_args(match: re.Match[str]) -> str:
    indent = match.group("indent")
    return (
        f"{indent}heating_indoor_c=heating_indoor,\n"
        f"{indent}heating_limit_c=heating_limit,\n"
        f"{indent}cooling_indoor_c=cooling_indoor,\n"
        f"{indent}cooling_limit_c=cooling_limit,"
    )

block, argument_replacements = pattern.subn(replace_args, block)
if argument_replacements != 2:
    raise SystemExit(f"Expected two old degree-metric argument blocks, found {argument_replacements}")

old_title = '''                f"{aggregation} heating and cooling {metric.lower()} "\n                f"(bases {heat_threshold:g}/{cool_threshold:g} °C)"\n'''
new_title = '''                f"{aggregation} heating and cooling {metric.lower()} "\n                f"(HGT {heating_indoor:g}/{heating_limit:g}; KGT {cooling_indoor:g}/{cooling_limit:g})"\n'''
if old_title not in block:
    raise SystemExit("Old degree-metric title block not found")
block = block.replace(old_title, new_title, 1)

old_note = '''            "Degree-hours use every source interval and preserve its native duration; "\n            "Degree-days use daily mean outdoor temperature before applying the heating/cooling base. "\n            "Heating and cooling bars are grouped because they are separate indicators, not additive components of one total."\n'''
new_note = '''            "Degree-hours evaluate the limit and indoor-reference difference at every native source interval. "\n            "Degree-days first form daily mean outdoor temperature and then apply the same HGT/KGT selection rules. "\n            "Heating and cooling bars are grouped because HGT and KGT are separate indicators, not additive components of one total."\n'''
if old_note in block:
    block = block.replace(old_note, new_note, 1)

text = text[:fn_start] + block + text[fn_end:]
APP.write_text(text, encoding="utf-8")
print("CLIMATE-0.10.11 four-input HGT/KGT UI patch applied")
