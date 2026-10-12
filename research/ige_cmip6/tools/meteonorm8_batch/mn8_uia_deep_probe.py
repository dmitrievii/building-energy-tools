#!/usr/bin/env python3
"""Read-only, scope-limited Meteonorm 8.2 WPF UIA deep inspection.

Never invokes, expands or clicks controls. Never reads Edit/Password values.
Only inspect Data/Format/Output expander subtrees; no location or licensing panes.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

TARGET_IDS = ("DataExpander", "FormatExpander", "OutputExpander")
SENSITIVE_TERMS = ("license", "licence", "serial", "activation", "password",
                   "product key", "api key", "token", "credential", "username")
HIDDEN_TYPES = ("Edit", "Password", "Document")
CONTROL_LIMIT = 2800
BRANCH_LIMIT = 180

def allowed_name(control_type, raw_name):
    if control_type in HIDDEN_TYPES:
        return "[redacted input]"
    s = str(raw_name or "")[:150]
    if any(term in s.casefold() for term in SENSITIVE_TERMS):
        return "[redacted label]"
    return s

def find_target_nodes(root, max_depth=6):
    """Locate the named WPF Expander wrappers without interacting with them."""
    queue = [(root, 0)]
    found = {}
    while queue:
        node, depth = queue.pop(0)
        try:
            name = str(node.element_info.automation_id or "")
            if name in TARGET_IDS and name not in found:
                found[name] = node
        except Exception:
            pass
        if depth >= max_depth:
            continue
        try:
            queue.extend((child, depth + 1) for child in node.children()[:BRANCH_LIMIT])
        except Exception:
            pass
    return found

def inspect_subtree(root, relative_max_depth=7, max_nodes=CONTROL_LIMIT):
    """Describe the controls, including children inside WPF GroupBox (depth 6+)."""
    budget = {"nodes": 0, "truncated": False}
    def walk(node, depth):
        if budget["nodes"] >= max_nodes:
            budget["truncated"] = True
            return None
        budget["nodes"] += 1
        description = {"depth": depth}
        try:
            info = node.element_info
            typ = str(info.control_type or "")
            description.update(control_type=typ,
                               automation_id=str(info.automation_id or "")[:160],
                               class_name=str(info.class_name or "")[:160],
                               name=allowed_name(typ, info.name))
            try:
                description["enabled"] = bool(node.is_enabled())
            except Exception:
                pass
        except Exception as exc:
            description["inspection_error"] = type(exc).__name__
            return description
        if depth >= relative_max_depth or budget["truncated"]:
            return description
        try:
            children = node.children()[:BRANCH_LIMIT]
        except Exception as exc:
            description["children_error"] = type(exc).__name__
            return description
        nested = [x for x in (walk(c, depth + 1) for c in children) if x is not None]
        if nested:
            description["children"] = nested
        return description
    tree = walk(root, 0)
    return tree, budget

def capture(view, output, max_depth=7):
    try:
        from pywinauto import Desktop
    except ImportError as exc:
        raise RuntimeError("Install with: py -3 -m pip install --user pywinauto comtypes pywin32") from exc
    windows = [w for w in Desktop(backend="uia").windows()
               if "meteonorm" in w.window_text().casefold()]
    if not windows:
        raise RuntimeError("Meteonorm 8.2 must be open; no matching window found")
    scope = ("DataExpander",) if view in ("future", "advanced") else (
        ("FormatExpander",) if view == "format" else ("OutputExpander",))
    snapshots = []
    for window in windows[:2]:
        groups = find_target_nodes(window)
        entry = {"window_title": "Meteonorm 8.x", "requested": list(scope), "found": [],
                 "not_found": [], "control_trees": {}}
        for ident in scope:
            if ident not in groups:
                entry["not_found"].append(ident)
                continue
            subtree, quota = inspect_subtree(groups[ident], relative_max_depth=max_depth)
            entry["found"].append(ident)
            entry["control_trees"][ident] = {"tree": subtree, "limits": quota}
        snapshots.append(entry)
    out = {"stage": "IGE_P8_MN8_UIA_DEEP_V02", "diagnostic_only": True,
           "no_gui_interaction": True, "no_edit_or_password_values": True,
           "requested_view": view, "max_relative_depth": max_depth,
           "windows": snapshots}
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Saved read-only, redacted UIA report:", path)
    print("Targets found:", [w["found"] for w in snapshots])
    print("No buttons were clicked; no Edit/Password values were read.")
    return 0 if any(x["found"] for x in snapshots) else 2

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--view", choices=("future", "advanced", "format", "output"),
                        required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--max-depth", type=int, default=7)
    args = parser.parse_args()
    if not (6 <= args.max_depth <= 9):
        parser.error("--max-depth must be 6..9")
    return capture(args.view, args.out, args.max_depth)

if __name__ == "__main__":
    raise SystemExit(main())
