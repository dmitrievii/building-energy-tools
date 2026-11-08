"""Exercise the entire registered matrix on synthetic data, never on real C."""
import contextlib
import io
import json
from pathlib import Path
import sys
from test_next_experiments import NextWorkspace
from ige_next.study import prepare,train,implementation
from ige_local.common import write_json


def main():
    output=Path(sys.argv[1]) if len(sys.argv)>1 else Path(__file__).resolve().parents[1]/"validation/NEXT_ALL_STRUCTURES_SYNTHETIC.json"
    w=NextWorkspace();w.setUp()
    try:
        c=w.config_next(w.source());c["optimizer"].update(max_evaluations=300,max_iterations=60,starts=2,wall_seconds_per_model=90)
        with contextlib.redirect_stdout(io.StringIO()):
            out=prepare(c);summary=train(out)
        value={"fixture":"SYNTHETIC_NOT_OBSERVATIONS","version":summary["version"],
            "models_requested":summary["models_requested"],"models_eligible":summary["models_eligible"],
            "failures":summary["failures"],"holdout_opened":summary["holdout_opened"],
            "wall_seconds":summary["wall_seconds_this_invocation"],"cpu_seconds":summary["cpu_seconds_this_invocation"],
            "peak_rss_bytes":summary["peak_rss_bytes"],"implementation":implementation()}
        write_json(output,value);print(json.dumps({k:v for k,v in value.items() if k!="implementation"},indent=2))
        return 0 if value["models_requested"]==value["models_eligible"]==73 and not value["holdout_opened"] else 2
    finally:w.doCleanups()


if __name__=="__main__":raise SystemExit(main())
