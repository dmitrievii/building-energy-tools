from __future__ import annotations

import unittest
from types import SimpleNamespace

import pandas as pd

from epw_climate_analyzer.geosphere_monthly_request_surface import (
    _STATION_KEY,
    _filtered_station_ids,
    _station_and_bundle,
)


class _FakeStreamlit:
    def __init__(self, state=None):
        self.session_state = dict(state or {})


class _FakeLegacy:
    def __init__(self, stations, catalog):
        self._bundle = (
            {"metadata": True},
            {"tl_mittel": SimpleNamespace(canonical_name="tl_mittel", description="temperature")},
            stations,
            catalog,
            {},
            {},
        )
        self.calls = 0

    def cached_geosphere_metadata_bundle(self):
        self.calls += 1
        return self._bundle


class MonthlyDefaultStationSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.stations = [
            SimpleNamespace(station_id="105", name="Wien Hohe Warte"),
            SimpleNamespace(station_id="112", name="Graz Universität"),
        ]
        self.catalog = pd.DataFrame(
            [
                {"station_id": "105", "name": "Wien Hohe Warte", "state": "Wien"},
                {"station_id": "112", "name": "Graz Universität", "state": "Steiermark"},
            ]
        )

    def test_fresh_session_uses_same_first_station_as_mature_browser(self):
        st = _FakeStreamlit()
        legacy = _FakeLegacy(self.stations, self.catalog)

        bundle = _station_and_bundle(legacy, st)

        self.assertIsNotNone(bundle)
        self.assertEqual(bundle[2].station_id, "105")
        self.assertEqual(st.session_state[_STATION_KEY], "105")
        self.assertEqual(legacy.calls, 1)

    def test_search_filter_controls_default_station_fallback(self):
        st = _FakeStreamlit({"geosphere_station_search": "Graz"})
        legacy = _FakeLegacy(self.stations, self.catalog)

        self.assertEqual(_filtered_station_ids(self.catalog, self.stations, st), ("112",))
        bundle = _station_and_bundle(legacy, st)

        self.assertEqual(bundle[2].station_id, "112")
        self.assertEqual(st.session_state[_STATION_KEY], "112")

    def test_search_filter_replaces_stale_but_globally_valid_station(self):
        st = _FakeStreamlit(
            {
                _STATION_KEY: "105",
                "geosphere_station_search": "Graz",
            }
        )
        legacy = _FakeLegacy(self.stations, self.catalog)

        bundle = _station_and_bundle(legacy, st)

        self.assertEqual(bundle[2].station_id, "112")
        self.assertEqual(st.session_state[_STATION_KEY], "112")

    def test_region_filter_controls_default_station_fallback(self):
        st = _FakeStreamlit({"geosphere_station_states": ["Steiermark"]})
        legacy = _FakeLegacy(self.stations, self.catalog)

        bundle = _station_and_bundle(legacy, st)

        self.assertEqual(bundle[2].station_id, "112")
        self.assertEqual(st.session_state[_STATION_KEY], "112")

    def test_explicit_visible_station_is_not_replaced_by_fallback(self):
        st = _FakeStreamlit({_STATION_KEY: "112"})
        legacy = _FakeLegacy(self.stations, self.catalog)

        bundle = _station_and_bundle(legacy, st)

        self.assertEqual(bundle[2].station_id, "112")
        self.assertEqual(st.session_state[_STATION_KEY], "112")


if __name__ == "__main__":
    unittest.main()
