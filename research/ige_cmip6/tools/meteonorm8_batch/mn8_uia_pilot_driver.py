#!/usr/bin/env python3
"""IGE P8 Meteonorm 8.2 UIA single-batch guarded pilot.

Operates only licensed, already-running Meteonorm; no undocumented APIs.
Default preflight is read-only. --execute changes settings and prepares export.
--save deliberately invokes Save All once, then leaves any dialog to the user.
Output completeness and provenance must be verified separately using
mn8_batch_controller.py verify. Never publish licensed EPW to GitHub.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_TITLE = "meteonorm"
SCENARIOS = {
    "contemporary": (None, None),
    "rcp45_2050": ("RCP 4.5", "2050"),
    "rcp85_2050": ("RCP 8.5", "2050"),
    "rcp85_2100": ("RCP 8.5", "2100"),
}
REQUIRED_IDS = {
    "period_future": "PeriodFuture",
    "period_contemporary": "PeriodContemporary",
    "year": "futureTimePeriod",
    "seed": "randomSeedBox",
    "epw_format": "outputFormat_22",
    "save_all": "SaveAllResultsButton",
}

class PilotError(RuntimeError):
    pass

def children(node):
    try:
        return node.children()
    except Exception:
        return []

def info(node, attr):
    try:
        return str(getattr(node.element_info, attr, "") or "")
    except Exception:
        return ""

def locate(root, *, aid=None, name=None, typ=None, max_depth=9, limit=3000):
    queue = [(root, 0)]
    seen = 0
    while queue:
        node, depth = queue.pop(0)
        seen += 1
        if seen > limit:
            raise PilotError("UIA node limit exceeded; refusing broad uncontrolled search")
        if ((aid is None or info(node, "automation_id") == aid) and
            (name is None or info(node, "name") == name) and
            (typ is None or info(node, "control_type") == typ)):
            return node
        if depth < max_depth:
            queue.extend((child, depth + 1) for child in children(node)[:250])
    return None

def required(root, **kwargs):
    result = locate(root, **kwargs)
    if result is None:
        raise PilotError("Required Meteonorm UIA control not found: " + str(kwargs))
    try:
        if not result.is_enabled():
            raise PilotError("Required control is disabled: " + str(kwargs))
    except (AttributeError, TypeError):
        pass
    return result

def opened_meteonorm():
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise PilotError("Install Windows support: py -3 -m pip install --user pywinauto comtypes pywin32") from exc
    windows = [w for w in Desktop(backend="uia").windows()
               if EXPECTED_TITLE in w.window_text().casefold()]
    if not windows:
        raise PilotError("Meteonorm 8.2 is not open")
    for window in windows:
        if locate(window, aid="MainAccordion", max_depth=5):
            return window
    raise PilotError("No Meteonorm main accordion found")

def panel(window, aid):
    return required(window, aid=aid, max_depth=8)

def selected_radio(radio):
    try:
        return bool(radio.iface_selection_item.CurrentIsSelected)
    except Exception:
        pass
    try:
        return int(radio.iface_toggle.CurrentToggleState) == 1
    except Exception:
        return None

def checked_choice(parent, name):
    choice = required(parent, typ="RadioButton", name=name, max_depth=5)
    return selected_radio(choice)

def select_radio(radio):
    if selected_radio(radio) is True:
        return
    try:
        radio.iface_selection_item.Select()
    except Exception:
        try:
            radio.select()
        except Exception as exc:
            raise PilotError("UIA SelectionItem failed: " + str(exc)) from exc
    if selected_radio(radio) is not True:
        raise PilotError("RadioButton state could not be verified after select: " + info(radio, "name"))

def selected_combo(combo):
    try:
        value = combo.selected_text()
        if value is not None:
            return str(value).strip()
    except Exception:
        pass
    try:
        selected = combo.iface_selection.GetCurrentSelection()
        if selected:
            return str(selected[0].CurrentName).strip()
    except Exception:
        pass
    try:
        value = str(combo.iface_value.CurrentValue).strip()
        if value:
            return value
    except Exception:
        pass
    for child in children(combo):
        if info(child, "control_type") == "ListItem" and selected_radio(child) is True:
            return info(child, "name").strip()
    return None

def combo_options(combo):
    try:
        values = [str(x).strip() for x in combo.item_texts()]
        if values:
            return values
    except Exception:
        pass
    return [info(c, "name") for c in children(combo)
            if info(c, "control_type") == "ListItem"]

def select_combo(combo, target, *, seed_number=None):
    before = selected_combo(combo)
    if before == target:
        return {"before": before, "after": before, "changed": False}
    options = combo_options(combo)
    try:
        if target in options:
            combo.select(target)
        elif seed_number is not None and len(options) >= seed_number:
            combo.select(seed_number - 1)
        elif seed_number is not None and not options:
            # A collapsed WPF ComboBox may not expose options until expanded.
            combo.expand()
            expanded = combo_options(combo)
            if str(target) in expanded:
                combo.select(str(target))
            elif len(expanded) >= seed_number:
                combo.select(seed_number - 1)
            else:
                raise PilotError("Seed ComboBox items are not exposed: " + str(expanded[:15]))
        else:
            raise PilotError("Required ComboBox value missing: " + repr(target) +
                             "; options=" + str(options[:20]))
    except PilotError:
        raise
    except Exception as exc:
        raise PilotError("ComboBox selection failed for " + repr(target) + ": " + str(exc)) from exc
    after = selected_combo(combo)
    if after is None:
        raise PilotError("ComboBox selected value not independently readable after change: " +
                         info(combo, "automation_id"))
    if target != after and not (seed_number is not None and
         re.search(r"(?<!\d)" + re.escape(str(seed_number)) + r"(?!\d)", after)):
        raise PilotError("ComboBox failed selection check: expected " +
                         repr(target) + ", got " + repr(after))
    return {"before": before, "after": after, "changed": before != after}

def invoke(control):
    try:
        control.iface_invoke.Invoke()
    except Exception:
        try:
            control.click_input()
        except Exception as exc:
            raise PilotError("Cannot invoke identified control " +
                             info(control, "automation_id") + ": " + str(exc)) from exc

def next_section(current):
    options = [x for x in children(current) if info(x, "class_name") == "NextButton"]
    if len(options) != 1:
        raise PilotError("NextButton ambiguous or missing in current section")
    btn = required(options[0], typ="Button", max_depth=2)
    invoke(btn)

def location_count(window):
    loc = locate(window, aid="LocationsExpander", max_depth=8)
    if loc is None:
        return None
    counter = locate(loc, aid="LocationsCount", max_depth=4)
    if counter is None:
        return None
    val = info(counter, "name")
    return int(val) if val.isdigit() else None

def selected_site_names(window):
    loc = locate(window, aid="LocationsExpander", max_depth=8)
    if loc is None:
        return []
    box = locate(loc, aid="SelectedLocationsBox", max_depth=5)
    if box is None:
        return []
    result = []
    for item in children(box):
        # WPF ListItem usually exposes station names directly.
        name = info(item, "name").strip()
        if name.startswith("IGE_"):
            result.append(name)
        else:
            for child in children(item):
                candidate = info(child, "name").strip()
                if candidate.startswith("IGE_"):
                    result.append(candidate)
                    break
    return result

def expected_sites(project):
    path = Path(project) / "project_config.json"
    if not path.exists():
        raise PilotError("Missing project_config.json; run 01_prepare_batches.bat first")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [x["name"] for x in payload["sites"]]

def validate_site_names(window, project):
    expected = expected_sites(project)
    actual = selected_site_names(window)
    if len(actual) != len(expected) or sorted(actual) != sorted(expected):
        raise PilotError("Selected station identities could not be verified for Save All. "
                         "Expected "+repr(expected)+"; UIA found "+repr(actual)+". "
                         "Return to Locations and import/select the IGE sites.")
    return actual

def _save_report(path, payload):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

def collect_preflight(window):
    data = locate(window, aid="DataExpander", max_depth=8)
    fmt = locate(window, aid="FormatExpander", max_depth=8)
    out = locate(window, aid="OutputExpander", max_depth=8)
    result = {"selected_location_count": location_count(window),
              "selected_ige_site_names": selected_site_names(window),
              "present": {"data": data is not None, "format": fmt is not None,
                          "output": out is not None}}
    if data:
        scenario_group = locate(data, typ="Group", name="Scenario for future periods", max_depth=3)
        result["future_period"] = (selected_combo(locate(data, aid="futureTimePeriod", max_depth=3))
                                   if locate(data, aid="futureTimePeriod", max_depth=3) else None)
        result["rcp"] = ({c: checked_choice(scenario_group,c) for c in
                          ("RCP 2.6", "RCP 4.5", "RCP 8.5")}
                          if scenario_group else None)
        seed = locate(data, aid="randomSeedBox", max_depth=3)
        result["seed"] = selected_combo(seed) if seed else None
        result["seed_options"] = combo_options(seed) if seed else None
        period = locate(data, typ="Group", name="Period", max_depth=3)
        result["period"] = ({c: checked_choice(period,c) for c in
                            ("Contemporary", "Future")} if period else None)
    if fmt:
        epw = locate(fmt, aid="outputFormat_22", max_depth=4)
        result["epw_selected"] = selected_radio(epw) if epw else None
    if out:
        result["save_available"] = bool(locate(out, aid="SaveAllResultsButton", max_depth=3))
    return result

def run(scenario, seed, mode, expected_locations, report, project):
    if scenario not in SCENARIOS:
        raise PilotError("Unknown scenario: " + scenario)
    if not 1 <= seed <= 10:
        raise PilotError("Seed out of Meteonorm 8 range 1..10")
    app = opened_meteonorm()
    audit = {"stage": "IGE_P8_MN8_UIA_GUARDED_PILOT_V03",
             "time_utc": datetime.now(timezone.utc).isoformat(),
             "mode": mode, "scenario": scenario, "seed": seed,
             "expected_location_count": expected_locations,
             "mutations": [], "export_clicked": False, "complete": False}
    try:
        audit["preflight"] = collect_preflight(app)
        if mode == "inspect":
            audit["complete"] = True
            return audit
        n = location_count(app)
        if n is None:
            raise PilotError("Selected locations count not readable; open Locations panel first")
        if n != expected_locations:
            raise PilotError("Selected locations " + str(n) +
                             " != expected " + str(expected_locations) +
                             "; check batch import before continuing")
        data = panel(app, "DataExpander")
        period = required(data, typ="Group", name="Period", max_depth=3)
        year, rcp = None, None
        if scenario == "contemporary":
            select_radio(required(period, aid="PeriodContemporary", max_depth=3))
            audit["mutations"].append("period=Contemporary")
        else:
            select_radio(required(period, aid="PeriodFuture", max_depth=3))
            audit["mutations"].append("period=Future")
            rcp, year = SCENARIOS[scenario]
            group = required(data, typ="Group", name="Scenario for future periods", max_depth=3)
            select_radio(required(group, typ="RadioButton", name=rcp, max_depth=3))
            audit["mutations"].append("scenario="+rcp)
            select_combo(required(data, aid="futureTimePeriod", max_depth=3), year)
            audit["mutations"].append("year="+year)
        seed_box = locate(data, aid="randomSeedBox", max_depth=3)
        if seed_box is None:
            raise PilotError("Advanced settings must be expanded; randomSeedBox not found")
        changed = select_combo(seed_box, str(seed), seed_number=seed)
        audit["mutations"].append("seed="+str(changed["after"]))
        check = collect_preflight(app)
        if check["period"][("Contemporary" if rcp is None else "Future")] is not True:
            raise PilotError("Period state verification failed")
        if rcp is not None and (check["rcp"][rcp] is not True or check["future_period"] != year):
            raise PilotError("RCP/year state verification failed")
        if mode == "configure":
            audit["complete"] = True
            audit["configured"] = check
            return audit
        next_section(data)
        fmt = panel(app, "FormatExpander")
        select_radio(required(fmt, aid="outputFormat_22", max_depth=4))
        audit["mutations"].append("format=EnergyPlus(.epw)")
        if selected_radio(required(fmt, aid="outputFormat_22", max_depth=4)) is not True:
            raise PilotError("EPW format state verification failed")
        next_section(fmt)
        out = panel(app, "OutputExpander")
        saved = required(out, aid="SaveAllResultsButton", max_depth=3)
        audit["output_ready"] = True
        if mode == "save":
            audit["verified_site_names"] = validate_site_names(app, project)
            invoke(saved)
            audit["export_clicked"] = True
            audit["requires_manual_dialog_validation"] = True
        audit["complete"] = True
        return audit
    except Exception as exc:
        audit["error_type"] = type(exc).__name__
        audit["error"] = str(exc)[:750]
        raise
    finally:
        _save_report(report, audit)

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--scenario", choices=tuple(SCENARIOS), default="rcp45_2050")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--mode", choices=("inspect", "configure", "prepare", "save"), default="inspect")
    p.add_argument("--expected-locations", type=int, default=5)
    p.add_argument("--project", default="mn8_project")
    p.add_argument("--report", default="mn8_project/uia_pilot_v03.json")
    a = p.parse_args(argv)
    try:
        result = run(a.scenario, a.seed, a.mode, a.expected_locations, a.report,a.project)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (PilotError, OSError, ValueError) as exc:
        print("P8 PILOT REFUSED:", str(exc), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
