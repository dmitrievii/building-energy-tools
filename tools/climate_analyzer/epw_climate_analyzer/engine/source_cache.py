"""Best-effort, bounded original-response checkpoints, never a data fallback.

Public source bodies only. Exact keys, original metadata, byte limits, expiry
and SHA-256 are checked on every read. Callers still perform scientific admission.
"""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import tempfile
import threading
import time

_LOCK = threading.RLock()
MAX_AGE = 86400
MAX_DISK_BYTES = 256 * 1024**2


class OriginalSourceCache:
    def __init__(self, directory=None, *, entry_limit=32*1024**2, max_age=MAX_AGE,
                 max_disk_bytes=MAX_DISK_BYTES):
        self.directory = Path(directory) if directory is not None else Path(tempfile.gettempdir())/"ige-original-sources-v1"
        self.entry_limit = entry_limit
        self.max_age = max_age
        self.max_disk_bytes = max_disk_bytes

    def _path(self, key):
        return self.directory/(sha256(key.encode()).hexdigest()+".cache")

    def get(self, key):
        try:
            path = self._path(key)
            if path.stat().st_size > self.entry_limit+4096:
                return None
            with path.open("rb") as stream:
                header = stream.readline(4097)
                if len(header) > 4096 or not header.endswith(b"\n"):
                    return None
                info = json.loads(header)
                body = stream.read(self.entry_limit+1)
            if (info["key"] != key or not 0 <= time.time()-info["saved_at"] <= self.max_age
                    or not body or len(body) > self.entry_limit or len(body) != info["bytes"]
                    or sha256(body).hexdigest() != info["sha256"]):
                return None
            return body, info.get("metadata", {})
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            return None

    def put(self, key, body, metadata=None):
        if not body or len(body) > min(self.entry_limit, self.max_disk_bytes-4096):
            return
        info = {"key": key, "saved_at": time.time(), "bytes": len(body),
                "sha256": sha256(body).hexdigest(), "metadata": metadata or {}}
        header = json.dumps(info, separators=(",", ":"), allow_nan=False).encode()+b"\n"
        if len(header) > 4096:
            return
        temporary = None
        try:
            with _LOCK:
                self.directory.mkdir(parents=True, exist_ok=True)
                target = self._path(key)
                entries = sorted(self.directory.glob("*.cache"), key=lambda p: p.stat().st_mtime)
                size = sum(p.stat().st_size for p in entries if p != target)
                for path in entries:
                    if path == target:
                        continue
                    if size+len(header)+len(body) <= self.max_disk_bytes and time.time()-path.stat().st_mtime <= self.max_age:
                        continue
                    size -= path.stat().st_size
                    path.unlink(missing_ok=True)
                with tempfile.NamedTemporaryFile(dir=self.directory, suffix=".part", delete=False) as stream:
                    temporary = Path(stream.name)
                    stream.write(header); stream.write(body)
                temporary.replace(target)
        except OSError:
            # An unavailable cache never prevents a live source request.
            pass
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
