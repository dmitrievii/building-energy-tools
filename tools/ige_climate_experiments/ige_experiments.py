#!/usr/bin/env python3
"""Offline E0 + E1.0 runner for sibling Database/{AT,DE,CH}."""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
import traceback

if sys.version_info < (3, 10):
    raise SystemExit("Python 3.10 or newer is required")

from ige_local import VERSION
from ige_local.audit import audit
from ige_local.common import InputError, load_config, log, new_run, now, read_json, write_json
from ige_local.pilot import numerical_oracles, pilot


def main(argv=None):
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="command", required=True)
    for command in ("run", "audit", "pilot", "check-config"):
        s = sub.add_parser(command)
        s.add_argument("--config", type=Path, default=Path(__file__).resolve().parent / "config_E0_E10.json")
        if command in ("run", "audit"):
            s.add_argument("--rehash", action="store_true", help="Read all source bytes again instead of using stable-stat cached hashes")
        if command == "pilot":
            s.add_argument("--snapshot", required=True, type=Path, help="E0/snapshot.json from an earlier audit with the same config")
    sub.add_parser("self-check", help="Hand-computable numerical controls; no Database access")
    args = p.parse_args(argv)
    if args.command == "self-check":
        import json
        print(json.dumps({"version": VERSION, "oracles": numerical_oracles()}, indent=2))
        return 0
    root = None
    try:
        cfg = load_config(args.config)
        if args.command == "check-config":
            import json
            print(json.dumps({"configuration_valid": True,
                              **{k: cfg[k] for k in ("config_source_path", "database", "results")}},
                             ensure_ascii=False, indent=2))
            return 0
        root = new_run(cfg["results"])
        log("IGE E0 + E1.0 " + VERSION)
        log("Database (read only): " + cfg["database"])
        log("New run: " + str(root))
        write_json(root / "effective_config.json", cfg)
        if args.command in ("run", "audit"):
            snapshot, e0 = audit(cfg, root / "E0", rehash=args.rehash)
        else:
            snapshot, e0 = read_json(args.snapshot), None
            if Path(snapshot["database"]).resolve() != Path(cfg["database"]).resolve():
                raise InputError("Snapshot belongs to another Database")
        e10 = pilot(snapshot, cfg, root / "E10") if args.command in ("run", "pilot") else None
        data_errors = bool(e0 and (e0["plan_errors"] or any(c["quarantined_jobs"] for c in e0["countries"].values())))
        pilot_errors = bool(e10 and (not e10["profiles_prediction_hashes_consistent"] or e10["prepare"]["read_failures"]
                            or not e10["scored_method_case_pairs_first_profile"]
                            or any(x["failed_jobs"] or x["budget_exceeded_jobs"] for x in e10["profile_sizes"])))
        result = {"version": VERSION, "finished_at_utc": now(), "run_directory": str(root),
                  "E0": e0, "E10": e10, "source_data_errors": data_errors,
                  "engineering_pilot_incomplete": pilot_errors, "full_E10_legacy_replay_complete": False,
                  "exit_code": 2 if data_errors or pilot_errors else 0}
        write_json(root / "summary.json", result)
        lines = ["# IGE — локальный запуск E0 + E1.0", "", "Версия " + VERSION + ". Завершение: " + now() + ".", "",
                 "- [E0: аудит](E0/REPORT_RU.md)" if e0 else "- Использован ранее сохранённый E0-снимок.",
                 "- [E1.0: пилот](E10/REPORT_RU.md)" if e10 else "- Пилот не запускался.", "",
                 "Код завершения: **" + str(result["exit_code"]) + "**.", "",
                 "0 означает завершение запрошенной инженерной операции; это не допуск научного метода.",
                 "2 означает карантин/ошибку входов, отсутствие оцениваемых случаев или незавершённый пилот.",
                 "Ожидаемые незавершённые загрузки сами по себе не дают ошибку.", "",
                 "Полное воспроизведение прежних P8.2F/S1/R1 не выполнено этим скалярным пилотом;",
                 "причины перечислены в E1.0-отчёте. Новая независимая точность не квалифицирована."]
        (root / "REPORT_RU.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
        log("REPORT: " + str(root / "REPORT_RU.md"))
        log("SUMMARY: " + str(root / "summary.json"))
        return result["exit_code"]
    except Exception as exc:
        log(type(exc).__name__ + ": " + str(exc))
        if root:
            write_json(root / "failure.json", {"at_utc": now(), "error": type(exc).__name__ + ": " + str(exc), "traceback": traceback.format_exc()})
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
