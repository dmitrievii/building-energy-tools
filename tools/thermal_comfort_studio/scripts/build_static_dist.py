from __future__ import annotations
import argparse
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def build(output: Path) -> None:
    output = output.resolve()
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    shutil.copy2(ROOT / "index.html", output / "index.html")
    shutil.copytree(ROOT / "src", output / "src")
    for child in (ROOT / "public").iterdir():
        target = output / child.name
        if child.is_dir(): shutil.copytree(child, target)
        else: shutil.copy2(child, target)

    forbidden = list(output.rglob("*.png")) + list(output.rglob("*reference*"))
    if forbidden:
        raise SystemExit(f"publication build contains forbidden development assets: {forbidden[:5]}")
    required = [output/'index.html', output/'src'/'main.js', output/'assets'/'favicon.svg']
    missing = [p for p in required if not p.is_file()]
    if missing:
        raise SystemExit(f"publication build missing required files: {missing}")
    print(f"Thermal Comfort Studio publication build PASS: {sum(1 for p in output.rglob('*') if p.is_file())} files")

if __name__ == '__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('--output', default=str(ROOT/'dist'))
    args=ap.parse_args()
    build(Path(args.output))
