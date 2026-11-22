"""MEM-PERF R2: synchronous, disposable HTML atlas process.

Only locally created, private pickle files are read. Never deserialize uploaded
files. The parent owns the workspace and holds the shared export admission lock.
No automatic in-process fallback on resource failure.
"""
from __future__ import annotations
import gc
import json
import os
from pathlib import Path
import pickle
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from .p66_memory import EXPORT_LOCK,MIB,container_memory,require_html_headroom,_trim_allocator

LAUNCH_RESERVE=768*MIB
POLL_SECONDS=.15
TIMEOUT_SECONDS=1800
MAX_OUTPUT=32*MIB
MAX_STATUS=4*MIB

def _admit_launch():
    sample=container_memory()
    if sample is None:return
    used,cap=sample
    reserve=min(LAUNCH_RESERVE,max(384*MIB,int(cap*.30)))
    if used+reserve>=cap:
        gc.collect();_trim_allocator()
        used,cap=container_memory() or sample
        if used+reserve>=cap:
            raise MemoryError(f"HTML worker admission blocked: {used/MIB:.0f}/{cap/MIB:.0f} MiB used; needs {reserve/MIB:.0f} MiB raw headroom. Clean caches or reboot the app.")

def _stop(proc):
    if os.name=="posix":
        try:os.killpg(proc.pid,signal.SIGKILL)
        except ProcessLookupError:pass
    elif proc.poll() is None:proc.kill()
    proc.wait()

def _read_json(path,limit):
    if not path.is_file() or path.stat().st_size>limit:return None
    with path.open("r",encoding="utf-8") as stream:return json.load(stream)

def _rss(pid):
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):return int(line.split()[1])*1024
    except (OSError,ValueError,IndexError):pass
    return 0

def isolated_html_atlas(diagrams,df,context,*,progress=None,timeout=TIMEOUT_SECONDS,**kwargs):
    from .p66_export import PDF_MODES
    kwargs.setdefault("mode",PDF_MODES[2])
    if kwargs["mode"]!=PDF_MODES[2] or "image_renderer" in kwargs or "output_path" in kwargs:
        raise ValueError("Only ordinary browserless HTML atlas exports can be isolated.")
    if not EXPORT_LOCK.acquire(blocking=False):
        raise RuntimeError("Another report/Atlas export is active. Try again after it finishes.")
    try:
        _admit_launch()
        with tempfile.TemporaryDirectory(prefix="ige-atlas-r2-") as tmp:
            root=Path(tmp)
            request=root/"request.pkl"
            status=root/"status.json"
            result=root/"result.json"
            output=root/"atlas.zip"
            log=root/"worker.log"
            with request.open("wb") as stream:
                pickle.dump((diagrams,df,context,kwargs),stream,protocol=5)
            _admit_launch()
            start=time.monotonic()
            baseline=container_memory()
            peak=baseline[0] if baseline else None
            parent_rss_before=_rss(os.getpid())
            worker_peak=0
            previous=None
            module_root=Path(__file__).resolve().parents[1]
            with log.open("wb") as errors:
                proc=subprocess.Popen([sys.executable,"-m","epw_climate_analyzer.atlas_worker",str(root)],
                    cwd=str(module_root),stdin=subprocess.DEVNULL,stdout=errors,stderr=errors,
                    start_new_session=(os.name=="posix"))
                try:
                    while proc.poll() is None:
                        sample=container_memory()
                        if sample:
                            used,cap=sample;peak=max(peak or 0,used)
                            reserve=min(384*MIB,max(96*MIB,int(cap*.20)))
                            if used+reserve>=cap:
                                raise MemoryError(f"HTML worker stopped at {used/MIB:.0f}/{cap/MIB:.0f} MiB raw container usage. No partial archive returned.")
                        worker_peak=max(worker_peak,_rss(proc.pid))
                        current=_read_json(status,MAX_STATUS)
                        if current and current!=previous:
                            previous=current
                            if progress:progress(current["done"],current["total"],current["label"])
                        if time.monotonic()-start>=timeout:raise TimeoutError("HTML atlas worker timed out.")
                        time.sleep(POLL_SECONDS)
                finally:_stop(proc)
            info=_read_json(result,MAX_STATUS)
            if proc.returncode or not info or not info.get("ok"):
                detail=info.get("error") if info else f"worker exited with status {proc.returncode}"
                raise RuntimeError("HTML atlas worker failed: "+str(detail))
            if not output.is_file() or not 0<output.stat().st_size<=MAX_OUTPUT:
                raise RuntimeError("Missing or oversized HTML atlas archive.")
            with zipfile.ZipFile(output) as z:
                if not {"index.html","coverage.csv","atlas_metadata.json","plotly.min.js"}.issubset(z.namelist()):
                    raise RuntimeError("Incomplete HTML atlas archive.")
                metadata=json.loads(z.read("atlas_metadata.json"))
                manifest=metadata["manifest"]
            if [row["id"] for row in manifest]!=[d.id for d in diagrams]:
                raise RuntimeError("HTML atlas manifest does not match the selected diagrams.")
            gc.collect();_trim_allocator()
            require_html_headroom("HTML worker result transfer")
            after=container_memory()
            data=output.read_bytes()
            wall=time.monotonic()-start
            import_s=info.get("worker_import_seconds")
            request_s=info.get("worker_request_load_seconds")
            generation_s=info.get("worker_generation_seconds")
            accounted=sum(v for v in (import_s,request_s,generation_s) if v is not None)
            metadata["execution_diagnostics"]={"mode":"isolated HTML worker","wall_seconds":wall,
                "worker_import_seconds":import_s,
                "worker_request_load_seconds":request_s,
                "worker_generation_seconds":generation_s,
                "outer_residual_seconds":max(0.,wall-accounted),
                "sampled_container_peak_mib":peak/MIB if peak is not None else None,
                "sampled_worker_rss_peak_mib":worker_peak/MIB if worker_peak else None,
                "baseline_container_mib":baseline[0]/MIB if baseline else None,
                "container_after_worker_exit_mib":after[0]/MIB if after else None,
                "parent_rss_before_mib":parent_rss_before/MIB if parent_rss_before else None,
                "parent_rss_after_transfer_mib":(_rss(os.getpid()) or 0)/MIB if parent_rss_before else None}
            if progress:progress(sum(d.status=="available" for d in diagrams),sum(d.status=="available" for d in diagrams),"Atlas complete")
            return data,manifest,metadata
    finally:
        gc.collect();_trim_allocator()
        EXPORT_LOCK.release()
