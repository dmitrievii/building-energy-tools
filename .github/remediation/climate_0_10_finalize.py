from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "tools" / "climate_analyzer" / "app.py"
SOURCES = ROOT / "tools" / "climate_analyzer" / "epw_climate_analyzer" / "climate_sources.py"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def patch_app() -> None:
    text = APP.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''            min_value=1000,\n            max_value=50000,\n            value=int(st.session_state.get("station_selectable_cluster_limit", 20000)),\n            step=1000,\n''',
        '''            min_value=1000,\n            max_value=100000,\n            value=int(st.session_state.get("station_selectable_cluster_limit", 50000)),\n            step=5000,\n''',
        "map capacity slider",
    )
    text = replace_once(
        text,
        '''    if len(station_groups_for_map) > int(st.session_state.get("station_selectable_cluster_limit", 20000)):\n''',
        '''    if len(station_groups_for_map) > int(st.session_state.get("station_selectable_cluster_limit", 50000)):\n''',
        "map capacity gate",
    )
    APP.write_text(text, encoding="utf-8")


def patch_sources() -> None:
    text = SOURCES.read_text(encoding="utf-8")

    old = '''    for column in ["name", "country", "region", "source", "dataset", "download_url", "catalog_url", "notes"]:\n        result[column] = result[column].astype(str).str.strip()\n\n    inferred = result.apply(_infer_metadata_from_url, axis=1, result_type="expand")\n'''
    new = '''    for column in ["name", "country", "region", "source", "dataset", "download_url", "catalog_url", "notes"]:\n        result[column] = result[column].astype(str).str.strip()\n\n    # Climate.OneBuilding often publishes the same logical catalog as both KML\n    # and XLSX. XLSX carries richer country/region metadata, while KML is the\n    # fallback for records not represented in a spreadsheet. Give spreadsheet\n    # rows deterministic precedence before URL-level de-duplication.\n    result["__metadata_priority"] = result["notes"].str.contains("; sheet=", regex=False).astype(int)\n    result = result.sort_values("__metadata_priority", ascending=False, kind="stable")\n\n    inferred = result.apply(_infer_metadata_from_url, axis=1, result_type="expand")\n'''
    text = replace_once(text, old, new, "XLSX metadata precedence")

    old = '''    result["station_id"] = result.apply(_make_station_id, axis=1)\n    result = result.drop_duplicates(subset=["download_url"], keep="first")\n    result = result.drop_duplicates(subset=["station_id"], keep="first")\n    return result[_empty_catalog().columns].sort_values(["country", "name", "dataset"]).reset_index(drop=True)\n'''
    new = '''    result["station_id"] = result.apply(_make_station_id, axis=1)\n    result = result.drop_duplicates(subset=["download_url"], keep="first")\n    result = result.drop_duplicates(subset=["station_id"], keep="first")\n    result = result.drop(columns=["__metadata_priority"], errors="ignore")\n    return result[_empty_catalog().columns].sort_values(["country", "name", "dataset"]).reset_index(drop=True)\n'''
    text = replace_once(text, old, new, "metadata priority cleanup")

    old = '''    country = ""\n    dataset = ""\n    if len(path_parts) >= 2:\n        country = path_parts[-3] if len(path_parts) >= 3 else path_parts[-2]\n        if len(country) != 3:\n            country = path_parts[-2]\n    if "_" in file_stem:\n        tokens = file_stem.split("_")\n        dataset = tokens[-1]\n        name = " ".join(tokens[2:-1]) if len(tokens) > 3 else file_stem\n    else:\n        name = file_stem\n'''
    new = '''    country = ""\n    dataset = ""\n    tokens = file_stem.split("_") if "_" in file_stem else [file_stem]\n\n    # Climate.OneBuilding weather filenames conventionally begin with a\n    # three-letter country/territory code (for example CAN_AB_..., USA_TX_...,\n    # AUS_NSW_...). Prefer that stable country-level token over a nearby URL\n    # directory, which can be a state/province such as AB_Alberta or TX_Texas.\n    filename_country = tokens[0].upper() if tokens else ""\n    if re.fullmatch(r"[A-Z]{3}", filename_country):\n        country = filename_country\n    elif len(path_parts) >= 2:\n        country = path_parts[-3] if len(path_parts) >= 3 else path_parts[-2]\n        if len(country) != 3:\n            country = path_parts[-2]\n\n    if "_" in file_stem:\n        dataset = tokens[-1]\n        name = " ".join(tokens[2:-1]) if len(tokens) > 3 else file_stem\n    else:\n        name = file_stem\n'''
    text = replace_once(text, old, new, "country-level URL fallback")

    SOURCES.write_text(text, encoding="utf-8")


def main() -> None:
    patch_app()
    patch_sources()
    print("CLIMATE-0.10 final remediation patch applied")


if __name__ == "__main__":
    main()
