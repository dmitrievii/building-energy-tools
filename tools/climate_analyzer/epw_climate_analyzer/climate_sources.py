"""Climate-file source helpers for local uploads and Climate.OneBuilding access.

This module provides two climate-file source layers for the Streamlit app:

* Local EPW file uploads handled by the UI.
* Online station selection through the public Climate.OneBuilding catalog.

Climate.OneBuilding does not expose a single JSON API. Instead, its website
publishes WMO-region pages with KML maps and XLSX spreadsheets. The functions
below build a local station cache by reading those public catalogs, extracting
station coordinates and ZIP/EPW download links, and storing the result as CSV.
The cached catalog is then used by the OSM map layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from zipfile import BadZipFile, ZipFile

import html
import re
import xml.etree.ElementTree as ET

import pandas as pd
import requests
from bs4 import BeautifulSoup
from openpyxl import load_workbook

from epw_climate_analyzer.epw_parser import MAX_EPW_BYTES, validate_epw_payload


BASE_URL = "https://climate.onebuilding.org/"
CATALOG_PATH = Path(__file__).resolve().parent / "data" / "station_catalog.csv"
CACHE_DIR = Path.home() / ".epw_climate_analyzer"
ONEBUILDING_CACHE_PATH = CACHE_DIR / "onebuilding_station_catalog.csv"
USER_AGENT = "Building-Energy-Tools-Climate-Analyzer/0.3"
ALLOWED_DOWNLOAD_HOSTS = {"climate.onebuilding.org"}
MAX_DOWNLOAD_BYTES = 32 * 1024 * 1024
MAX_ZIP_MEMBERS = 128
MAX_ZIP_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_ZIP_COMPRESSION_RATIO = 200.0
MAX_REDIRECTS = 3

ONEBUILDING_REGION_PAGES = [
    "WMO_Region_1_Africa/default.html",
    "WMO_Region_2_Asia/default.html",
    "WMO_Region_3_South_America/default.html",
    "WMO_Region_4_North_and_Central_America/default.html",
    "WMO_Region_5_Southwest_Pacific/default.html",
    "WMO_Region_6_Europe/default.html",
    "WMO_Region_7_Antarctica/default.html",
]
ONEBUILDING_REGION_OPTIONS = {
    "Africa": "WMO_Region_1_Africa/default.html",
    "Asia": "WMO_Region_2_Asia/default.html",
    "South America": "WMO_Region_3_South_America/default.html",
    "North and Central America": "WMO_Region_4_North_and_Central_America/default.html",
    "Southwest Pacific": "WMO_Region_5_Southwest_Pacific/default.html",
    "Europe": "WMO_Region_6_Europe/default.html",
    "Antarctica": "WMO_Region_7_Antarctica/default.html",
}


@dataclass(frozen=True)
class ClimateFilePayload:
    """Downloaded or uploaded climate-file payload ready for EPW parsing.

    Attributes
    ----------
    name:
        Display filename used by the UI.
    payload:
        Raw EPW bytes.
    source:
        Human-readable source description.
    """

    name: str
    payload: bytes
    source: str


@dataclass(frozen=True)
class DownloadResult:
    """Result of a climate-file download or archive extraction.

    Attributes
    ----------
    file_name:
        Extracted EPW filename.
    payload:
        Raw EPW bytes.
    extracted_from:
        ZIP filename when the EPW was extracted from an archive.
    content_type:
        HTTP content type returned by the server.
    source_url:
        Original download URL.
    """

    file_name: str
    payload: bytes
    extracted_from: str | None
    content_type: str | None
    source_url: str


@dataclass(frozen=True)
class CatalogBuildReport:
    """Summary of a Climate.OneBuilding catalog build operation.

    ``failed_catalog_count`` counts logical catalogs for which no published
    representation could be parsed. ``source_file_failure_count`` counts raw
    XLSX/KML failures even when another representation recovered the catalog.
    """

    station_count: int
    xlsx_catalog_count: int
    kml_catalog_count: int
    failed_catalog_count: int
    source_file_failure_count: int
    recovered_source_file_failure_count: int
    cache_path: Path


def catalog_cache_path() -> Path:
    """Return the writable path used for the Climate.OneBuilding station cache."""
    return ONEBUILDING_CACHE_PATH


def _validate_onebuilding_url(url: str) -> str:
    """Return a normalized Climate.OneBuilding HTTPS URL or reject it."""
    clean_url = url.strip()
    if not clean_url:
        raise ValueError("The download URL is empty.")

    parsed = urlparse(clean_url)
    if parsed.scheme.lower() != "https":
        raise ValueError("Climate downloads must use HTTPS.")
    if parsed.username or parsed.password:
        raise ValueError("Credential-bearing download URLs are not allowed.")
    hostname = (parsed.hostname or "").rstrip(".").lower()
    if hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise ValueError("Climate downloads are restricted to climate.onebuilding.org.")
    if parsed.port not in (None, 443):
        raise ValueError("Non-standard download ports are not allowed.")
    return clean_url


def _download_limited(url: str, timeout_s: int = 60) -> tuple[bytes, str | None, str]:
    """Download bounded bytes while validating every redirect target."""
    current_url = _validate_onebuilding_url(url)

    for redirect_count in range(MAX_REDIRECTS + 1):
        response = requests.get(
            current_url,
            timeout=(10, timeout_s),
            headers={"User-Agent": USER_AGENT},
            stream=True,
            allow_redirects=False,
        )
        try:
            if 300 <= response.status_code < 400:
                location = response.headers.get("location")
                if not location:
                    response.raise_for_status()
                if redirect_count >= MAX_REDIRECTS:
                    raise ValueError("The climate download exceeded the allowed redirect count.")
                current_url = _validate_onebuilding_url(urljoin(current_url, location))
                continue

            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    declared_size = int(content_length)
                except ValueError:
                    declared_size = 0
                if declared_size > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"The climate download exceeds the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MiB limit."
                    )

            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > MAX_DOWNLOAD_BYTES:
                    raise ValueError(
                        f"The climate download exceeds the {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MiB limit."
                    )
                chunks.append(chunk)

            return b"".join(chunks), response.headers.get("content-type"), current_url
        finally:
            response.close()

    raise ValueError("The climate download could not be completed safely.")


def _http_get(url: str, timeout_s: int = 60) -> requests.Response:
    """Execute a GET request with a consistent User-Agent and status check."""
    response = requests.get(url, timeout=timeout_s, headers={"User-Agent": USER_AGENT})
    response.raise_for_status()
    return response


def _safe_file_name_from_url(url: str) -> str:
    """Infer a readable filename from a URL path."""
    parsed = urlparse(url)
    name = Path(parsed.path).name
    return name or "downloaded_climate_file.epw"


def _extract_epw_from_zip(zip_payload: bytes, archive_name: str) -> tuple[str, bytes]:
    """Read one bounded EPW member from a ZIP archive without filesystem extraction."""
    try:
        with ZipFile(BytesIO(zip_payload)) as archive:
            members = archive.infolist()
            if len(members) > MAX_ZIP_MEMBERS:
                raise ValueError(
                    f"The archive '{archive_name}' contains too many members ({len(members)} > {MAX_ZIP_MEMBERS})."
                )

            total_uncompressed = sum(info.file_size for info in members)
            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
                raise ValueError(
                    f"The archive '{archive_name}' exceeds the uncompressed size limit."
                )

            candidates = []
            for info in members:
                if info.is_dir() or not info.filename.lower().endswith(".epw"):
                    continue
                member_path = PurePosixPath(info.filename)
                if member_path.is_absolute() or ".." in member_path.parts:
                    raise ValueError(f"The archive '{archive_name}' contains an unsafe EPW path.")
                if info.flag_bits & 0x1:
                    raise ValueError(f"The archive '{archive_name}' contains an encrypted EPW member.")
                if info.file_size > MAX_EPW_BYTES:
                    raise ValueError(f"The EPW member in '{archive_name}' exceeds the EPW size limit.")
                if info.compress_size == 0 and info.file_size > 0:
                    raise ValueError(f"The archive '{archive_name}' has an invalid compressed EPW member.")
                if info.compress_size > 0 and info.file_size / info.compress_size > MAX_ZIP_COMPRESSION_RATIO:
                    raise ValueError(f"The archive '{archive_name}' has a suspicious EPW compression ratio.")
                candidates.append(info)

            if not candidates:
                raise ValueError(f"The archive '{archive_name}' does not contain an EPW file.")

            selected = sorted(candidates, key=lambda item: (PurePosixPath(item.filename).parent.parts, len(item.filename)))[0]
            epw_payload = archive.read(selected)
            epw_name = Path(selected.filename).name
            validate_epw_payload(epw_payload, epw_name)
            return epw_name, epw_payload
    except BadZipFile as exc:
        raise ValueError(f"The downloaded file '{archive_name}' is not a valid ZIP archive.") from exc


def download_climate_file(url: str, timeout_s: int = 120) -> DownloadResult:
    """Download an EPW file or a ZIP archive with an EPW file.

    The function is used internally for station downloads. It accepts plain EPW
    files and ZIP archives that contain at least one EPW file.

    Parameters
    ----------
    url:
        URL to either an ``.epw`` file or a ``.zip`` archive containing an EPW.
    timeout_s:
        HTTP timeout in seconds.

    Returns
    -------
    DownloadResult
        Extracted EPW payload and metadata.
    """
    clean_url = _validate_onebuilding_url(url)
    payload, content_type, final_url = _download_limited(clean_url, timeout_s=timeout_s)
    url_name = _safe_file_name_from_url(final_url)
    lower_name = url_name.lower()

    if lower_name.endswith(".zip") or (content_type and "zip" in content_type.lower()):
        epw_name, epw_payload = _extract_epw_from_zip(payload, url_name)
        return DownloadResult(epw_name, epw_payload, url_name, content_type, final_url)

    if lower_name.endswith(".epw") or payload[:32].decode("utf-8", errors="ignore").upper().startswith("LOCATION"):
        file_name = url_name if lower_name.endswith(".epw") else "downloaded_weather.epw"
        validate_epw_payload(payload, file_name)
        return DownloadResult(file_name, payload, None, content_type, final_url)

    try:
        epw_name, epw_payload = _extract_epw_from_zip(payload, url_name)
        return DownloadResult(epw_name, epw_payload, url_name, content_type, final_url)
    except ValueError:
        header = payload[:128].decode("utf-8", errors="ignore").upper()
        if header.startswith("LOCATION"):
            validate_epw_payload(payload, "downloaded_weather.epw")
            return DownloadResult("downloaded_weather.epw", payload, None, content_type, final_url)

    raise ValueError("The downloaded file is neither an EPW file nor a ZIP archive containing an EPW file.")


def download_station_epw(station: pd.Series) -> DownloadResult:
    """Download and extract the EPW file for a selected catalog station."""
    return download_climate_file(str(station["download_url"]))


def load_station_catalog(path: str | Path | None = None) -> pd.DataFrame:
    """Load the bundled fallback EPW station catalog.

    This small CSV is used only as a fallback if the online Climate.OneBuilding
    catalog has not yet been built.
    """
    catalog_path = Path(path) if path is not None else CATALOG_PATH
    df = pd.read_csv(catalog_path)
    return _finalize_catalog(df)


def load_onebuilding_catalog(path: str | Path | None = None, fallback_to_bundled: bool = True) -> pd.DataFrame:
    """Load the cached Climate.OneBuilding catalog.

    Parameters
    ----------
    path:
        Optional CSV cache path. If omitted, the user cache location is used.
    fallback_to_bundled:
        If ``True``, return the bundled small catalog when no online cache is
        available yet.

    Returns
    -------
    pandas.DataFrame
        Station catalog ready for map display and station selection.
    """
    cache_path = Path(path) if path is not None else ONEBUILDING_CACHE_PATH
    if cache_path.exists():
        return _finalize_catalog(pd.read_csv(cache_path))
    if fallback_to_bundled:
        return load_station_catalog()
    return _empty_catalog()


def save_onebuilding_catalog(catalog: pd.DataFrame, path: str | Path | None = None) -> Path:
    """Save a station catalog to the local cache path and return that path."""
    cache_path = Path(path) if path is not None else ONEBUILDING_CACHE_PATH
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    _finalize_catalog(catalog).to_csv(cache_path, index=False)
    return cache_path


def build_onebuilding_station_catalog(
    progress_callback: Callable[[str], None] | None = None,
    timeout_s: int = 60,
    region_pages: list[str] | None = None,
) -> CatalogBuildReport:
    """Build and cache a global station catalog from Climate.OneBuilding.

    The crawler reads public WMO-region pages, extracts links to XLSX and KML
    catalogs, parses each catalog and writes a normalized CSV cache. XLSX files
    are preferred because they usually contain richer metadata; KML files are
    used as a fallback and to catch datasets not represented in spreadsheets.

    Parameters
    ----------
    progress_callback:
        Optional callback receiving short status messages for the UI.
    timeout_s:
        HTTP timeout per catalog request.

    Returns
    -------
    CatalogBuildReport
        Counts of parsed catalogs and station records.
    """
    def report(message: str) -> None:
        if progress_callback is not None:
            progress_callback(message)

    catalog_links = discover_onebuilding_catalog_links(timeout_s=timeout_s, region_pages=region_pages)
    frames: list[pd.DataFrame] = []
    xlsx_ok = 0
    kml_ok = 0
    source_file_failures = 0
    successful_logical_catalogs: set[str] = set()
    failed_files_by_logical_catalog: dict[str, list[str]] = {}

    def logical_catalog_key(url: str) -> str:
        path = urlparse(url).path
        return path.rsplit(".", 1)[0].lower()

    for index, item in enumerate(catalog_links, start=1):
        url = item["url"]
        kind = item["kind"]
        logical_key = logical_catalog_key(url)
        report(f"Reading {index}/{len(catalog_links)}: {Path(urlparse(url).path).name}")
        try:
            response = _http_get(url, timeout_s=timeout_s)
            if kind == "xlsx":
                frame = _catalog_from_xlsx(response.content, source_url=url, source_label=item["label"])
                xlsx_ok += 1
            else:
                frame = _catalog_from_kml(response.content, source_url=url, source_label=item["label"])
                kml_ok += 1
            if frame.empty:
                raise ValueError("parsed catalog contains zero usable station records")
            frames.append(frame)
            successful_logical_catalogs.add(logical_key)
        except Exception as exc:
            source_file_failures += 1
            failed_files_by_logical_catalog.setdefault(logical_key, []).append(url)
            report(
                f"FAILED source representation: {url} [{kind}] "
                f"{type(exc).__name__}: {exc}"
            )

    uncovered_logical_catalogs = {
        key: urls
        for key, urls in failed_files_by_logical_catalog.items()
        if key not in successful_logical_catalogs
    }
    failed_logical_catalog_count = len(uncovered_logical_catalogs)
    unrecovered_source_failures = sum(len(urls) for urls in uncovered_logical_catalogs.values())
    recovered_source_failures = source_file_failures - unrecovered_source_failures

    for key, urls in sorted(uncovered_logical_catalogs.items()):
        report(f"UNRECOVERED logical catalog: {key} | failed representations: {len(urls)}")
    if recovered_source_failures:
        report(
            f"Recovered {recovered_source_failures} failed source representation(s) "
            "through another published representation of the same logical catalog."
        )

    if frames:
        catalog = pd.concat(frames, ignore_index=True)
        catalog = _finalize_catalog(catalog)
    else:
        catalog = _empty_catalog()

    cache_path = save_onebuilding_catalog(catalog)
    return CatalogBuildReport(
        station_count=len(catalog),
        xlsx_catalog_count=xlsx_ok,
        kml_catalog_count=kml_ok,
        failed_catalog_count=failed_logical_catalog_count,
        source_file_failure_count=source_file_failures,
        recovered_source_file_failure_count=recovered_source_failures,
        cache_path=cache_path,
    )


def discover_onebuilding_catalog_links(timeout_s: int = 60, region_pages: list[str] | None = None) -> list[dict[str, str]]:
    """Discover KML and XLSX catalog links from selected WMO-region pages."""
    links: list[dict[str, str]] = []
    seen: set[str] = set()

    for page in (region_pages or ONEBUILDING_REGION_PAGES):
        page_url = urljoin(BASE_URL, page)
        try:
            response = _http_get(page_url, timeout_s=timeout_s)
        except Exception:
            continue
        soup = BeautifulSoup(response.text, "html.parser")
        page_title = soup.get_text(" ", strip=True).split("Climate.OneBuilding.Org")[0].strip() or page
        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"])
            absolute = urljoin(page_url, href)
            lower = absolute.lower()
            if not (lower.endswith(".xlsx") or lower.endswith(".kml")):
                continue
            if absolute in seen:
                continue
            seen.add(absolute)
            links.append({
                "url": absolute,
                "kind": "xlsx" if lower.endswith(".xlsx") else "kml",
                "label": f"{page_title} | {anchor.get_text(' ', strip=True)}",
            })
    return links


def _empty_catalog() -> pd.DataFrame:
    """Return an empty catalog with the normalized schema."""
    return pd.DataFrame(
        columns=[
            "station_id",
            "name",
            "country",
            "region",
            "source",
            "dataset",
            "latitude",
            "longitude",
            "elevation_m",
            "download_url",
            "catalog_url",
            "notes",
        ]
    )


def _finalize_catalog(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize, clean and de-duplicate station catalog records."""
    if df is None or df.empty:
        return _empty_catalog()

    result = df.copy()
    for column in _empty_catalog().columns:
        if column not in result.columns:
            result[column] = ""

    result["latitude"] = pd.to_numeric(result["latitude"], errors="coerce")
    result["longitude"] = pd.to_numeric(result["longitude"], errors="coerce")
    result["elevation_m"] = pd.to_numeric(result["elevation_m"], errors="coerce")
    result = result.dropna(subset=["latitude", "longitude", "download_url"])
    result = result[result["download_url"].astype(str).str.startswith(("http://", "https://"))]

    for column in ["name", "country", "region", "source", "dataset", "download_url", "catalog_url", "notes"]:
        result[column] = result[column].astype(str).str.strip()

    # Climate.OneBuilding often publishes the same logical catalog as both KML
    # and XLSX. XLSX carries richer country/region metadata, while KML is the
    # fallback for records not represented in a spreadsheet. Give spreadsheet
    # rows deterministic precedence before URL-level de-duplication.
    result["__metadata_priority"] = result["notes"].str.contains("; sheet=", regex=False).astype(int)
    result = result.sort_values("__metadata_priority", ascending=False, kind="stable")

    inferred = result.apply(_infer_metadata_from_url, axis=1, result_type="expand")
    for column in ["name", "country", "dataset"]:
        empty = result[column].eq("") | result[column].eq("nan")
        result.loc[empty, column] = inferred.loc[empty, column]

    result["station_id"] = result.apply(_make_station_id, axis=1)
    result = result.drop_duplicates(subset=["download_url"], keep="first")
    result = result.drop_duplicates(subset=["station_id"], keep="first")
    result = result.drop(columns=["__metadata_priority"], errors="ignore")
    return result[_empty_catalog().columns].sort_values(["country", "name", "dataset"]).reset_index(drop=True)


def _infer_metadata_from_url(row: pd.Series) -> pd.Series:
    """Infer missing display metadata from a Climate.OneBuilding file URL."""
    url = str(row.get("download_url", ""))
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    file_stem = Path(path_parts[-1]).stem if path_parts else "weather_file"
    file_stem = file_stem.replace(".epw", "")
    country = ""
    dataset = ""
    tokens = file_stem.split("_") if "_" in file_stem else [file_stem]

    # Climate.OneBuilding weather filenames conventionally begin with a
    # three-letter country/territory code (for example CAN_AB_..., USA_TX_...,
    # AUS_NSW_...). Prefer that stable country-level token over a nearby URL
    # directory, which can be a state/province such as AB_Alberta or TX_Texas.
    filename_country = tokens[0].upper() if tokens else ""
    if re.fullmatch(r"[A-Z]{3}", filename_country):
        country = filename_country
    elif len(path_parts) >= 2:
        country = path_parts[-3] if len(path_parts) >= 3 else path_parts[-2]
        if len(country) != 3:
            country = path_parts[-2]

    if "_" in file_stem:
        dataset = tokens[-1]
        name = " ".join(tokens[2:-1]) if len(tokens) > 3 else file_stem
    else:
        name = file_stem
    return pd.Series({"name": name.replace(".", " "), "country": country, "dataset": dataset})


def _make_station_id(row: pd.Series) -> str:
    """Create a stable station identifier from URL and station metadata."""
    url_name = Path(urlparse(str(row.get("download_url", ""))).path).stem
    raw = url_name or f"{row.get('country', '')}_{row.get('name', '')}_{row.name}"
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_")[:160]


def _catalog_from_xlsx(payload: bytes, source_url: str, source_label: str) -> pd.DataFrame:
    """Parse a Climate.OneBuilding XLSX station catalog.

    The parser reads visible cell values with pandas and hyperlink targets with
    openpyxl. This is necessary because several spreadsheet catalogs expose the
    ZIP download as a hyperlink rather than as visible text.
    """
    frames: list[pd.DataFrame] = []
    workbook = pd.ExcelFile(BytesIO(payload))
    hyperlink_lookup = _xlsx_hyperlink_lookup(payload, source_url)
    for sheet_name in workbook.sheet_names:
        header_row = _detect_xlsx_header_row(payload, sheet_name)
        if header_row is None:
            continue
        sheet = pd.read_excel(BytesIO(payload), sheet_name=sheet_name, header=header_row)
        sheet["__hyperlinks"] = _hyperlinks_for_dataframe_rows(hyperlink_lookup, sheet_name, header_row, len(sheet))
        normalized = _normalize_tabular_catalog(sheet, source_url=source_url, source_label=source_label, sheet_name=sheet_name)
        if not normalized.empty:
            frames.append(normalized)
    return pd.concat(frames, ignore_index=True) if frames else _empty_catalog()


def _xlsx_hyperlink_lookup(payload: bytes, source_url: str) -> dict[tuple[str, int], str]:
    """Return concatenated hyperlink targets by worksheet name and one-based row number."""
    lookup: dict[tuple[str, int], list[str]] = {}
    workbook = load_workbook(BytesIO(payload), read_only=False, data_only=True)
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                if cell.hyperlink and cell.hyperlink.target:
                    target = urljoin(source_url, str(cell.hyperlink.target))
                    lookup.setdefault((worksheet.title, int(cell.row)), []).append(target)
    return {key: " ".join(values) for key, values in lookup.items()}


def _hyperlinks_for_dataframe_rows(lookup: dict[tuple[str, int], str], sheet_name: str, header_row: int, row_count: int) -> list[str]:
    """Map openpyxl worksheet-row hyperlinks to pandas dataframe rows."""
    # pandas header_row is zero-based; the first data row is one row after the
    # header in Excel's one-based indexing.
    first_excel_row = header_row + 2
    return [lookup.get((sheet_name, first_excel_row + offset), "") for offset in range(row_count)]


def _detect_xlsx_header_row(payload: bytes, sheet_name: str) -> int | None:
    """Detect the header row in an XLSX catalog sheet using keyword scoring."""
    preview = pd.read_excel(BytesIO(payload), sheet_name=sheet_name, header=None, nrows=30)
    for idx, row in preview.iterrows():
        values = " ".join(str(value).lower() for value in row.dropna().tolist())
        has_coordinate = any(token in values for token in ["latitude", "lat", "longitude", "lon"])
        has_file = any(token in values for token in ["url", "download", "zip", "epw", "weather"])
        if has_coordinate and has_file:
            return int(idx)
    return None


def _normalize_tabular_catalog(sheet: pd.DataFrame, source_url: str, source_label: str, sheet_name: str) -> pd.DataFrame:
    """Normalize arbitrary spreadsheet columns to the internal station schema."""
    if sheet.empty:
        return _empty_catalog()
    df = sheet.dropna(how="all").copy()
    df.columns = [str(column).strip() for column in df.columns]

    lat_col = _find_column(df, ["latitude", "lat"])
    lon_col = _find_column(df, ["longitude", "long", "lon"])
    url_col = _find_column(df, ["download", "url", "link", "zip", "epw"])
    if lat_col is None or lon_col is None:
        return _empty_catalog()

    records: list[dict[str, object]] = []
    for _, row in df.iterrows():
        download_url = _extract_url_from_row(row, preferred_column=url_col)
        if not download_url:
            continue
        latitude = pd.to_numeric(row.get(lat_col), errors="coerce")
        longitude = pd.to_numeric(row.get(lon_col), errors="coerce")
        if pd.isna(latitude) or pd.isna(longitude):
            continue
        records.append(
            {
                "station_id": "",
                "name": _first_non_empty(row, df, ["location", "city", "station", "name", "weather file", "epw"]),
                "country": _first_non_empty(row, df, ["country", "nation", "iso"]),
                "region": _first_non_empty(row, df, ["state", "province", "region", "subdivision"]),
                "source": "Climate.OneBuilding",
                "dataset": _first_non_empty(row, df, ["dataset", "source", "data source", "type"]),
                "latitude": float(latitude),
                "longitude": float(longitude),
                "elevation_m": _numeric_or_blank(_first_non_empty(row, df, ["elevation", "elev", "altitude", "height"])),
                "download_url": download_url,
                "catalog_url": source_url,
                "notes": f"{source_label}; sheet={sheet_name}",
            }
        )
    return pd.DataFrame(records) if records else _empty_catalog()


def _find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Find the first column whose lowercase name contains a candidate token."""
    lowered = {column: str(column).lower() for column in df.columns}
    for token in candidates:
        for column, value in lowered.items():
            if token in value:
                return column
    return None


def _first_non_empty(row: pd.Series, df: pd.DataFrame, candidates: list[str]) -> str:
    """Return the first non-empty value from columns matching candidate tokens."""
    for token in candidates:
        for column in df.columns:
            if token in str(column).lower():
                value = row.get(column)
                if pd.notna(value) and str(value).strip():
                    return str(value).strip()
    return ""


def _numeric_or_blank(value: object) -> float | str:
    """Convert a value to float when possible; otherwise return an empty string."""
    number = pd.to_numeric(value, errors="coerce")
    return float(number) if not pd.isna(number) else ""


def _extract_url_from_row(row: pd.Series, preferred_column: str | None = None) -> str:
    """Extract a ZIP/EPW URL from one spreadsheet row."""
    values: list[str] = []
    if preferred_column is not None:
        values.append(str(row.get(preferred_column, "")))
    values.extend(str(value) for value in row.tolist())
    joined = " ".join(values)
    matches = re.findall(r"https?://[^\s'\"<>]+(?:\.zip|\.epw)", joined, flags=re.IGNORECASE)
    if matches:
        return html.unescape(matches[0]).rstrip("),.;")
    return ""


def _catalog_from_kml(payload: bytes, source_url: str, source_label: str) -> pd.DataFrame:
    """Parse a Climate.OneBuilding KML station catalog."""
    root = ET.fromstring(payload)
    namespace = _kml_namespace(root)
    placemark_path = f".//{{{namespace}}}Placemark" if namespace else ".//Placemark"
    name_path = f"{{{namespace}}}name" if namespace else "name"
    description_path = f"{{{namespace}}}description" if namespace else "description"
    coordinates_path = f".//{{{namespace}}}coordinates" if namespace else ".//coordinates"

    records: list[dict[str, object]] = []
    for placemark in root.findall(placemark_path):
        name = _xml_text(placemark.find(name_path))
        description = _xml_text(placemark.find(description_path))
        coordinates = _xml_text(placemark.find(coordinates_path))
        if not coordinates:
            continue
        parts = coordinates.split()[0].split(",")
        if len(parts) < 2:
            continue
        longitude = pd.to_numeric(parts[0], errors="coerce")
        latitude = pd.to_numeric(parts[1], errors="coerce")
        elevation = pd.to_numeric(parts[2], errors="coerce") if len(parts) > 2 else pd.NA
        if pd.isna(latitude) or pd.isna(longitude):
            continue
        download_url = _extract_url_from_text(description)
        if not download_url:
            continue
        inferred = _infer_metadata_from_url(pd.Series({"download_url": download_url}))
        records.append(
            {
                "station_id": "",
                "name": name or inferred["name"],
                "country": inferred["country"],
                "region": "",
                "source": "Climate.OneBuilding",
                "dataset": inferred["dataset"],
                "latitude": float(latitude),
                "longitude": float(longitude),
                "elevation_m": float(elevation) if not pd.isna(elevation) else "",
                "download_url": html.unescape(download_url),
                "catalog_url": source_url,
                "notes": source_label,
            }
        )
    return pd.DataFrame(records) if records else _empty_catalog()


def _kml_namespace(root: ET.Element) -> str:
    """Return the XML namespace URI used by a KML document."""
    if root.tag.startswith("{"):
        return root.tag.split("}", 1)[0].strip("{")
    return ""


def _xml_text(element: ET.Element | None) -> str:
    """Return stripped text from an XML element."""
    return "" if element is None or element.text is None else element.text.strip()


def _extract_url_from_text(text: str) -> str:
    """Extract the first EPW/ZIP URL from arbitrary text or HTML."""
    unescaped = html.unescape(text)
    matches = re.findall(r"https?://[^\s'\"<>]+(?:\.zip|\.epw)", unescaped, flags=re.IGNORECASE)
    return matches[0].rstrip("),.;") if matches else ""


def filter_station_catalog(
    catalog: pd.DataFrame,
    search_text: str = "",
    countries: Iterable[str] | None = None,
    datasets: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Filter station catalog by free text, country list and dataset list."""
    df = catalog.copy()
    if countries:
        country_list = list(countries)
        if country_list:
            df = df[df["country"].isin(country_list)]
    if datasets:
        dataset_list = list(datasets)
        if dataset_list:
            df = df[df["dataset"].isin(dataset_list)]
    if search_text.strip():
        token = search_text.strip().lower()
        searchable = (
            df["name"].fillna("")
            + " "
            + df["country"].fillna("")
            + " "
            + df.get("region", pd.Series("", index=df.index)).fillna("")
            + " "
            + df.get("dataset", pd.Series("", index=df.index)).fillna("")
            + " "
            + df.get("station_id", pd.Series("", index=df.index)).fillna("")
        ).str.lower()
        df = df[searchable.str.contains(token, regex=False)]
    return df.reset_index(drop=True)


def nearest_station(catalog: pd.DataFrame, latitude: float, longitude: float) -> pd.Series:
    """Return the station nearest to a clicked map location using planar distance."""
    if catalog.empty:
        raise ValueError("Cannot find a nearest station in an empty catalog.")
    lat = catalog["latitude"].astype(float)
    lon = catalog["longitude"].astype(float)
    mean_lat_rad = max(abs(lat.mean()), 1.0)
    distances = (lat - latitude) ** 2 + ((lon - longitude) * mean_lat_rad / 90.0) ** 2
    return catalog.loc[distances.idxmin()]
