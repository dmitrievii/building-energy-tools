"""Disk-backed rendering: bounded export-scoped worker and disposable fallback."""
from pathlib import Path
import gc
import os
import signal
import subprocess
import sys
import tempfile
import time
from .p66_memory import require_headroom

def render_disposable(fig,target,*,scale=1.5,timeout=120,_sample=None):
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
                    if _sample is not None:_sample()
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


# P6.7: no shared browser across exports or concurrent requests.
from contextlib import contextmanager
from contextvars import ContextVar
from importlib.metadata import version
import hashlib
import json
import logging
import shutil
from .p66_memory import container_memory,MIB

_ACTIVE=ContextVar("ige_render_session",default=None)
_LOG=logging.getLogger(__name__)
_CACHE_BYTES=64*MIB
_CACHE_ITEMS=256
_WORKER=Path(__file__).with_name("p6_render_worker.py")

def _valid_png(path):
    from PIL import Image
    try:
        with Image.open(path) as im:
            if im.format!="PNG" or min(im.size)<=0:return False
            im.verify()
        return True
    except (OSError,ValueError):return False

def session_cache_dir(state):
    """Private disk cache owned by this Streamlit session, not by the server."""
    key="_p67_render_cache"
    if key not in state:state[key]=tempfile.TemporaryDirectory(prefix="ige-p67-cache-")
    return Path(state[key].name)

class RenderSession:
    def __init__(self,*,cache_dir=None,mode="adaptive",max_jobs=8,metrics=None):
        if mode not in ("adaptive","disposable"):raise ValueError("Invalid renderer mode")
        self.mode=mode
        self.max_jobs=max(1,min(32,int(max_jobs)))
        self.cache=Path(cache_dir) if cache_dir is not None else None
        self.metrics=metrics
        self.proc=None
        self.tmp=None
        self.log=None
        self.jobs=0
        self.warm_used=None
        self.starts=0
        self.renders=0
        self.hits=0
        self.fallbacks=0
        self.seconds=0.
        self.peak=0
        self.identity="p67-v1:"+version("plotly")+":"+version("kaleido")+":"+hashlib.sha256(_WORKER.read_bytes()).hexdigest()

    def sample(self):
        value=container_memory()
        if value:self.peak=max(self.peak,value[0])
        return value

    def reusable(self):
        # Unknown container limit or non-POSIX process-tree semantics: use
        # existing disposable mode rather than retain unbounded browser state.
        value=self.sample()
        if self.mode!="adaptive" or os.name!="posix" or value is None:return False
        used,cap=value
        if used>=min(.72*cap,cap-512*MIB):return False
        if self.proc is not None:
            if self.proc.poll() is not None or self.jobs>=self.max_jobs:return False
            if self.warm_used is not None and used-self.warm_used>=128*MIB:return False
        return True

    def close_worker(self):
        proc,self.proc=self.proc,None
        try:
            if proc is not None:
                if proc.stdin:
                    try:proc.stdin.close()
                    except OSError:pass
                try:os.killpg(proc.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                proc.wait()
        finally:
            if self.log:self.log.close();self.log=None
            if self.tmp:self.tmp.cleanup();self.tmp=None
            self.jobs=0;self.warm_used=None

    def _wait(self,path,deadline):
        while True:
            self.sample()
            require_headroom()
            if path.is_file():return
            if self.proc.poll() is not None:raise RuntimeError("Persistent renderer exited")
            if time.monotonic()>=deadline:raise TimeoutError("Static figure render timed out.")
            time.sleep(.05)

    def _start(self,deadline):
        self.tmp=tempfile.TemporaryDirectory(prefix="ige-p67-worker-")
        directory=Path(self.tmp.name)
        self.log=(directory/"worker.log").open("wb")
        ready=directory/"ready"
        self.proc=subprocess.Popen([sys.executable,str(_WORKER),"--persistent",str(ready)],
                    stdin=subprocess.PIPE,stdout=self.log,stderr=self.log,
                    start_new_session=True)
        self.starts+=1
        self._wait(ready,deadline)

    def _persistent(self,source,target,scale,timeout):
        deadline=time.monotonic()+timeout
        cold=self.proc is None
        start=time.perf_counter()
        if cold:self._start(deadline)
        startup=time.perf_counter()-start
        result=source.with_name("result.json")
        payload={"source":str(source.resolve()),"target":str(target.resolve()),
                 "scale":scale,"result":str(result.resolve())}
        self.proc.stdin.write((json.dumps(payload)+"\n").encode("utf-8"))
        self.proc.stdin.flush()
        self._wait(result,deadline)
        answer=json.loads(result.read_text(encoding="utf-8"))
        if not answer.get("ok"):raise RuntimeError(answer.get("error","Renderer failed"))
        if not target.is_file() or target.stat().st_size==0:raise RuntimeError("Renderer produced no image.")
        self.jobs+=1
        value=self.sample()
        if self.warm_used is None and value:self.warm_used=value[0]
        return {"backend":"persistent","cold":cold,"startup_s":startup,
                "decode_s":answer["decode_s"],"render_and_encode_s":answer["render_and_encode_s"]}

    def _cache_key(self,source,scale):
        h=hashlib.sha256((self.identity+":"+float(scale).hex()).encode())
        with source.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""):h.update(chunk)
        return h.hexdigest()

    def _get_cache(self,key,target):
        if self.cache is None:return False
        p=self.cache/(key+".png")
        try:
            if p.is_file() and _valid_png(p):
                shutil.copyfile(p,target)
                os.utime(p,None)
                return True
            p.unlink(missing_ok=True)
        except OSError:pass
        return False

    def _put_cache(self,key,target):
        if self.cache is None:return
        pending=None
        try:
            if target.stat().st_size>_CACHE_BYTES:return
            self.cache.mkdir(mode=0o700,parents=True,exist_ok=True)
            p=self.cache/(key+".png")
            pending=p.with_suffix(".tmp")
            shutil.copyfile(target,pending);os.replace(pending,p)
            entries=sorted(self.cache.glob("*.png"),key=lambda x:x.stat().st_mtime)
            total=sum(e.stat().st_size for e in entries)
            while entries and (total>_CACHE_BYTES or len(entries)>_CACHE_ITEMS):
                victim=entries.pop(0);total-=victim.stat().st_size;victim.unlink()
        except OSError:
            if pending:
                try:pending.unlink(missing_ok=True)
                except OSError:pass

    def render(self,fig,target,*,scale=1.5,timeout=120):
        target=Path(target)
        started=time.perf_counter()
        info={}
        # Recycle BEFORE admission if the idle browser uses too much memory.
        if not self.reusable():self.close_worker()
        require_headroom()
        try:
            with tempfile.TemporaryDirectory(prefix="ige-p67-job-") as tmp:
                source=Path(tmp)/"figure.json"
                t=time.perf_counter()
                fig.write_json(str(source),remove_uids=True)
                info["serialize_s"]=time.perf_counter()-t
                key=self._cache_key(source,scale) if self.cache is not None else None
                if key is not None and self._get_cache(key,target):
                    self.hits+=1;info["backend"]="cache"
                else:
                    if self.reusable():
                        try:info.update(self._persistent(source,target,scale,timeout))
                        except MemoryError:raise
                        except Exception as exc:
                            self.fallbacks+=1
                            _LOG.warning("P6.7 worker retry using disposable renderer: %s",type(exc).__name__)
                            self.close_worker();target.unlink(missing_ok=True)
                            render_disposable(fig,target,scale=scale,timeout=timeout,_sample=self.sample)
                            info["backend"]="fallback"
                    else:
                        self.close_worker()
                        render_disposable(fig,target,scale=scale,timeout=timeout,_sample=self.sample)
                        info["backend"]="disposable"
                    if not _valid_png(target):raise RuntimeError("Invalid PNG from report renderer")
                    self.renders+=1
                    if key is not None:self._put_cache(key,target)
                t=time.perf_counter()
                if not self.reusable():self.close_worker()
                info['post_render_cleanup_s']=time.perf_counter()-t
                require_headroom()
        except BaseException:
            self.close_worker();target.unlink(missing_ok=True)
            raise
        finally:
            info["wall_s"]=time.perf_counter()-started
            self.seconds+=info["wall_s"]
            self.sample()
            if self.metrics is not None:self.metrics.append(info)
        return target

@contextmanager
def render_session(*,cache_dir=None,mode=None,max_jobs=8,metrics=None):
    mode=mode or os.environ.get("IGE_P67_RENDER_MODE","adaptive")
    session=RenderSession(cache_dir=cache_dir,mode=mode,max_jobs=max_jobs,metrics=metrics)
    token=_ACTIVE.set(session)
    try:yield session
    finally:
        try:
            session.close_worker()
            _LOG.info("P6.7 render summary: renders=%d cache_hits=%d worker_starts=%d fallbacks=%d wall_s=%.3f sampled_peak_mib=%.1f",
                      session.renders,session.hits,session.starts,session.fallbacks,session.seconds,session.peak/MIB)
        finally:_ACTIVE.reset(token)

def release_render_worker():
    session=_ACTIVE.get()
    if session is not None:session.close_worker()

def render_png(fig,target,*,scale=1.5,timeout=120):
    session=_ACTIVE.get()
    if session is None:return render_disposable(fig,target,scale=scale,timeout=timeout)
    return session.render(fig,target,scale=scale,timeout=timeout)
