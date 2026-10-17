"""IGE P8.4B frozen full-census, target leakage and paired physical contracts."""
from __future__ import annotations
import datetime as dt
import math
import unittest

from p8_4b_full_census_wind import (
    YEARS,TARGETS,BASE_METHODS,EVALUATED_METHODS,BUFFER_KM,
    STATION_MIN_COUNT,QUALIFIED_MIN_COUNT,CENSUS_THREADS,
    parse_original_two_years,qualified_donor_ids,
    apply_region_buffer,selected_methods,common_hour_predictions,
    paired_effects,paired_7day_bootstrap,score_extended,summarize_year,
    SEASONS,SPEED_BINS,MIN_DONOR_YEAR_FRACTION,MIN_SITE_YEAR_FRACTION,
    BOOTSTRAP_DAYS,BOOTSTRAP_REPS,
)


def station(sid,lat,lon,z=500.):
    return {"station_id":sid,"lat":lat,"lon":lon,"hoehe_m":float(z)}


def toy_catalog():
    # Source metadata used for donor selection only, never target wind data.
    target=station("AIG",47.,8.,500.)
    stations={"AIG":target}
    for i,sid in enumerate(("THU","INT","RAG","ZER","VIT")):
        stations[sid]=station(sid,47.1+i*.01,8.1+i*.01,600+i*100)
    for i,sid in enumerate(("ABC","DEF","GHI","JKL","MNO","PQR")):
        stations[sid]=station(sid,47.,8.+.015+.20*i,500.+40*i)
    return stations


def six_models_on_hours(site,hours):
    out={}
    for i,method in enumerate(EVALUATED_METHODS):
        out[method]={
            t:{
                "reference_speed":2.,
                "reference_direction":45.,
                "scalar":2.+.1*i,
                "vector_direction":45. if not (i==2 and t==hours[0]) else None,
                "unit_direction":45.,
                "nearest_direction":45.,
                "unit_resultant":1.,
            } for t in hours
        }
    return out


class TestFullCensusFrozenMethods(unittest.TestCase):
    def test_frozen_two_independent_years_and_six_target_sites(self):
        self.assertEqual(YEARS,(2022,2025))
        self.assertEqual(TARGETS,("AIG","THU","INT","RAG","ZER","VIT"))
        self.assertEqual(len(set(TARGETS)),6)
        self.assertEqual(BUFFER_KM,25.)
        self.assertEqual(STATION_MIN_COUNT,150)
        self.assertEqual(QUALIFIED_MIN_COUNT,65)

    def test_full_catalog_not_nearest20_shortcut(self):
        self.assertGreater(STATION_MIN_COUNT,92)
        self.assertEqual(CENSUS_THREADS,8)
        self.assertEqual(MIN_DONOR_YEAR_FRACTION,.90)
        self.assertEqual(MIN_SITE_YEAR_FRACTION,.80)

    def test_four_donor_selectors_plus_original_25km_buffer(self):
        self.assertEqual(BASE_METHODS,
            ("distance_idw4","altitude_idw4","terrain_idw4"))
        self.assertEqual(EVALUATED_METHODS,BASE_METHODS+
            tuple("buffer25_"+s for s in BASE_METHODS))

    def test_original_csv_filter_two_years_only_and_source_units(self):
        rows=[
            "station_abbr;reference_timestamp;fkl010h0;dkl010h0",
            "AIG;01.01.2022 00:00;2.5;360",
            "AIG;01.01.2024 00:00;8.0;45",
            "THU;01.01.2025 00:00;9.0;90",
            "AIG;01.01.2025 00:00;0.0;",
            "AIG;01.01.2025 01:00;3.0;180",
        ]
        r,flags=parse_original_two_years(("\n".join(rows)+"\n").encode(),"AIG")
        self.assertFalse(flags)
        self.assertEqual(len(r[2022]),1)
        self.assertEqual(len(r[2025]),2)
        self.assertEqual(r[2022][dt.datetime(2022,1,1)]["direction"],0.)
        self.assertEqual(r[2025][dt.datetime(2025,1,1)]["speed"],0.)
        self.assertIsNone(r[2025][dt.datetime(2025,1,1)]["direction"])
        self.assertEqual(r[2025][dt.datetime(2025,1,1,1)]["direction"],180.)

    def test_duplicate_original_station_time_rejected(self):
        rows=["station_abbr;reference_timestamp;fkl010h0;dkl010h0",
              "AIG;01.01.2022 00:00;2;1",
              "AIG;01.01.2022 00:00;3;2"]
        with self.assertRaisesRegex(ValueError,"DUPLICATED"):
            parse_original_two_years(("\n".join(rows)+"\n").encode(),"AIG")

    def test_source_missing_columns_rejected(self):
        with self.assertRaisesRegex(ValueError,"WIND_COLUMNS"):
            parse_original_two_years(
                b"station_abbr;reference_timestamp;wind_speed\nAIG;01.01.2022 00:00;2\n","AIG")

    def test_wind_magnitude_not_silently_clamped(self):
        rows=["station_abbr;reference_timestamp;fkl010h0;dkl010h0",
              "AIG;01.01.2022 00:00;-2;90",
              "AIG;01.01.2025 00:00;200;1000"]
        r,_=parse_original_two_years(("\n".join(rows)+"\n").encode(),"AIG")
        self.assertIsNone(r[2022][dt.datetime(2022,1,1)]["speed"])
        self.assertIsNone(r[2025][dt.datetime(2025,1,1)]["speed"])
        self.assertIsNone(r[2025][dt.datetime(2025,1,1)]["direction"])

    def test_global_holdout_excludes_all_six_target_readings(self):
        m=toy_catalog()
        q=set(m)
        ids=qualified_donor_ids(m,q)
        self.assertFalse(ids.intersection(TARGETS))
        self.assertEqual(len(ids),6)

    def test_geographic_25km_exclusion_is_not_an_elevation_window(self):
        m=toy_catalog()
        q=qualified_donor_ids(m,set(m))
        filtered=apply_region_buffer(m["AIG"],m,q)
        self.assertNotIn("ABC",filtered)
        self.assertIn("GHI",filtered)
        self.assertTrue(all(
            math.isfinite(m[sid]["hoehe_m"]) for sid in filtered))

    def test_preselected_donors_never_use_targets(self):
        m=toy_catalog()
        ids=qualified_donor_ids(m,set(m))
        feats={sid:{"tpi_1500_m":0.,"rugged_1500_m":0.} for sid in m}
        result=selected_methods(m["AIG"],m,ids,feats)
        self.assertEqual(set(result),set(EVALUATED_METHODS))
        for mode,donors in result.items():
            self.assertEqual(len(donors),4)
            self.assertFalse({x["station_id"] for d,x in donors}.intersection(TARGETS))
            if mode.startswith("buffer25_"):
                self.assertTrue(all(d>=25 for d,x in donors))

    def test_no_target_in_qualified_donor_request(self):
        m=toy_catalog()
        with self.assertRaisesRegex(AssertionError,"TARGET_USED"):
            selected_methods(m["AIG"],m,set(m),{})

    def test_paired_site_metrics_same_hours(self):
        hours=tuple(dt.datetime(2025,3,1)+dt.timedelta(hours=i) for i in range(72))
        predicted=six_models_on_hours("AIG",hours)
        scores,strata=score_extended("AIG",2025,hours,predicted)
        self.assertEqual(len(scores),6)
        self.assertEqual(scores[0]["n_original_UTC_hourly_match"],72)
        self.assertEqual(scores[0]["vector_direction_all_six_method_strict_paired_n"],71)
        self.assertEqual(scores[0]["unit_direction_all_six_method_strict_paired_n"],72)
        self.assertEqual(
            next(x for x in scores if x["method"]=="altitude_idw4")["scalar_speed_MAE_mps"],.1)
        self.assertTrue(any(r["group"]=="MAM" for r in strata))

    def test_paired_delta_is_altitude_minus_distance(self):
        hours=tuple(dt.datetime(2025,2,1)+dt.timedelta(hours=i) for i in range(24))
        p=six_models_on_hours("AIG",hours)
        pairs=paired_effects(p,hours)
        self.assertEqual(len(pairs),24)
        self.assertTrue(all(abs(val-.1)<1e-10 for t,val in pairs))

    def test_bootstrap_preserves_2025_calendar_days_and_determinism(self):
        begin=dt.datetime(2025,1,1)
        pairs=tuple((begin+dt.timedelta(hours=i),-.25) for i in range(8760))
        a=paired_7day_bootstrap(pairs,2025,"AIG",reps=40)
        b=paired_7day_bootstrap(pairs,2025,"AIG",reps=40)
        self.assertEqual(a,b)
        self.assertAlmostEqual(a["estimated_delta_MAE_mps"],-.25,places=8)
        self.assertAlmostEqual(a["CI95_low_mps"],-.25,places=8)
        self.assertEqual(a["block_calendar_days"],7)

    def test_bootstrap_rejects_wrong_year(self):
        pairs=((dt.datetime(2024,1,1),-.3),)
        with self.assertRaisesRegex(ValueError,"OUTSIDE_TEST_YEAR"):
            paired_7day_bootstrap(pairs,2025,"AIG",reps=40)

    def test_year_summary_six_sites_required(self):
        records=[]
        for site in TARGETS:
            records.append({"site":site,"scores":[{"method":name,"scalar_speed_MAE_mps":1.} for name in EVALUATED_METHODS]})
        y=summarize_year(2025,records)
        self.assertEqual(y["n_target_sites"],6)
        self.assertEqual(y["altitude_minus_distance_MAE_mps"],0.)
        with self.assertRaisesRegex(ValueError,"MISSING_SIX_SITE"):
            summarize_year(2025,records[:-1])

    def test_original_clock_seasons_and_weak_wind_strata_fixed(self):
        self.assertEqual(SEASONS[1],"DJF")
        self.assertEqual(SEASONS[8],"JJA")
        self.assertEqual(SPEED_BINS[0][2],"calm")
        self.assertEqual(SPEED_BINS[-1][2],"strong")
        self.assertEqual(BOOTSTRAP_REPS,400)
        self.assertEqual(BOOTSTRAP_DAYS,7)


if __name__=="__main__":
    unittest.main()
