"""Disk-backed disposable rendering shared by report exporters."""
from pathlib import Path
import gc
import os
import signal
import subprocess
import sys
import tempfile
import time
from .p66_memory import require_headroom

def render_png(fig,target,*,scale=1.5,timeout=120):
    target=Path(target)
    require_headroom()
    with tempfile.TemporaryDirectory(prefix="ige-render-") as tmp:
        source=Path(tmp)/"figure.json";log=Path(tmp)/"renderer.log"
        fig.write_json(str(source))
        require_headroom()
        args=[sys.executable,str(Path(__file__).with_name("p6_render_worker.py")),str(source),str(target),str(scale)]
        with log.open("wb") as errors:
            proc=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=errors,stderr=errors,start_new_session=(os.name=="posix"))
            try:
                deadline=time.monotonic()+timeout
                while proc.poll() is None:
                    require_headroom()
                    if time.monotonic()>=deadline:raise TimeoutError("Static figure render timed out.")
                    time.sleep(.20)
                if proc.returncode:
                    with log.open("rb") as f:
                        f.seek(max(0,log.stat().st_size-3000))
                        message=f.read().decode("utf-8",errors="replace")
                    raise RuntimeError(f"Renderer exited with status {proc.returncode}: {message}")
                if not target.is_file() or target.stat().st_size==0:raise RuntimeError("Renderer produced no image.")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
            finally:
                # Reap Chromium descendants even if the parent has exited.
                if os.name=="posix":
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                elif proc.poll() is None:proc.kill()
                proc.wait()
        gc.collect()
        require_headroom()
    return target
