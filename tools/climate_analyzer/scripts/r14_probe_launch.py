"""Version-scoped experimental launcher, separate from the production launcher."""
import inspect
import os
from pathlib import Path
import sys
import tracemalloc

def main():
    import streamlit
    from streamlit.runtime.runtime import Runtime
    if streamlit.__version__ not in ("1.63.0","1.67.0"):
        raise RuntimeError("Unexpected Streamlit experiment version")
    mode=os.environ["R14_MODE"]
    if mode not in ("native","close","close-loop"):raise RuntimeError("Invalid mode")
    if mode=="close-loop":
        original=Runtime._loop_coroutine
        source=inspect.getsource(original)
        marker="                    # Yield briefly between session message flushing cycles.\n"
        before="                    for active_session_info in self._session_mgr.list_active_sessions():\n"
        if Runtime.exists() or source.count(marker)!=1 or source.count(before)!=1 or source.index(before)>source.index(marker):
            raise RuntimeError("Runtime source contract changed")
        corrected=source.replace(marker,"                    active_session_info = msg_list = msg = None\n"+marker,1)
        namespace={}
        exec(compile("class _ProbeRuntimeLoop:\n"+corrected,inspect.getsourcefile(original),"exec"),original.__globals__,namespace)
        replacement=namespace["_ProbeRuntimeLoop"]._loop_coroutine
        replacement._ige_r14_probe=True
        Runtime._loop_coroutine=replacement
    if os.environ.get("R14_TRACE")=="1":tracemalloc.start(8)
    from streamlit.web import cli
    sys.argv=["streamlit","run",str(Path(__file__).with_name("r14_probe_app.py")),*sys.argv[1:]]
    cli.main()

if __name__=="__main__":main()
