from __future__ import annotations

import json
import os
import resource
import signal
import subprocess
import sys
import time
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TOOL_ROOT = REPO_ROOT / "tools" / "climate_analyzer"
APP_PATH = TOOL_ROOT / "app.py"
OUTPUT_DIR = Path(os.environ.get("PERF_OUTPUT_DIR", REPO_ROOT / "artifacts" / "performance"))
if not OUTPUT_DIR.is_absolute():
    OUTPUT_DIR = REPO_ROOT / OUTPUT_DIR
OUTPUT_DIR = OUTPUT_DIR.resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

PYTHON_ENV = os.environ.copy()
PYTHON_ENV["PYTHONPATH"] = str(TOOL_ROOT) + os.pathsep + PYTHON_ENV.get("PYTHONPATH", "")


def _child_import(statement: str) -> dict[str, object]:
    code = f"""
import json
import resource
import time
started = time.perf_counter()
{statement}
elapsed = time.perf_counter() - started
print(json.dumps({{"elapsed_s": elapsed, "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=PYTHON_ENV,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stderr": completed.stderr[-4000:],
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception as exc:  # pragma: no cover - diagnostics path
        return {"ok": False, "parse_error": repr(exc), "stdout": completed.stdout[-4000:]}
    return {"ok": True, **payload}


def import_profile() -> dict[str, dict[str, object]]:
    cases = {
        "python_baseline": "pass",
        "numpy": "import numpy",
        "pandas": "import pandas",
        "plotly": "import plotly",
        "streamlit": "import streamlit",
        "folium": "import folium",
        "streamlit_folium": "import streamlit_folium",
        "pvlib": "import pvlib",
        "psychrolib": "import psychrolib",
        "openpyxl": "import openpyxl",
        "climate_sources": "import epw_climate_analyzer.climate_sources",
        "charts": "import epw_climate_analyzer.charts",
        "comparison": "import epw_climate_analyzer.comparison",
        "decisions": "import epw_climate_analyzer.decisions",
        "epw_parser": "import epw_climate_analyzer.epw_parser",
        "interpretations": "import epw_climate_analyzer.interpretations",
        "psychrometrics": "import epw_climate_analyzer.psychrometrics",
        "solar": "import epw_climate_analyzer.solar",
        "statistics": "import epw_climate_analyzer.statistics",
    }
    return {name: _child_import(statement) for name, statement in cases.items()}


def _proc_children(pid: int) -> list[int]:
    path = Path(f"/proc/{pid}/task/{pid}/children")
    try:
        return [int(value) for value in path.read_text().split()]
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return []


def _rss_kb(pid: int) -> int:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        return 0
    return 0


def _process_tree_rss_kb(root_pid: int) -> int:
    pending = [root_pid]
    seen: set[int] = set()
    total = 0
    while pending:
        pid = pending.pop()
        if pid in seen:
            continue
        seen.add(pid)
        total += _rss_kb(pid)
        pending.extend(_proc_children(pid))
    return total


def server_cold_start() -> dict[str, object]:
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP_PATH),
        "--server.headless=true",
        "--server.address=127.0.0.1",
        "--server.port=8765",
        "--browser.gatherUsageStats=false",
    ]
    log_path = OUTPUT_DIR / "streamlit-cold-start.log"
    with log_path.open("w", encoding="utf-8") as log:
        started = time.perf_counter()
        process = subprocess.Popen(
            command,
            cwd=REPO_ROOT,
            env=PYTHON_ENV,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        peak_rss_kb = 0
        healthy_at_s: float | None = None
        response_body = ""
        try:
            import urllib.request

            deadline = started + 45.0
            while time.perf_counter() < deadline:
                if process.poll() is not None:
                    break
                peak_rss_kb = max(peak_rss_kb, _process_tree_rss_kb(process.pid))
                try:
                    with urllib.request.urlopen("http://127.0.0.1:8765/_stcore/health", timeout=0.5) as response:
                        response_body = response.read(200).decode("utf-8", errors="replace")
                        if response.status == 200:
                            healthy_at_s = time.perf_counter() - started
                            break
                except Exception:
                    pass
                time.sleep(0.05)

            if healthy_at_s is not None:
                settle_deadline = time.perf_counter() + 1.0
                while time.perf_counter() < settle_deadline and process.poll() is None:
                    peak_rss_kb = max(peak_rss_kb, _process_tree_rss_kb(process.pid))
                    time.sleep(0.05)
            final_rss_kb = _process_tree_rss_kb(process.pid) if process.poll() is None else 0
        finally:
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=5)

    return {
        "ok": healthy_at_s is not None,
        "health_time_s": healthy_at_s,
        "health_body": response_body,
        "peak_tree_rss_kb": peak_rss_kb,
        "settled_tree_rss_kb": final_rss_kb,
        "returncode_after_termination": process.returncode,
        "log": str(log_path.relative_to(REPO_ROOT)),
    }


def app_test_profile() -> dict[str, object]:
    code = f"""
import json
import resource
import time
from streamlit.testing.v1 import AppTest
app = AppTest.from_file({str(APP_PATH)!r})
started = time.perf_counter()
app.run(timeout=120)
first_s = time.perf_counter() - started
first_exceptions = [str(item.value) for item in app.exception]
started = time.perf_counter()
app.run(timeout=120)
second_s = time.perf_counter() - started
second_exceptions = [str(item.value) for item in app.exception]
print(json.dumps({{
    "first_render_s": first_s,
    "second_rerun_s": second_s,
    "max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    "first_exceptions": first_exceptions,
    "second_exceptions": second_exceptions,
}}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=PYTHON_ENV,
        text=True,
        capture_output=True,
        timeout=300,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "ok": False,
            "returncode": completed.returncode,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {
            "ok": False,
            "parse_error": repr(exc),
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    return {"ok": True, **payload}


def source_footprint() -> dict[str, object]:
    python_files = list(TOOL_ROOT.rglob("*.py"))
    return {
        "python_file_count": len(python_files),
        "python_bytes": sum(path.stat().st_size for path in python_files),
        "app_bytes": APP_PATH.stat().st_size,
        "app_lines": len(APP_PATH.read_text(encoding="utf-8").splitlines()),
    }


def render_markdown(report: dict[str, object]) -> str:
    imports = report["imports"]
    import_rows = []
    for name, result in imports.items():
        if result.get("ok"):
            import_rows.append((name, float(result["elapsed_s"]), int(result["max_rss_kb"])))
    import_rows.sort(key=lambda row: row[1], reverse=True)

    lines = [
        "# Climate Analyzer runtime performance probe",
        "",
        f"Generated: `{report['generated_at']}`",
        f"Python: `{report['python']}`",
        "",
        "## Server cold start",
        "",
        "```json",
        json.dumps(report["server_cold_start"], indent=2, sort_keys=True),
        "```",
        "",
        "## Streamlit AppTest",
        "",
        "```json",
        json.dumps(report["app_test"], indent=2, sort_keys=True),
        "```",
        "",
        "## Import cost ranking",
        "",
        "| Import target | elapsed [s] | max RSS [MiB] |",
        "|---|---:|---:|",
    ]
    for name, elapsed, rss_kb in import_rows:
        lines.append(f"| `{name}` | {elapsed:.4f} | {rss_kb / 1024:.1f} |")
    lines.extend([
        "",
        "## Source footprint",
        "",
        "```json",
        json.dumps(report["source_footprint"], indent=2, sort_keys=True),
        "```",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": sys.version,
        "platform": sys.platform,
        "source_footprint": source_footprint(),
        "imports": import_profile(),
        "server_cold_start": server_cold_start(),
        "app_test": app_test_profile(),
        "probe_max_rss_kb": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    json_path = OUTPUT_DIR / "runtime-performance.json"
    md_path = OUTPUT_DIR / "runtime-performance.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    print(md_path.read_text(encoding="utf-8"))

    import_failures = [name for name, result in report["imports"].items() if not result.get("ok")]
    if import_failures:
        print(f"IMPORT_PROFILE_FAILURES={','.join(import_failures)}", file=sys.stderr)
        return 1
    if not report["server_cold_start"].get("ok"):
        print("SERVER_COLD_START=FAIL", file=sys.stderr)
        return 1
    app_test = report["app_test"]
    if not app_test.get("ok") or app_test.get("first_exceptions") or app_test.get("second_exceptions"):
        print("APP_TEST=FAIL", file=sys.stderr)
        return 1
    print("WEB_0_9_PERFORMANCE_PROBE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
