from __future__ import annotations

import unittest

import pandas as pd

from epw_climate_analyzer.geosphere import (
    GEOSPHERE_ENDPOINT,
    GEOSPHERE_NATIVE_INTERVAL_MINUTES,
    MAX_REQUEST_DATAPOINTS,
    GeoSphereStation,
    _validate_official_url,
    build_canonical_station_dataset,
    build_data_query,
    estimate_request_datapoints,
    parse_parameters,
    parse_station_data_response,
    parse_stations,
    provider_frame_to_canonical,
    station_catalog,
    supported_parameter_mapping,
)


PARAMETERS = [
    {"name": "tl", "long_name": "Lufttemperatur 2m", "unit": "°C", "description": ""},
    {"name": "rf", "long_name": "Relative Feuchte", "unit": "%", "description": ""},
    {"name": "p", "long_name": "Luftdruck", "unit": "hPa", "description": ""},
    {"name": "ffam", "long_name": "Windgeschwindigkeit 10m, arithmetischer Mittelwert", "unit": "m/s", "description": ""},
    {"name": "dd", "long_name": "Windrichtung", "unit": "°", "description": ""},
    {"name": "rr", "long_name": "Niederschlagssumme", "unit": "mm", "description": ""},
    {"name": "sh", "long_name": "Gesamtschneehöhe, Schneepegelmessung", "unit": "cm", "description": ""},
    {"name": "cglo", "long_name": "Globalstrahlung Mittelwert", "unit": "W/m²", "description": ""},
    {"name": "chim", "long_name": "Himmelsstrahlung Mittelwert", "unit": "W/m²", "description": ""},
    {"name": "tl_flag", "long_name": "Qualitätsflag", "unit": "code", "description": ""},
]

METADATA = {
    "parameters": PARAMETERS,
    "stations": [
        {
            "id": 11240,
            "name": "Graz/Universitaet",
            "state": "Steiermark",
            "altitude": 366.0,
            "valid_from": "1992-08-29",
            "valid_to": "2100-12-31",
            "geometry": {"type": "Point", "coordinates": [15.45, 47.08]},
        }
    ],
}


class GeoSphereAdapterTests(unittest.TestCase):
    def test_metadata_resolves_official_v2_parameters_and_units(self) -> None:
        parsed = parse_parameters(METADATA)
        self.assertEqual(parsed["tl"].unit, "°C")
        mapping = supported_parameter_mapping(METADATA)
        self.assertEqual(mapping["tl"].canonical_name, "dry_bulb_temperature_c")
        self.assertEqual(mapping["p"].scale, 100.0)
        self.assertAlmostEqual(mapping["cglo"].scale, 1.0 / 6.0)
        self.assertNotIn("tl_flag", mapping)

    def test_metadata_unit_change_fails_closed(self) -> None:
        changed = {"parameters": [dict(item) for item in PARAMETERS], "stations": METADATA["stations"]}
        next(item for item in changed["parameters"] if item["name"] == "p")["unit"] = "Pa"
        with self.assertRaisesRegex(ValueError, "unit changed"):
            supported_parameter_mapping(changed)

    def test_station_metadata_and_catalog_preserve_provider_identity(self) -> None:
        stations = parse_stations(METADATA)
        self.assertEqual(len(stations), 1)
        station = stations[0]
        self.assertEqual(station.station_id, "11240")
        self.assertEqual(station.state, "Steiermark")
        self.assertEqual(station.latitude, 47.08)
        self.assertEqual(station.longitude, 15.45)
        catalog = station_catalog(METADATA)
        self.assertEqual(catalog.iloc[0]["station_id"], "11240")
        self.assertEqual(float(catalog.iloc[0]["elevation_m"]), 366.0)

    def test_official_host_boundary_is_fail_closed(self) -> None:
        self.assertEqual(_validate_official_url(GEOSPHERE_ENDPOINT), GEOSPHERE_ENDPOINT)
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            _validate_official_url("http://dataset.api.hub.geosphere.at/v1/test")
        with self.assertRaisesRegex(ValueError, "restricted"):
            _validate_official_url("https://example.com/v1/station/historical/klima-v2-10min")
        with self.assertRaisesRegex(ValueError, "v1"):
            _validate_official_url("https://dataset.api.hub.geosphere.at/other")

    def test_request_size_uses_ten_minute_cadence_and_local_cap(self) -> None:
        start = pd.Timestamp("2026-01-01T00:00:00Z")
        end = pd.Timestamp("2026-01-01T01:00:00Z")
        self.assertEqual(estimate_request_datapoints(start, end, 3), 21)
        query = build_data_query("11240", start, end, ["tl", "rf", "p"])
        self.assertEqual(query["station_ids"], "11240")
        self.assertEqual(query["parameters"], "tl,rf,p")
        self.assertEqual(query["start"], "2026-01-01T00:00")
        self.assertEqual(query["end"], "2026-01-01T01:00")
        # A sufficiently large request is rejected before any network call.
        very_long_end = start + pd.Timedelta(minutes=10 * (MAX_REQUEST_DATAPOINTS + 1))
        with self.assertRaisesRegex(ValueError, "local .* limit"):
            build_data_query("11240", start, very_long_end, ["tl"])

    def test_station_json_parser_retains_real_utc_timestamps_and_nulls(self) -> None:
        payload = {
            "timestamps": [
                "2024-07-03T12:00+00:00",
                "2024-07-03T12:10+00:00",
                "2024-07-03T12:20+00:00",
            ],
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "station": 11240,
                        "parameters": {
                            "tl": {"data": [25.0, 25.2, None]},
                            "rf": {"data": [50.0, 49.0, 48.0]},
                            "p": {"data": [960.0, 960.1, 960.2]},
                            "cglo": {"data": [600.0, 300.0, 0.0]},
                            "rr": {"data": [0.0, 0.2, None]},
                        },
                    },
                }
            ],
        }
        frame = parse_station_data_response(payload, "11240", ["tl", "rf", "p", "cglo", "rr"])
        self.assertEqual(len(frame), 3)
        self.assertEqual(str(frame.index.tz), "UTC")
        self.assertEqual(frame.index.year.unique().tolist(), [2024])
        self.assertTrue(pd.isna(frame.iloc[2]["tl"]))
        self.assertEqual(float(frame.iloc[1]["rr"]), 0.2)

    def test_canonical_conversion_uses_quantity_correct_units(self) -> None:
        index = pd.date_range("2024-07-03T12:00:00Z", periods=3, freq="10min")
        provider = pd.DataFrame(
            {
                "tl": [25.0, 25.2, 25.4],
                "rf": [50.0, 49.0, 48.0],
                "p": [960.0, 960.1, 960.2],
                "cglo": [600.0, 300.0, 0.0],
                "chim": [120.0, 60.0, 0.0],
                "rr": [0.0, 0.2, 0.0],
                "ffam": [2.0, 2.2, 2.1],
                "dd": [350.0, 0.0, 10.0],
                "sh": [0.0, 0.0, 0.0],
            },
            index=index,
        )
        mapping = supported_parameter_mapping(METADATA)
        canonical = provider_frame_to_canonical(provider, mapping)
        self.assertEqual(float(canonical.iloc[0]["atmospheric_station_pressure_pa"]), 96000.0)
        self.assertEqual(float(canonical.iloc[0]["global_horizontal_radiation_wh_m2"]), 100.0)
        self.assertEqual(float(canonical.iloc[0]["diffuse_horizontal_radiation_wh_m2"]), 20.0)
        self.assertEqual(float(canonical.iloc[1]["liquid_precipitation_depth_mm"]), 0.2)

        station = GeoSphereStation(
            station_id="11240",
            name="Graz/Universitaet",
            latitude=47.08,
            longitude=15.45,
            elevation_m=366.0,
            state="Steiermark",
            valid_from="1992-08-29",
            valid_to="2100-12-31",
        )
        climate = build_canonical_station_dataset(
            station=station,
            provider_frame=provider,
            mapping=mapping,
            request_reference="https://dataset.api.hub.geosphere.at/v1/station/historical/klima-v2-10min?test=1",
            retrieval_time_utc="2026-09-15T12:00:00+00:00",
        )
        self.assertEqual(climate.temporal.calendar_mode, "historical")
        self.assertEqual(climate.temporal.native_interval_minutes, GEOSPHERE_NATIVE_INTERVAL_MINUTES)
        self.assertEqual(climate.temporal.timezone_name, "UTC")
        self.assertEqual(climate.start.year, 2024)
        self.assertEqual(climate.provenance.provider, "GeoSphere Austria")
        self.assertIn("CC", climate.provenance.notes[0])
        self.assertEqual(climate.location.station_id, "11240")

    def test_station_parameter_length_mismatch_fails_closed(self) -> None:
        payload = {
            "timestamps": ["2024-01-01T00:00+00:00", "2024-01-01T00:10+00:00"],
            "features": [
                {
                    "properties": {
                        "station": "11240",
                        "parameters": {"tl": {"data": [1.0]}},
                    }
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "1 values for 2 timestamps"):
            parse_station_data_response(payload, "11240", ["tl"])


if __name__ == "__main__":
    unittest.main()
