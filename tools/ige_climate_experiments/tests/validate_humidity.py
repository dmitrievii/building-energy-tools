"""Reproduce the all-structure smoke test using synthetic D/V data only."""
import contextlib
import io
import json
from pathlib import Path
import platform
import sys

from test_humidity_comparison import HumidityWorkspace
from ige_local.common import read_json,write_json
from ige_hum.study import create_spec,train,implementation


def main():
    root=Path(__file__).resolve().parents[1]
    output=Path(sys.argv[1]) if len(sys.argv)>1 else root/"validation/HUMIDITY_ALL_STRUCTURES_SYNTHETIC.json"
    w=HumidityWorkspace();w.setUp()
    try:
        w.c["models"]=read_json(root/"config_auto_regression.json")["models"]
        w.c["optimizer"].update(max_evaluations=300,max_iterations=60)
        run=w.base/"all_structures";run.mkdir()
        create_spec(w.cube,w.h,w.c,w.anchor,run)
        with contextlib.redirect_stdout(io.StringIO()):summary=train(run)
        records=[read_json(p) for p in sorted((run/"models").rglob("result.sealed.json"))]
        record={"fixture":"SYNTHETIC_NOT_OBSERVATIONS","scope":"All six production structures for each of RH/log_e/q; D/V only",
            "real_weather_C_evaluated":False,"synthetic_holdout_opened":summary["holdout_opened"],
            "requested":summary["models_requested"],"eligible":summary["models_eligible"],"exit_code":summary["exit_code"],
            "wall_seconds":summary["wall_seconds_this_invocation"],"peak_rss_bytes":summary["peak_process_rss_bytes"],
            "case_matrix_bytes":summary["estimated_resident_case_matrices_bytes"],
            "python":platform.python_version(),"implementation_sha256":implementation(),
            "models":[{"coordinate":m["coordinate"],"model":m["model"]["id"],"status":m["status"],
                       "reason":m.get("reason"),"optimizer_status":m.get("optimization",{}).get("status")} for m in records]}
        write_json(output,record)
        print(json.dumps({k:record[k] for k in ("fixture","requested","eligible","exit_code")},indent=2))
        return 0 if record["eligible"]==18 and record["exit_code"]==0 and not record["synthetic_holdout_opened"] else 2
    finally:w.doCleanups()


if __name__=="__main__":raise SystemExit(main())
