from __future__ import annotations

import unittest
from datetime import date

from epw_climate_analyzer.source_parity_resource_bounds import resource_start_date


class GeoSphereResourceBoundsTests(unittest.TestCase):
    def test_published_resource_start_dates(self) -> None:
        self.assertEqual(resource_start_date("klima-v2-1h"), date(1880, 4, 1))
        self.assertEqual(resource_start_date("klima-v2-10min"), date(1992, 5, 20))

    def test_unknown_resource_has_no_invented_bound(self) -> None:
        self.assertIsNone(resource_start_date("future-resource"))


if __name__ == "__main__":
    unittest.main()
