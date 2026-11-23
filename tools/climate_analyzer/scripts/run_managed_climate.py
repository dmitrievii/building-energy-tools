"""Exclusive, cooperative Linux launcher for self-managed Climate Analyzer."""
import os
import sys
from pathlib import Path
import hashlib
import fcntl
import tempfile

def main():
    # CI-only, process-local evidence for a stalled browser initialization.
    # Do not register signals in platform-owned production processes.
    if os.environ.get("IGE_R144B_THREAD_DIAGNOSTICS")=="1":
        import faulthandler
        import signal
        faulthandler.register(signal.SIGUSR1,all_threads=True)
    app=Path(__file__).resolve().parents[1]/"app.py"
    sys.path.insert(0,str(app.parent))
    # Stable per app and UID; keep the FD open for the entire server lifetime.
    # This protects cooperating managed launches only, not platform-owned ones.
    directory=Path(tempfile.gettempdir())/f"ige-runtime-{os.getuid()}"
    directory.mkdir(mode=0o700,exist_ok=True)
    if directory.is_symlink() or directory.stat().st_uid!=os.getuid() or directory.stat().st_mode&0o077:
        raise RuntimeError("Unsafe runtime lock directory")
    lock=directory/(hashlib.sha256(str(app).encode()).hexdigest()+".lock")
    fd=os.open(lock,os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        try:fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise SystemExit("Climate Analyzer managed runtime already owns the instance lock")
        from epw_climate_analyzer.runtime_loop_patch import install_before_runtime
        install_before_runtime()
        from streamlit.web import cli
        sys.argv=["streamlit","run",str(app),*sys.argv[1:]]
        cli.main()
    finally:os.close(fd)

if __name__=="__main__":main()
