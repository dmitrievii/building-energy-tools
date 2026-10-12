#!/usr/bin/env python3
"""Safe non-executing ZIP inventory for locally installed Meteonorm 8 media.

No installer execution, extraction, license reads or binary reverse engineering.
Export only a redacted file listing to share for automation feasibility review.
"""
from pathlib import Path
import argparse
import collections
import hashlib
import json
import os
import re
import zipfile


def redact(name):
    if re.search(r"license|licence|activation|serial|product.?key|password|credential", name, re.I):
        return "[redacted potentially sensitive filename]"
    return name


def inspect(filename):
    p = Path(filename)
    if not p.is_file():
        raise FileNotFoundError(p)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(2 << 20), b""):
            h.update(b)
    report = {"file": p.name, "file_size_bytes": p.stat().st_size, "sha256": h.hexdigest()}
    with zipfile.ZipFile(p) as z:
        items = z.infolist()
        ext = collections.Counter(Path(i.filename).suffix.lower() for i in items if not i.is_dir())
        type_limited = {".exe", ".msi", ".dll", ".config", ".xml", ".json", ".ini",
                        ".txt", ".pdf", ".chm", ".bat", ".cmd", ".ps1", ".manifest"}
        selected = []
        for i in items:
            if Path(i.filename).suffix.lower() in type_limited and not i.is_dir():
                selected.append({"path": redact(i.filename[:220]),
                                 "size_bytes": i.file_size, "encrypted": bool(i.flag_bits & 1)})
        unsafe = [redact(i.filename[:220]) for i in items
                  if i.filename.startswith(("/", "\\")) or ".." in Path(i.filename).parts]
        report.update({
            "member_count": len(items),
            "uncompressed_bytes": sum(i.file_size for i in items),
            "encrypted_count": sum(bool(i.flag_bits & 1) for i in items),
            "extension_counts": dict(ext.most_common()),
            "selected_files_first_160": selected[:160],
            "unsafe_archive_member_paths": unsafe[:20],
            "files_omitted_for_privacy": max(0, len(selected) - 160),
            "exe_or_installer_run": False,
            "archive_contents_extracted": False
        })
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("archive", help="Path to your original Meteonorm 8 ZIP")
    ap.add_argument("--out", default="meteonorm8_installer_inventory.json")
    a = ap.parse_args()
    info = inspect(a.archive)
    Path(a.out).write_text(json.dumps(info, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("ZIP inventoried without executing anything. Output:", a.out)
    print("Members:", info["member_count"], "| archive sha256:", info["sha256"])


if __name__ == "__main__":
    main()
