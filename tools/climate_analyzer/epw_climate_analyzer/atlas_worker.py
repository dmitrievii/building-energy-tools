"""Private HTML atlas worker. Input is emitted by atlas_isolation only."""
from pathlib import Path
import json
import pickle
import sys

def _write_json(path,value):
    draft=path.with_suffix(".tmp")
    draft.write_text(json.dumps(value,ensure_ascii=False,default=str),encoding="utf-8")
    draft.replace(path)

def main(directory):
    root=Path(directory)
    result=root/"result.json"
    try:
        from .p66_export import generate_atlas
        with (root/"request.pkl").open("rb") as stream:
            diagrams,df,context,kwargs=pickle.load(stream)
        (root/"request.pkl").unlink()
        def progress(done,total,label):
            _write_json(root/"status.json",dict(done=done,total=total,label=label))
        generate_atlas(diagrams,df,context,**kwargs,progress=progress,output_path=root/"atlas.zip")
        _write_json(result,{"ok":True})
        return 0
    except Exception as exc:
        _write_json(result,{"ok":False,"error":f"{type(exc).__name__}: {exc}"})
        return 1

if __name__=="__main__":raise SystemExit(main(sys.argv[1]))
