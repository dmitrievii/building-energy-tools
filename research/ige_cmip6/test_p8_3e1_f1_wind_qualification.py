"""Independent P8.3E1/F1 invariants (synthetic mathematical fixtures, no live data)."""
import datetime as dt
import math
import unittest

from p8_3e1_f1_wind_qualification import (
    classify_station_evidence, correct_era5, decode_era5_year, donor_weights,
    e1_station_records, evaluate_target, exposure_clues, metrics, monthly_residuals,
    blended_residual, TRAIN_YEAR, HOLDOUT_YEAR,
)
from p8_2e_crossyear import annual_hours


def wind(speed, direction=0.):
    return {"speed": speed, "direction": direction}


class ExposureQualification(unittest.TestCase):
    def test_text_exposure_is_not_wmo_class(self):
        raw = b"station_abbr;station_exposition_en;station_height_masl\nBAS;City valley;316\nGRA;On an open field;700\n"
        rows, _ = e1_station_records(raw, ("BAS","GRA"))
        self.assertEqual(rows[0]["exposure_textual_clues"], ["valley_indication", "urban_indication"])
        self.assertTrue(rows[1]["station_exposition_description"])
        for site in rows:
            self.assertIsNone(site["instrument_height_m_agl"])
            self.assertIsNone(site["z0_m"])
            self.assertFalse(site["height_normalization_authorized"])
            self.assertFalse(site["exposure_wmo_class_verified"])

    def test_height_and_roughness_source_claims_not_automatically_accepted(self):
        row = {"station_abbr":"BAS", "station_exposition_en":"Airport",
               "anemometer_height_m_agl":"10", "roughness_length_z0_m":".03"}
        q = classify_station_evidence(row, list(row))
        self.assertTrue(q["instrument_height_column_present"])
        self.assertTrue(q["roughness_column_present"])
        self.assertFalse(q["height_normalization_authorized"])
        self.assertIsNone(q["instrument_height_m_agl"])

    def test_undefined_exposure_is_reported_not_imputed(self):
        self.assertEqual(exposure_clues(""),["missing_or_undocumented"])
        self.assertEqual(exposure_clues("At a location"),["description_present_no_recognized_clue"])

    def test_missing_or_duplicate_stations_fail(self):
        with self.assertRaisesRegex(ValueError, "E1_STATIONS_MISSING"):
            e1_station_records(b"station_abbr;station_exposition_en\nBAS;valley\n", ("BAS", "GRA"))
        with self.assertRaisesRegex(ValueError, "E1_DUPLICATE_STATION"):
            e1_station_records(b"station_abbr;station_exposition_en\nBAS;valley\nBAS;ridge\n", ("BAS",))


class ERA5Climatology(unittest.TestCase):
    def era_fixture(self, year):
        hrs = annual_hours(year)
        return {
            "hourly_units":{"wind_speed_10m":"m/s","wind_direction_10m":"°"},
            "hourly":{
                "time":[t.strftime("%Y-%m-%dT%H:%M") for t in hrs],
                "wind_speed_10m":[2.]*len(hrs),
                "wind_direction_10m":[350.]*len(hrs),
            },
        }

    def test_strict_full_year_leap_hourly_axis(self):
        self.assertEqual(len(decode_era5_year(self.era_fixture(2024),2024)),8784)
        self.assertEqual(len(decode_era5_year(self.era_fixture(2023),2023)),8760)

    def test_reject_clock_and_unit_errors(self):
        fixture=self.era_fixture(2024)
        fixture["hourly"]["time"][42]="2024-01-02T17:00"
        with self.assertRaisesRegex(ValueError,"CLOCK"):
            decode_era5_year(fixture,2024)
        fixture=self.era_fixture(2024)
        fixture["hourly_units"]["wind_speed_10m"]="km/h"
        with self.assertRaisesRegex(ValueError,"UNITS"):
            decode_era5_year(fixture,2024)

    def test_monthwise_training_excludes_missing_days(self):
        hours=annual_hours(TRAIN_YEAR)
        obs={t:wind(3,90) for t in hours}
        era={t:wind(2,90) for t in hours}
        residual=monthly_residuals(obs,era)
        self.assertEqual(len(residual),12)
        self.assertAlmostEqual(residual[1]["scalar_bias_mps"],1.)
        self.assertAlmostEqual(residual[1]["u_bias_mps"],-1.)
        # Entire January removed -> fail closed, not fit another month.
        incomplete={t:v for t,v in obs.items() if t.month!=1}
        with self.assertRaisesRegex(ValueError,"F1_MONTH_TRAIN_COVERAGE"):
            monthly_residuals(incomplete,era)

    def test_circular_wind_bias_near_360(self):
        hours=annual_hours(2023)
        observed={t:wind(3,1) for t in hours}
        background={t:wind(3,359) for t in hours}
        corrections=monthly_residuals(observed, background)
        prediction=correct_era5(wind(3,359), corrections[5])
        angle=prediction["direction"]
        self.assertLess(abs(((angle-1+180)%360)-180),.01)

    def test_clipped_scalar_is_calm_without_synthetic_direction(self):
        r=correct_era5(wind(1,0),{"scalar_bias_mps":-4,"u_bias_mps":0,"v_bias_mps":0})
        self.assertEqual(r["speed"],0.)
        self.assertIsNone(r["direction"])

    def test_target_excluded_by_identity(self):
        target={"station_id":"BAS","lat":47.6,"lon":7.5}
        donors={"BAS":target, "PAY":{"station_id":"PAY","lat":46.8,"lon":7.0}}
        with self.assertRaisesRegex(ValueError,"LEAKAGE"):
            donor_weights(target,donors,1)

    def test_weight_normalization_and_missing_climatology(self):
        selected=[("A",10,.75),("B",15,.25)]
        residual={k:{m:{"scalar_bias_mps":i,"u_bias_mps":i,"v_bias_mps":i} for m in range(1,13)}
                  for k,i in (("A",2.),("B",6.))}
        self.assertAlmostEqual(blended_residual(1,selected,residual)["scalar_bias_mps"],3.)
        with self.assertRaisesRegex(ValueError,"CLIMATOLOGY"):
            blended_residual(1,[("C",4,1)],residual)

    def test_paired_metrics_and_unresolved_azimuth(self):
        samples=[{"observed":wind(2,359),
                  "era5":wind(1,1),
                  "era5_residual":wind(2,0),
                  "station_idw4":wind(2,None)}]
        result=metrics(samples)
        self.assertAlmostEqual(result["era5"]["speed_mae_mps"],1.)
        self.assertEqual(result["era5_residual"]["speed_mae_mps"],0.)
        self.assertAlmostEqual(result["era5"]["direction_mae_deg"],2.)
        self.assertEqual(result["station_idw4"]["direction_fixed90_deg"],90.)
        self.assertEqual(result["station_idw4"]["direction_resolved_n"],0)

    def test_blind_year_site_and_baseline_common_hour_gate(self):
        t=dt.datetime(HOLDOUT_YEAR,1,1)
        target_obs={t:wind(2,90)}
        era_obs={t:wind(2,90)}
        climat={"A":{m:{"scalar_bias_mps":0,"u_bias_mps":0,"v_bias_mps":0} for m in range(1,13)},
                 "B":{m:{"scalar_bias_mps":0,"u_bias_mps":0,"v_bias_mps":0} for m in range(1,13)}}
        selected=[("A",2,.5),("B",3,.5)]
        donor={"A":{t:wind(2,90)},"B":{t:wind(2,90)}}
        with self.assertRaisesRegex(ValueError,"COVERAGE"):
            evaluate_target("TGT",selected,climat,era_obs,target_obs,donor)


if __name__ == "__main__":
    unittest.main()
