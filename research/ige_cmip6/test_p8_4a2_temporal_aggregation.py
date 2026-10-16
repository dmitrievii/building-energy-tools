"""P8.4A2 unit physics contracts for source 10min/hour temporal reconstruction."""
import datetime as dt
import math
import unittest
from p8_4a2_temporal_aggregation import (
    YEAR, REQUIRED_HOURS, HOUR_TO_TEN, utc_ten_axis,
    aggregate_six, matched_hourly, summarize, source_field_semantics,
    parse_swiss_tenminute, SWISS_SITES, GEO_SITES, MIN_FRACTION,
)


def sample(speed=2.,direction=90.):
    return {"speed":float(speed),"direction":direction}


class TestA2TemporalAggregation(unittest.TestCase):
    def test_reference_743_hourly_windows_and_4464_ten_minute_stamps(self):
        self.assertEqual(len(REQUIRED_HOURS),743)
        self.assertEqual(len(utc_ten_axis()),4464)
        self.assertEqual(REQUIRED_HOURS[0],dt.datetime(2024,1,1,1))
        self.assertEqual(REQUIRED_HOURS[-1],dt.datetime(2024,1,31,23))
        self.assertEqual(HOUR_TO_TEN[REQUIRED_HOURS[0]],
            tuple(dt.datetime(2024,1,1,0,10)+dt.timedelta(minutes=10*i) for i in range(6)))
        self.assertEqual(HOUR_TO_TEN[REQUIRED_HOURS[-1]][-1],REQUIRED_HOURS[-1])

    def test_preregistered_swiss_and_graz_sites(self):
        self.assertEqual(SWISS_SITES,("BAS","GRA","MUB"))
        self.assertEqual(GEO_SITES,(16400,16412))
        self.assertEqual(MIN_FRACTION,.85)

    def test_scalar_average_and_parallel_vector_are_equivalent(self):
        x=aggregate_six([sample(v,90) for v in (1.,2.,3.,4.,5.,6.)])
        self.assertAlmostEqual(x["scalar_speed"],3.5)
        self.assertAlmostEqual(x["vector_speed"],3.5)
        self.assertAlmostEqual(x["weighted_direction"],90.)
        self.assertAlmostEqual(x["unit_direction"],90.)

    def test_opposite_winds_must_not_cancel_scalar(self):
        vals=[sample(3.,0.) for _ in range(3)]+[sample(3.,180.) for _ in range(3)]
        x=aggregate_six(vals)
        self.assertAlmostEqual(x["scalar_speed"],3.)
        self.assertAlmostEqual(x["vector_speed"],0.)
        self.assertIsNone(x["weighted_direction"])

    def test_wraparound_is_correct_on_unit_circle(self):
        vals=[sample(3.,359.) for _ in range(3)]+[sample(3.,1.) for _ in range(3)]
        x=aggregate_six(vals)
        self.assertAlmostEqual(x["scalar_speed"],3.)
        self.assertAlmostEqual(x["weighted_direction"],0.,places=8)
        self.assertAlmostEqual(x["unit_direction"],0.,places=8)

    def test_speed_weighted_vs_unit_directions_differ(self):
        vals=[sample(5.,0.) for _ in range(3)]+[sample(1.,90.) for _ in range(3)]
        x=aggregate_six(vals)
        self.assertAlmostEqual(x["scalar_speed"],3.)
        self.assertLess(x["weighted_direction"],20.)
        self.assertAlmostEqual(x["unit_direction"],45.)

    def test_all_calm_values_cannot_invent_direction(self):
        x=aggregate_six([sample(0.,None) for _ in range(6)])
        self.assertEqual(x["scalar_speed"],0.)
        self.assertEqual(x["vector_speed"],0.)
        self.assertIsNone(x["weighted_direction"])
        self.assertIsNone(x["unit_direction"])

    def test_noncalm_missing_direction_keeps_scalar_but_blocks_azimuth(self):
        x=aggregate_six([sample(2.,None)]+[sample(2.,90.) for _ in range(5)])
        self.assertEqual(x["scalar_speed"],2.)
        self.assertIsNone(x["vector_speed"])
        self.assertIsNone(x["weighted_direction"])

    def test_missing_speed_returns_no_full_hour(self):
        x=aggregate_six([sample(2.) for _ in range(5)]+[{"speed":None,"direction":90.}])
        self.assertIsNone(x)

    def test_requires_six(self):
        with self.assertRaisesRegex(ValueError,"EXACTLY_SIX"):
            aggregate_six([sample(3.)]*5)

    def test_jensen_bound_with_rotating_wind(self):
        for azimuths in ((0,90,180,270,330,10),(359,1,359,1,359,1),
                         (0,0,0,90,90,90)):
            a=aggregate_six([sample(5.+i*.1,d) for i,d in enumerate(azimuths)])
            self.assertLessEqual(a["vector_speed"],a["scalar_speed"]+1e-10)

    def test_metadata_requires_all_four_distinct_original_parameters(self):
        lines=["parameter;description;unit",
               "fkl010z0;Wind speed scalar ten minutes mean;m/s",
               "dkl010z0;Direction ten minutes mean;°",
               "fkl010h0;Wind speed scalar hourly mean;m/s",
               "dkl010h0;Direction hourly mean;°"]
        import builtins
        raw=("\n".join(lines)+"\n").encode()
        found=source_field_semantics(raw)
        self.assertEqual(len(found),4)
        with self.assertRaisesRegex(ValueError,"A2_OFFICIAL_PARAMETER_METADATA"):
            source_field_semantics(("\n".join(lines[:-1])+"\n").encode())

    def test_strict_743_complete_source_hours(self):
        ten={}
        hourly={}
        for t in REQUIRED_HOURS:
            hourly[t]=sample(4.,90.)
            for stamp in HOUR_TO_TEN[t]:
                ten[stamp]=sample(4.,90.)
        rows=matched_hourly(ten,hourly,"BAS")
        self.assertEqual(len(rows),743)
        metrics=summarize(rows,"Swiss scalar")
        self.assertAlmostEqual(metrics["scalar_speed_error_mps"]["mae"],0.)
        self.assertAlmostEqual(metrics["fair_same_hour_scalar_vs_vector_speed_error_mps"]["scalar"]["mae"],0.)
        self.assertEqual(metrics["direction_candidates"]["unit_direction"]["n_resolved"],743)
        # Make too many hours unobservable; should never fill.
        for t in REQUIRED_HOURS[:150]:
            ten.pop(HOUR_TO_TEN[t][-1],None)
        with self.assertRaisesRegex(ValueError,"TOO_FEW"):
            matched_hourly(ten,hourly,"BAS")

    def test_schema_and_origin_date_are_strict(self):
        from p8_4a2_temporal_aggregation import parse_datetime_utc
        self.assertEqual(parse_datetime_utc("31.01.2024 23:50"),dt.datetime(2024,1,31,23,50))
        with self.assertRaisesRegex(ValueError,"UTC_TIMESTAMP"):
            parse_datetime_utc("2024-01-31T23:50Z")

    def test_monthly_raw_swiss_exact_parameter_declaration(self):
        # 4464 samples ensure full original-Jan time axis and official naming.
        csv=["station_abbr;reference_timestamp;fkl010z0;dkl010z0"]
        csv.extend("BAS;%s;2.0;180" % stamp.strftime("%d.%m.%Y %H:%M")
                   for stamp in utc_ten_axis())
        data=("\n".join(csv)+"\n").encode()
        parsed=parse_swiss_tenminute(data,"BAS")
        self.assertEqual(len(parsed),4464)
        self.assertEqual(parsed[utc_ten_axis()[0]]["speed"],2.)
        self.assertEqual(parsed[utc_ten_axis()[-1]]["direction"],180.)
        with self.assertRaisesRegex(ValueError,"SWISS_DUPLICATE"):
            parse_swiss_tenminute(data+csv[1].encode()+b"\n","BAS")

    def test_no_silent_speed_compensation_with_ambiguous_direction(self):
        vals=[sample(3.,270.)]*3 + [sample(3.,None)] + [sample(3.,90.)]*2
        a=aggregate_six(vals)
        self.assertEqual(a["scalar_speed"],3.)
        self.assertFalse(a["direction_qualified"])


if __name__=="__main__":
    unittest.main()
