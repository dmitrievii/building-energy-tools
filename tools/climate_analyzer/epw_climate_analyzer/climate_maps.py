"""Source geometry for the shared OSM map; locations never imply admission."""
from __future__ import annotations

import csv
import io
import math


def donor_markers(rows):
    return [{"latitude": r["latitude"], "longitude": r["longitude"],
             "selected": bool(r.get("selected")), "label": f"{r.get('station_name', '')} · {r['station_id']}",
             "detail": f"{r.get('station_name', '')} · {r['station_id']} · {r.get('distance_km', 0):.2f} km · "
                       f"T/RH altitude {r.get('temperature_elevation_m')} m · "
                       f"{'selected donor' if r.get('selected') else 'candidate; see admission report'}"}
            for r in rows if r.get("latitude") is not None and r.get("longitude") is not None]


def epw_markers(entries):
    """Header-only preview. Eligibility still requires the complete year checks."""
    rows = []
    for name, body in entries[:20]:
        try:
            header = next(csv.reader(io.StringIO(body[:4096].decode("utf-8-sig"))))
            lat, lon, height = float(header[6]), float(header[7]), float(header[9])
            if header[0] != "LOCATION" or not all(map(math.isfinite, (lat, lon, height))) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
                continue
            rows.append({"latitude": lat, "longitude": lon, "selected": False,
                         "label": header[1] or name, "detail": f"{name} · {height:g} m · uploaded candidate; not yet admitted"})
        except (ValueError, IndexError, UnicodeError, StopIteration):
            continue
    return rows


def grid_markers(report):
    geometry = report.get("source_geometry", {})
    point = geometry.get("background_cell")
    if not point:
        return []
    return [{"latitude": point[0], "longitude": point[1], "selected": True,
             "nominal_resolution_deg": .25,
             "label": "ERA5 background · returned grid point",
             "detail": f"ERA5 via Open-Meteo · {point[0]:.5f}°, {point[1]:.5f}° · provider height "
                       f"{geometry.get('elevation_m_provider_response_proxy')} m; no local height correction"}]


def render_source_map(st, latitude, longitude, elevation_m, sources=(), *, key="result"):
    from .location_picker import render_location_map, LATITUDE, LONGITUDE, HEIGHT, EPOCH
    render_location_map({LATITUDE: latitude, LONGITUDE: longitude, HEIGHT: elevation_m, EPOCH: 0},
                        sources=sources, editable=False, key_suffix="_"+key)
