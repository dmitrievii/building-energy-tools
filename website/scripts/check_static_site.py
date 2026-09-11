from __future__ import annotations

import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

REPO_ROOT = Path(__file__).resolve().parents[2]
SITE_ROOT = REPO_ROOT / "website" / "site"
MANIFEST_PATH = SITE_ROOT / "site-manifest.json"

EXPECTED_PAGES = {
    "index.html",
    "tools/index.html",
    "teaching/index.html",
    "research/index.html",
    "documentation/index.html",
    "about/index.html",
    "privacy/index.html",
    "accessibility/index.html",
    "legal/index.html",
}
ALLOWED_EXTERNAL_LINK_HOSTS = {
    "building-climate-analyzer.streamlit.app",
    "dmitrievii.github.io",
    "github.com",
}

class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.h1_count=0; self.main_ids=set(); self.hrefs=[]; self.asset_urls=[]; self.script_count=0; self.lang=None; self.title_depth=0; self.title_text=[]; self.has_viewport=False; self.primary_nav=False
    def handle_starttag(self, tag, attrs):
        values=dict(attrs)
        if tag=="html": self.lang=values.get("lang")
        elif tag=="h1": self.h1_count += 1
        elif tag=="main" and values.get("id"): self.main_ids.add(values["id"] or "")
        elif tag=="a" and values.get("href"): self.hrefs.append(values["href"] or "")
        elif tag=="link" and values.get("href"): self.asset_urls.append(values["href"] or "")
        elif tag in {"img","source","iframe"} and values.get("src"): self.asset_urls.append(values["src"] or "")
        elif tag=="script":
            self.script_count += 1
            if values.get("src"): self.asset_urls.append(values["src"] or "")
        elif tag=="meta" and values.get("name")=="viewport": self.has_viewport=True
        elif tag=="nav" and values.get("aria-label")=="Primary navigation": self.primary_nav=True
        elif tag=="title": self.title_depth += 1
    def handle_endtag(self, tag):
        if tag=="title" and self.title_depth: self.title_depth -= 1
    def handle_data(self, data):
        if self.title_depth: self.title_text.append(data)

def _is_external(value):
    parsed=urlparse(value); return parsed.scheme in {"http","https"} or bool(parsed.netloc)

def _resolve_local(page, href):
    clean=href.split("#",1)[0].split("?",1)[0]
    if not clean: return None
    target=(page.parent/clean).resolve()
    try: target.relative_to(SITE_ROOT.resolve())
    except ValueError: raise AssertionError(f"local link escapes site root: {page.relative_to(SITE_ROOT)} -> {href}")
    if clean.endswith("/") or target.is_dir(): target=target/"index.html"
    return target

def validate_site():
    errors=[]
    try: manifest=json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc: return [f"manifest unreadable: {exc}"]
    stage=manifest.get("stage")
    if not isinstance(stage,str) or re.fullmatch(r"SITE-\d+\.\d+",stage) is None: errors.append("manifest stage must use SITE-x.y format")
    if manifest.get("build_required") is not False: errors.append("static website must not require a build step")
    if manifest.get("javascript_required") is not False: errors.append("static website must not require JavaScript")
    if manifest.get("runtime_dependencies") != []: errors.append("static website runtime_dependencies must remain empty")
    if manifest.get("external_runtime_assets") != []: errors.append("static website external_runtime_assets must remain empty")
    if manifest.get("publication_status") != "BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED": errors.append("publication status changed without publication-gate closure")
    actual_pages={str(path.relative_to(SITE_ROOT)) for path in SITE_ROOT.rglob("*.html")}
    missing=EXPECTED_PAGES-actual_pages
    if missing: errors.append(f"missing pages: {sorted(missing)}")
    for relative in sorted(EXPECTED_PAGES & actual_pages):
        page=SITE_ROOT/relative; parser=PageParser(); parser.feed(page.read_text(encoding="utf-8"))
        if parser.lang!="en": errors.append(f"{relative}: html lang must be en")
        if parser.h1_count!=1: errors.append(f"{relative}: expected exactly one h1, found {parser.h1_count}")
        if "main" not in parser.main_ids: errors.append(f"{relative}: missing <main id=\"main\">")
        if not "".join(parser.title_text).strip(): errors.append(f"{relative}: missing document title")
        if not parser.has_viewport: errors.append(f"{relative}: missing responsive viewport meta")
        if not parser.primary_nav: errors.append(f"{relative}: missing primary navigation")
        if parser.script_count: errors.append(f"{relative}: JavaScript is not allowed by the static-site contract")
        for asset in parser.asset_urls:
            if _is_external(asset): errors.append(f"{relative}: external runtime asset is not allowed: {asset}"); continue
            try: target=_resolve_local(page,asset)
            except AssertionError as exc: errors.append(str(exc)); continue
            if target is not None and not target.exists(): errors.append(f"{relative}: missing local asset {asset}")
        for href in parser.hrefs:
            if href.startswith(("mailto:","tel:")): continue
            if _is_external(href):
                host=(urlparse(href).hostname or "").lower()
                if host not in ALLOWED_EXTERNAL_LINK_HOSTS: errors.append(f"{relative}: unreviewed external link host {host}: {href}")
                continue
            try: target=_resolve_local(page,href)
            except AssertionError as exc: errors.append(str(exc)); continue
            if target is not None and not target.exists(): errors.append(f"{relative}: broken internal link {href}")
    index=(SITE_ROOT/'index.html').read_text(encoding='utf-8') if (SITE_ROOT/'index.html').exists() else ''
    tools=(SITE_ROOT/'tools'/'index.html').read_text(encoding='utf-8') if (SITE_ROOT/'tools'/'index.html').exists() else ''
    climate_url='https://building-climate-analyzer.streamlit.app/'
    if climate_url not in index or climate_url not in tools: errors.append('Climate Analyzer must be directly linked from Home and Tools')
    if 'https://dmitrievii.github.io/building-energy-tools/tools/thermal-comfort-studio/' not in tools: errors.append('Thermal Comfort Studio must be directly linked from Tools')
    if 'not an official TU Graz' not in index: errors.append('Home must retain the project independence notice')
    return errors

def main():
    errors=validate_site()
    if errors:
        print('Static site validation FAILED')
        for error in errors: print(f'- {error}')
        return 1
    print(f'Static site validation PASS: {len(EXPECTED_PAGES)} core pages, zero shell runtime dependencies')
    return 0

if __name__=='__main__': sys.exit(main())
