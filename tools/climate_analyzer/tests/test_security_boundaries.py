from __future__ import annotations

from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile
import unittest

from epw_climate_analyzer.climate_sources import (
    MAX_ZIP_MEMBERS,
    _extract_epw_from_zip,
    _validate_onebuilding_url,
)
from epw_climate_analyzer.epw_parser import EPW_COLUMNS, MAX_EPW_BYTES, parse_epw, validate_epw_payload


def valid_epw_bytes(hours: int = 24) -> bytes:
    headers = [
        "LOCATION,Test City,Test State,AUT,TEST,123456,47.07,15.44,1.0,350.0",
        "DESIGN CONDITIONS,0",
        "TYPICAL/EXTREME PERIODS,0",
        "GROUND TEMPERATURES,0",
        "HOLIDAYS/DAYLIGHT SAVINGS,No,0,0,0",
        "COMMENTS 1,generated security fixture",
        "COMMENTS 2,generated security fixture",
        "DATA PERIODS,1,1,Data,Sunday,1/1,12/31",
    ]
    rows = []
    for index in range(hours):
        values = ["0"] * len(EPW_COLUMNS)
        values[0] = "2020"
        values[1] = "1"
        values[2] = str(1 + index // 24)
        values[3] = str(1 + index % 24)
        values[4] = "60"
        values[5] = "?9?9?9?9E0?9?9?9*9*9*9*9*9*9*9*9*9*9*9*9*9*9*9"
        values[6] = "5.0"
        values[7] = "2.0"
        values[8] = "80"
        values[9] = "101325"
        values[20] = "180"
        values[21] = "2.0"
        rows.append(",".join(values))
    return ("\n".join(headers + rows) + "\n").encode("utf-8")


class EpwInputBoundaryTests(unittest.TestCase):
    def test_valid_minimal_epw_passes_and_parses(self) -> None:
        payload = valid_epw_bytes()
        validate_epw_payload(payload, "valid.epw")
        epw = parse_epw(BytesIO(payload))
        self.assertEqual(len(epw.data), 24)
        self.assertEqual(epw.location.country, "AUT")

    def test_nul_bytes_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "NUL"):
            validate_epw_payload(valid_epw_bytes() + b"\x00", "nul.epw")

    def test_oversized_payload_is_rejected_before_parsing(self) -> None:
        with self.assertRaisesRegex(ValueError, "exceeds"):
            validate_epw_payload(b"A" * (MAX_EPW_BYTES + 1), "large.epw")

    def test_wrong_field_count_is_rejected(self) -> None:
        payload = valid_epw_bytes().decode("utf-8")
        lines = payload.splitlines()
        lines[8] = "2020,1,1,1"
        with self.assertRaisesRegex(ValueError, "fields on line"):
            validate_epw_payload(("\n".join(lines) + "\n").encode("utf-8"), "bad-fields.epw")

    def test_invalid_location_bounds_are_rejected(self) -> None:
        payload = valid_epw_bytes().decode("utf-8").replace(",47.07,15.44,", ",147.07,15.44,", 1)
        with self.assertRaisesRegex(ValueError, "latitude"):
            validate_epw_payload(payload.encode("utf-8"), "bad-location.epw")


class ClimateDownloadBoundaryTests(unittest.TestCase):
    def test_only_https_onebuilding_host_is_allowed(self) -> None:
        accepted = _validate_onebuilding_url("https://climate.onebuilding.org/file.zip")
        self.assertEqual(accepted, "https://climate.onebuilding.org/file.zip")

        rejected = [
            "http://climate.onebuilding.org/file.zip",
            "https://example.com/file.zip",
            "https://climate.onebuilding.org.evil.example/file.zip",
            "https://user:pass@climate.onebuilding.org/file.zip",
            "https://climate.onebuilding.org:8443/file.zip",
        ]
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError):
                _validate_onebuilding_url(url)

    def test_safe_zip_epw_is_read_without_filesystem_extraction(self) -> None:
        buf = BytesIO()
        with ZipFile(buf, "w", ZIP_DEFLATED) as archive:
            archive.writestr("weather/test.epw", valid_epw_bytes())
            archive.writestr("weather/readme.txt", "metadata")
        name, payload = _extract_epw_from_zip(buf.getvalue(), "weather.zip")
        self.assertEqual(name, "test.epw")
        self.assertTrue(payload.startswith(b"LOCATION,"))

    def test_zip_path_traversal_is_rejected(self) -> None:
        buf = BytesIO()
        with ZipFile(buf, "w", ZIP_DEFLATED) as archive:
            archive.writestr("../test.epw", valid_epw_bytes())
        with self.assertRaisesRegex(ValueError, "unsafe EPW path"):
            _extract_epw_from_zip(buf.getvalue(), "unsafe.zip")

    def test_zip_member_count_is_bounded(self) -> None:
        buf = BytesIO()
        with ZipFile(buf, "w", ZIP_DEFLATED) as archive:
            for index in range(MAX_ZIP_MEMBERS + 1):
                archive.writestr(f"metadata/{index}.txt", "x")
            archive.writestr("weather.epw", valid_epw_bytes())
        with self.assertRaisesRegex(ValueError, "too many members"):
            _extract_epw_from_zip(buf.getvalue(), "many.zip")


if __name__ == "__main__":
    unittest.main()
