"""Source-derived runtime identity for live deployment verification.

The fingerprint intentionally covers the Streamlit entrypoint, dependency lock
surface, and every Python module in the Climate Analyzer package.  It changes
automatically whenever executable application source changes, without coupling
public release metadata to deployment mechanics.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


def runtime_source_files(tool_root: Path | None = None) -> list[Path]:
    """Return the ordered files that define one Climate Analyzer runtime build."""
    root = tool_root or Path(__file__).resolve().parents[1]
    package_root = root / "epw_climate_analyzer"
    files = [root / "app.py", root / "requirements.txt"]
    files.extend(sorted(package_root.glob("*.py"), key=lambda path: path.name))
    return files


def runtime_build_id(tool_root: Path | None = None) -> str:
    """Return a deterministic SHA-256 identity for the executable source set."""
    root = tool_root or Path(__file__).resolve().parents[1]
    digest = sha256()
    for path in runtime_source_files(root):
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


RUNTIME_BUILD_ID = runtime_build_id()
