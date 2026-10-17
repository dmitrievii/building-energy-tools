"""IGE P9.1A strict source provenance + global-grid historical hourly contracts."""
import copy
import datetime as dt
import json
import math
import unittest
import urllib.parse
import p9_1a_global_historical_backbone as p


def stub(s="2023-01-01",e="2023-01-02"):
    start=dt.date.fromisoformat(s);end=dt.date.fromisoformat(e)
    times=[(dt.datetime.combine(start,dt.time())+dt.timedelta(hours=i))
           .strftime("%Y-%m-%dT%H:%M")
           for i in range(((end-start).days+1)*24)]
    n=len(times)
    daily=[i%24 for i in range(n)]
    arrays={
        "temperature_2m":[20.]*n,"dew_point_2m":[10.]*n,
        "relative_humidity_2m":[52.5]*n,
        "surface_pressure":[985.]*n,
        "precipitation":[1. if i%24 in (8,9) else 0. for i in range(n)],
        "cloud_cover":[95. if i%24 in (8,9) else 35. for i in range(n)],
        "shortwave_radiation":[100. if 8<=h<=16 else 0. for h in daily],
        "direct_radiation":[50. if 8<=h<=16 else 0. for h in daily],
        "diffuse_radiation":[50. if 8<=h<=16 else 0. for h in daily],
        "direct_normal_irradiance":[100. if 8<=h<=16 else 0. for h in daily],
        "wind_speed_10m":[2.]*n,"wind_direction_10m":[270.]*n,
        "time":times,
    }
    return {
        "latitude":47.0,"longitude":15.5,"elevation":0,
        "utc_offset_seconds":0,"timezone":"GMT",
        "hourly":arrays,
        "hourly_units":dict(p.EXPECTED_UNITS,time="iso8601"),
    }


def parse(obj=None,s="2023-01-01",e="2023-01-02"):
    return p.parse_source(json.dumps(obj or stub(s,e)).encode(),47.,15.5,s,e)


class P91SourceContracts(unittest.TestCase):
    def test_01_unbounded_longitude_rejected(self):
        with self.assertRaisesRegex(ValueError,"WGS84"):
            p.request_url(47,185,"2023-01-01","2023-01-02")

    def test_02_cannot_request_future_as_historical(self):
        with self.assertRaisesRegex(ValueError,"INVALID_OR_UNAVAILABLE"):
            p.request_url(47,15,"2050-01-01","2050-01-02")

    def test_03_fixed_real_era5_and_no_hidden_elevation_downscaling(self):
        url=p.request_url(47.07,15.44,"2023-01-01","2023-01-02")
        d=urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        self.assertEqual(d["models"],["era5"])
        self.assertEqual(d["elevation"],["nan"])
        self.assertEqual(d["cell_selection"],["nearest"])
        self.assertEqual(d["timezone"],["GMT"])
        self.assertEqual(d["wind_speed_unit"],["ms"])
        self.assertEqual(set(d["hourly"][0].split(",")),set(p.HOURLY))

    def test_04_single_UTC_hour_sequence_complete(self):
        _,arr,m=parse()
        self.assertEqual(m["n_received_hourly_rows"],48)
        self.assertEqual(len(arr["temperature_2m"]),48)
        self.assertTrue(m["dates_UTC_contiguous"])

    def test_05_wrong_UTC_offset_is_fatal(self):
        x=stub();x["utc_offset_seconds"]=3600
        with self.assertRaisesRegex(ValueError,"NOT_GMT_UTC"):
            parse(x)

    def test_06_wrong_source_unit_is_fatal(self):
        x=stub();x["hourly_units"]["wind_speed_10m"]="km/h"
        with self.assertRaisesRegex(ValueError,"SOURCE_UNITS_DRIFT_wind_speed_10m"):
            parse(x)

    def test_07_EPW_clock_shift_or_missing_hours_fails(self):
        x=stub();x["hourly"]["time"][4]="2023-01-01T05:00"
        with self.assertRaisesRegex(ValueError,"SHIFTED_OR_DST"):
            parse(x)

    def test_08_missing_variable_fails(self):
        x=stub();del x["hourly"]["cloud_cover"]
        with self.assertRaisesRegex(ValueError,"VARIABLE_INCOMPLETE_cloud_cover"):
            parse(x)

    def test_09_badly_selected_provider_grid_fails(self):
        x=stub();x["latitude"]=-48.
        with self.assertRaisesRegex(ValueError,"DISTANT_REANALYSIS_GRID"):
            parse(x)

    def test_10_returned_zero_provider_elevation_is_not_a_native_DEM_certification(self):
        _,_,m=parse()
        self.assertTrue(m["provider_elevation_field_cannot_certify_native_grid_or_site_height"])
        self.assertFalse(m["user_altitude_or_terrain_DEM_applied"])
        self.assertTrue(m["provider_statistical_elevation_downscaling_disabled"])

    def test_11_physical_coupling_expected_rain_cloud(self):
        _,arr,_=parse()
        metrics=p.statistics_and_coherence(arr)
        self.assertTrue(metrics["hard_QC_pass"])
        self.assertEqual(metrics["rain_positive_hour_count"],4)
        _,arr,_=parse()
        r=p.grouped_month_hour(arr,stub()["hourly"]["time"])
        self.assertGreater(r["rain_minus_dry_same_month_UTC_hour_cloud_percentage_points"],0)

    def test_12_dewpoint_above_air_is_physical_fail(self):
        x=stub();x["hourly"]["dew_point_2m"][0]=30.
        _,arr,_=parse(x)
        q=p.statistics_and_coherence(arr)
        self.assertFalse(q["hard_QC_pass"])
        self.assertEqual(q["hard_QC_failures"]["dewpoint_above_drybulb"],1)

    def test_13_cloud_cannot_be_pretended_available_if_null(self):
        x=stub();x["hourly"]["cloud_cover"][0]=None
        _,arr,_=parse(x)
        q=p.statistics_and_coherence(arr)
        self.assertFalse(q["hard_QC_pass"])
        self.assertEqual(q["hard_QC_failures"]["provider_missing_nonfinite_hourly_components"],1)

    def test_14_negative_precipitation_source_physically_fails(self):
        x=stub();x["hourly"]["precipitation"][0]=-1
        _,arr,_=parse(x)
        q=p.statistics_and_coherence(arr)
        self.assertFalse(q["hard_QC_pass"])
        self.assertEqual(q["hard_QC_failures"]["invalid_precipitation_cloud_wind_or_radiation"],1)

    def test_15_direct_horizontal_cannot_exceed_direct_normal(self):
        x=stub();x["hourly"]["direct_radiation"][11]=280.
        _,arr,_=parse(x)
        q=p.statistics_and_coherence(arr)
        self.assertFalse(q["hard_QC_pass"])
        self.assertEqual(q["hard_QC_failures"]["direct_horizontal_exceeds_direct_normal"],1)

    def test_16_leap_year_2024_has_8784_hours(self):
        obj=stub("2024-01-01","2024-12-31")
        _,arr,m=p.parse_source(json.dumps(obj).encode(),47.,15.5,
                               "2024-01-01","2024-12-31")
        self.assertEqual(m["n_received_hourly_rows"],8784)
        self.assertEqual(len(arr["precipitation"]),8784)

    def test_17_never_follow_provider_redirects_or_unknown_http_hosts(self):
        with self.assertRaisesRegex(ValueError,"SOURCE_HOST_NOT_ALLOWLISTED"):
            p.get_original_source("http://example.org/evil")

    def test_18_weighted_conditional_comparison_not_invented_when_missing(self):
        self.assertIsNone(p._weighted([(None,5),(None,2)]))

    def test_19_distance_is_zero_on_equal_coordinates(self):
        self.assertAlmostEqual(p.haversine(47,15,47,15),0.)
        self.assertGreater(p.haversine(47,15,47,16),70.)

    def test_20_response_is_source_request_provenance_not_native_CDS(self):
        self.assertIn("NOT_NATIVE",p.SOURCE_SCOPE)
        self.assertEqual(p.MODEL,"era5")


if __name__=="__main__":unittest.main()
