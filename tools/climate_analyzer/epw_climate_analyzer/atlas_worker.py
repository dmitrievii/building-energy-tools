"""Private HTML atlas worker. Input is emitted by atlas_isolation only."""
from pathlib import Path
import json
import pickle
import sys
from time import perf_counter

def _write_json(path,value):
    draft=path.with_suffix(".tmp")
    draft.write_text(json.dumps(value,ensure_ascii=False,default=str),encoding="utf-8")
    draft.replace(path)

def main(directory):
    root=Path(directory)
    result=root/"result.json"
    try:
        started=perf_counter()
        from .p66_export import generate_atlas
        import_seconds=perf_counter()-started
        started=perf_counter()
        with (root/"request.pkl").open("rb") as stream:
            diagrams,df,context,kwargs=pickle.load(stream)
        request_seconds=perf_counter()-started
        (root/"request.pkl").unlink()
        def progress(done,total,label):
            _write_json(root/"status.json",dict(done=done,total=total,label=label))
        started=perf_counter()
        generate_atlas(diagrams,df,context,**kwargs,progress=progress,output_path=root/"atlas.zip")
        generation_seconds=perf_counter()-started
        _write_json(result,{"ok":True,"worker_import_seconds":import_seconds,
                            "worker_request_load_seconds":request_seconds,
                            "worker_generation_seconds":generation_seconds})
        return 0
    except Exception as exc:
        _write_json(result,{"ok":False,"error":f"{type(exc).__name__}: {exc}"})
        return 1

if __name__=="__main__":raise SystemExit(main(sys.argv[1]))
