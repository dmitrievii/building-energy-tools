"""Versioned continuation before humidity model selection; preserve the parent."""
import copy
from pathlib import Path
import shutil
import numpy as np
from ige_auto.data import Cube
from ige_local.common import InputError,digest,file_hash,log,new_run,write_json
from .auxiliary import MODEL
from .config import sealed,check_cohort
from .study import create_spec,implementation,seal

PUBLISHED_020_CODE_ID="3656f5a28c94b12d065cac9cc34b091bff85f6469a911f27539e78ee3aa0b68f"


def fork_run(source,anchor_path=None):
    source=Path(source).resolve();old=sealed(source/"run_spec.sealed.json","spec_id")
    recognized=(old["version"]=="0.2.0" and digest(old["implementation"])==PUBLISHED_020_CODE_ID)
    if not recognized and old["implementation"]!=implementation():
        raise InputError("Recovery only accepts published 0.2.0 or the unchanged current implementation")
    if (source/"selected_chains.sealed.json").exists() or any((source/"models").rglob("result.sealed.json")):
        raise InputError("This recovery is limited to the auxiliary stage before humidity selection on V")
    if (source/"summary.json").exists() and sealed_summary_opened(source):
        raise InputError("Cannot recover a run after C exposure")
    anchor=Path(anchor_path or old["configuration"]["cohort_anchor"]).resolve()
    anchored=sealed(anchor,"split_id")
    if anchored!=old["anchor"]:raise InputError("Recovery anchor differs from the frozen original cohort")
    if (source/"C_OPENED.json").exists() or (anchor.parent.parent/"C_OPENED.json").exists():
        raise InputError("C already exposed; cannot recover as unexposed development")
    location=source/"cube"
    if not (location/"metadata.json").is_file():location=Path(old["cube_path"])
    cube=Cube(location)
    if cube.meta["cube_id"]!=old["cube_id"]:raise InputError("Recovery input cube changed")
    check_cohort(cube,anchored)
    c=copy.deepcopy(old["base_configuration"]);h=copy.deepcopy(old["configuration"])
    h["results"]=str(source.parent);h["cohort_anchor"]=str(anchor)
    expected={"aux_full_D":np.flatnonzero(cube.roles=="D")}
    expected.update({"aux_inner_"+str(i):np.flatnonzero((cube.roles=="D")&(cube.folds!=i)) for i in range(c["inner_folds"])})
    inherited=[]
    for p in sorted((source/"checkpoints").glob("*.json")):
        if p.stem not in expected:raise InputError("Unexpected checkpoint in a pre-selection run: "+p.name)
        record=sealed(p,"checkpoint_id")
        if record["spec_id"]!=old["spec_id"] or set(record["value"])!={"T","p"}:
            raise InputError("Parent checkpoint has incompatible provenance")
        families=sorted({cube.stations[i]["family"] for i in expected[p.stem]})
        years=sorted(set(cube.years[cube.time_roles=="D"].tolist()))
        for value in record["value"].values():
            if (value["model"]!=MODEL or value["optimization"]["status"]!="CONVERGED"
                or value["training_families"]!=families or value["training_years"]!=years
                or not np.all(np.isfinite(value["fit"]["coefficients"]))):
                raise InputError("Parent auxiliary checkpoint failed D-only support checks: "+p.name)
        inherited.append((p,record,file_hash(p)))
    parent_hash=file_hash(source/"run_spec.sealed.json")
    root=new_run(source.parent)
    log("Recovery child run: "+str(root))
    shutil.copytree(cube.path,root/"cube")
    fresh=Cube(root/"cube");spec=create_spec(fresh,h,c,anchored,root)
    lineage={"schema":"IGE_HUMIDITY_CONTINUATION_v1","parent_run":str(source),"parent_spec_id":old["spec_id"],
        "parent_spec_sha256":parent_hash,"parent_version":old["version"],"parent_code_id":digest(old["implementation"]),
        "cube_unchanged":True,"no_reaudit_or_download":True,"anchor_relocated":str(anchor)!=old["configuration"]["cohort_anchor"],
        "checkpoint_policy":"Reuse converged D-only branches; recover numerical failures only; no V score existed in parent",
        "inherited_checkpoints":{p.name:{"checkpoint_id":record["checkpoint_id"],"sha256":sha} for p,record,sha in inherited}}
    spec.pop("spec_id");spec["continuation"]=lineage
    spec=seal(root/"run_spec.sealed.json",spec,"spec_id")
    for p,record,sha in inherited:
        seal(root/"checkpoints"/p.name,{"spec_id":spec["spec_id"],"value":record["value"],
             "inherited_from":{"spec_id":old["spec_id"],"checkpoint_id":record["checkpoint_id"],"sha256":sha}},"checkpoint_id")
    if file_hash(source/"run_spec.sealed.json")!=parent_hash or any(file_hash(p)!=sha for p,record,sha in inherited):
        raise InputError("Parent changed during continuation preparation")
    write_json(root/"effective_config.json",h);write_json(root/"base_config.resolved.json",c)
    write_json(root/"recovery_lineage.json",lineage)
    log("Verified and inherited "+str(len(inherited))+" complete auxiliary bundles; C remains closed")
    return root


def sealed_summary_opened(source):
    import json
    return bool(json.loads((source/"summary.json").read_bytes()).get("holdout_opened"))
