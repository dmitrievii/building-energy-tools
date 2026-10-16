"""IGE P8.4A1 synthetic contracts for physical temporal support and QC provenance."""
import datetime as dt
import unittest

from p8_4a1_source_semantics import (
    YEAR,MONTH,HOURS,SHIFTS,GEO_STATION,GEO_SITE_CENSUS,
    january_hours,normalize_era5_january,common_clock_sensitivity,geo_metadata_audit,
    swiss_post2018_hourly_reference_stamps,
)
from p7b5_wind_coherence import QC as QC_APPROVED


def era5_payload():
    return {
        "hourly_units":{"wind_speed_10m":"m/s","wind_direction_10m":"°"},
        "utc_offset_seconds":0,"timezone":"GMT",
        "latitude":47.12,"longitude":8.06,"elevation":450.,
        "hourly":{
            "time":[x.strftime("%Y-%m-%dT%H:%M") for x in january_hours()],
            "wind_speed_10m":[2.]*HOURS,
            "wind_direction_10m":[359.]*HOURS,
        }
    }


def geosphere_metadata():
    flags=[{"key":0,"value":"ungeprüft"}]+[
        {"key":i,"value":"processed good"} for i in sorted(QC_APPROVED)]
    return {
        "parameters":[
            {"name":"ff","unit":"m/s","description":"hourly wind speed"},
            {"name":"dd","unit":"°","description":"wind direction"},
            {"name":"ff_flag","unit":"1"},
            {"name":"dd_flag","unit":"1"},
        ],
        "stations":[{"id":GEO_STATION,"name":"station"}],
        "code_lists":{"q21":flags},
    }


class P84A1Contracts(unittest.TestCase):
    def test_axis_744_sorted_utc_hours(self):
        self.assertEqual(HOURS,744)
        self.assertEqual(len(january_hours()),744)
        self.assertEqual(january_hours()[0],dt.datetime(2024,1,1))
        self.assertEqual(january_hours()[-1],dt.datetime(2024,1,31,23))
        self.assertEqual(SHIFTS,(-1,0,1))

    def test_official_post2018_six_10min_end_stamps(self):
        moment=dt.datetime(2024,1,1,16)
        support=swiss_post2018_hourly_reference_stamps(moment)
        self.assertEqual(support,tuple(
            dt.datetime(2024,1,1,15,10)+dt.timedelta(minutes=10*i)
            for i in range(6)))
        self.assertEqual(support[-1],moment)

    def test_pre2018_synop_cannot_reuse_post2018_window(self):
        with self.assertRaisesRegex(ValueError,"PRE2018"):
            swiss_post2018_hourly_reference_stamps(dt.datetime(2017,12,31,16))

    def test_swiss_reference_timezone_must_be_explicitly_utc(self):
        with self.assertRaisesRegex(ValueError,"UTC_NAIVE"):
            swiss_post2018_hourly_reference_stamps(
                dt.datetime(2024,1,1,16,tzinfo=dt.timezone.utc))

    def test_swiss_reference_must_be_hourly(self):
        with self.assertRaisesRegex(ValueError,"NOT_ON_HOUR"):
            swiss_post2018_hourly_reference_stamps(dt.datetime(2024,1,1,16,10))

    def test_valid_gateway_metadata(self):
        d,cell=normalize_era5_january(era5_payload())
        self.assertEqual(len(d),744)
        self.assertEqual(cell["elevation"],450.)
        self.assertEqual(d[january_hours()[0]]["direction"],359.)

    def test_era5_wrong_unit_fails(self):
        p=era5_payload()
        p["hourly_units"]["wind_speed_10m"]="km/h"
        with self.assertRaisesRegex(ValueError,"UNIT"):
            normalize_era5_january(p)

    def test_explicit_era5_gmt_required(self):
        p=era5_payload();p["utc_offset_seconds"]=3600
        with self.assertRaisesRegex(ValueError,"NOT_GMT"):
            normalize_era5_january(p)

    def test_missing_era5_axis_fails(self):
        p=era5_payload();p["hourly"]["time"].pop()
        with self.assertRaisesRegex(ValueError,"744"):
            normalize_era5_january(p)

    def test_duplicate_time_cannot_be_silent(self):
        p=era5_payload()
        p["hourly"]["time"][20]=p["hourly"]["time"][19]
        with self.assertRaisesRegex(ValueError,"DUPLICATE_GAP"):
            normalize_era5_january(p)

    def test_missing_grid_elevation_not_assumed_zero(self):
        p=era5_payload();del p["elevation"]
        with self.assertRaisesRegex(ValueError,"GRID_PROVENANCE"):
            normalize_era5_january(p)

    def test_missing_gateway_direction_coverage_fails_closed(self):
        p=era5_payload()
        p["hourly"]["wind_direction_10m"][:60]=[None]*60
        with self.assertRaisesRegex(ValueError,"SPARSE"):
            normalize_era5_january(p)

    def test_shift_diagnostics_are_fixed_and_not_selected(self):
        grid,_=normalize_era5_january(era5_payload())
        reference={t:{"speed":2.,"direction":1.} for t in january_hours()}
        scores=common_clock_sensitivity(reference,grid)
        self.assertEqual(set(scores),{"-1","0","1"})
        for k in scores:
            self.assertEqual(scores[k]["n_speed_pairs"],742)
            self.assertEqual(scores[k]["n_vector_direction_pairs"],742)
            self.assertEqual(scores[k]["scalar_speed_mae_mps"],0.)
            self.assertEqual(scores[k]["direction_mae_deg_on_both_noncalm"],2.)

    def test_shift_vector_metric_checks_actual_pairwise_vector(self):
        grid,_=normalize_era5_january(era5_payload())
        reference={t:{"speed":2.,"direction":179.} for t in january_hours()}
        scores=common_clock_sensitivity(reference,grid)
        self.assertGreater(scores["0"]["vector_east_north_rmse_mps"],3.9)

    def test_clock_diagnostic_requires_valid_matched_sample(self):
        grid,_=normalize_era5_january(era5_payload())
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_SWISS"):
            common_clock_sensitivity({},grid)

    def test_qc_metadata_codes_and_units(self):
        audit=geo_metadata_audit(geosphere_metadata())
        self.assertEqual(audit["station_id"],GEO_STATION)
        self.assertEqual(audit["parameter_definitions"]["ff"]["units"],"m/s")
        self.assertEqual(audit["qc_flag_legend"][0],"ungeprüft")
        self.assertFalse(audit["unknown_flag_codes_accepted"])

    def test_source_unverified_flag_rejected_by_qc(self):
        self.assertNotIn(0,QC_APPROVED)

    def test_geo_missing_direction_qc_must_fail(self):
        m=geosphere_metadata()
        m["parameters"]=[v for v in m["parameters"] if v["name"]!="dd_flag"]
        with self.assertRaisesRegex(ValueError,"dd_flag"):
            geo_metadata_audit(m)

    def test_census_is_fixed_not_fit_to_skill(self):
        self.assertEqual(GEO_SITE_CENSUS,(30,16414,16400,16412))
        self.assertEqual(len(set(GEO_SITE_CENSUS)),4)
        self.assertEqual(GEO_SITE_CENSUS[0],GEO_STATION)

    def test_new_graz_site_metadata_identity_distinct_from_composite(self):
        meta=geosphere_metadata()
        meta["stations"].append({"id":16414,"name":"Graz Universität/Heinrichstraße"})
        x=geo_metadata_audit(meta,station_id=16414)
        self.assertEqual(x["station_id"],16414)
        self.assertEqual(x["station_name"],"Graz Universität/Heinrichstraße")

    def test_geo_invalid_units_must_fail(self):
        m=geosphere_metadata()
        m["parameters"][0]["unit"]="km/h"
        with self.assertRaisesRegex(ValueError,"UNIT_DRIFT"):
            geo_metadata_audit(m)

    def test_geo_missing_q21_legend_fails(self):
        m=geosphere_metadata()
        m["code_lists"]={"q21":[]}
        with self.assertRaisesRegex(ValueError,"Q21"):
            geo_metadata_audit(m)

    def test_only_original_station_id_is_accepted(self):
        m=geosphere_metadata()
        m["stations"]=[{"id":31,"name":"wrong site"}]
        with self.assertRaisesRegex(ValueError,"STATION_METADATA_MISSING_30"):
            geo_metadata_audit(m)


if __name__=="__main__":
    unittest.main()
