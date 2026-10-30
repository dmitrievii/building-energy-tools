"""Bounded terrain metadata lookup, independent of weather acquisition."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from urllib.parse import urlencode

import requests
import streamlit as st

ENDPOINT = "https://api.open-meteo.com/v1/elevation"
SOURCE = "Copernicus DEM GLO-90 (2021), 90 m, via Open-Meteo; terrain/surface height proxy; sensor datum unconfirmed"
MANUAL = "User supplied site elevation; vertical datum unconfirmed"


@st.cache_data(show_spinner=False, ttl=86400, max_entries=256)
def lookup_elevation(latitude: float, longitude: float) -> dict:
    """Cache metadata only. Never fill a failed lookup with zero or a grid height."""
    if not (math.isfinite(latitude) and math.isfinite(longitude)
            and -90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise ValueError("Invalid coordinates for elevation lookup")
    url = ENDPOINT + "?" + urlencode({"latitude": f"{latitude:.6f}", "longitude": f"{longitude:.6f}"})
    with requests.get(url, timeout=(3, 8), allow_redirects=False, stream=True) as response:
        if response.status_code != 200:
            raise ValueError(f"Elevation service returned HTTP {response.status_code}")
        raw = b""
        for chunk in response.iter_content(chunk_size=4096):
            raw += chunk
            if len(raw) > 16384:
                raise ValueError("Elevation response is too large")
    if not raw or len(raw) > 16384:
        raise ValueError("Elevation response size is invalid")
    values = json.loads(raw).get("elevation")
    if not isinstance(values, list) or len(values) != 1 or isinstance(values[0], bool):
        raise ValueError("Elevation service did not return one height")
    value = values[0]
    if not isinstance(value, (int, float)) or not math.isfinite(value) or not -500 <= value <= 9000:
        raise ValueError("Elevation is missing or outside the supported range")
    return {"latitude": latitude, "longitude": longitude, "elevation_m": float(value),
            "source": SOURCE, "url": url, "retrieved_utc": datetime.now(timezone.utc).isoformat(),
            "response_sha256": sha256(raw).hexdigest(), "response": raw.decode("utf-8")}
