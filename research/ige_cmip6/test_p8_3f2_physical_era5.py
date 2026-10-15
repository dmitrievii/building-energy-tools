"""IGE P8.3F2: leakage, physics-domain and honest independent benchmark contracts."""
import datetime as dt
import math
import unittest

from p8_2e_crossyear import annual_hours
from p8_3f2_physical_era5 import (
    TARGETS, METHODS, FROZEN_2024_P8D_ALTITUDE, BOOTSTRAP_REPS,
    exposure_category, station_exposures, altitude_and_exposure_weights,
    physical_correction, frozen_selection, build_predictions, paired_site_rows,
    summarize, moving_block_delta_ci,
)


def row(speed, direction=180.):
    return {"speed":speed,"direction":direction}


def station(sid,lat=47.,lon=8.,height=450.):
    return {"station_id":sid,"lat":lat,"lon":lon,"hoehe_m":height}


class PhysicalWindF2Contracts(unittest.TestCase):
    def test_exposure_text_is_exact_not_a_wmo_or_sensor_height(self):
        self.assertEqual(exposure_category("plain"),"plain")
        self.assertEqual(exposure_category("height (30-100 m above valley)"),"elevated_above_valley")
        self.assertEqual(exposure_category("southern oriented slope"),"slope")
        self.assertEqual(exposure_category("north-western oriented slope"),"slope")
        self.assertEqual(exposure_category("height: 10 m"),"unclassified")
        self.assertEqual(exposure_category("city street"),"unclassified")
        self.assertEqual(exposure_category(""),"unclassified")

    def test_real_metadata_encoding_and_site_labels(self):
        meta={"BAS":station("BAS"),"CHD":station("CHD")}
        b=("station_abbr;station_exposition_en\n"
           "BAS;height (30-100 m above valley)\n"
           "CHD;southern oriented slope\n").encode("utf-8")
        labels=station_exposures(b,meta)
        self.assertEqual(labels["BAS"]["category"],"elevated_above_valley")
        self.assertEqual(labels["CHD"]["category"],"slope")

    def test_altitude_weights_are_normalized_and_penalize_mismatch(self):
        target=station("TARGET",height=400.)
        nearby=station("S1",height=400.)
        mountain=station("S2",height=1400.)
        weights=altitude_and_exposure_weights(target,[(10.,nearby),(10.,mountain)],{},False)
        self.assertAlmostEqual(sum(x[2] for x in weights),1.)
        self.assertGreater(weights[0][2],weights[1][2])

    def test_exposure_conditioning_reduces_unmatched_exposure_donor_weight(self):
        target=station("TARGET")
        donors=[(10.,station("A")),(10.,station("B"))]
        exposures={"TARGET":{"category":"plain"},
                   "A":{"category":"plain"},"B":{"category":"slope"}}
        a=altitude_and_exposure_weights(target,donors,exposures,False)
        b=altitude_and_exposure_weights(target,donors,exposures,True)
        self.assertAlmostEqual(a[0][2],a[1][2])
        self.assertAlmostEqual(b[0][2],2*b[1][2])
        self.assertAlmostEqual(sum(x[2] for x in b),1.)

    def test_unclassified_exposure_is_neutral(self):
        t=station("T")
        donors=[(10.,station("A")),(10.,station("B"))]
        x={"T":{"category":"unclassified"},
           "A":{"category":"plain"},"B":{"category":"slope"}}
        self.assertEqual(altitude_and_exposure_weights(t,donors,x,False),
                         altitude_and_exposure_weights(t,donors,x,True))

    def test_target_must_not_be_calibration_donor(self):
        t=station("T")
        with self.assertRaisesRegex(AssertionError,"TARGET_LEAK"):
            altitude_and_exposure_weights(t,[(1.,t)],{},False)

    def test_calm_speed_has_zero_adjustment(self):
        c={"A":{m:{"scalar_bias_mps":2.,"u_bias_mps":1.,"v_bias_mps":1.} for m in range(1,13)}}
        chosen=[("A",10.,1.)]
        out=physical_correction(row(0.,None),1,chosen,c)
        self.assertEqual(out["speed"],0.)
        self.assertIsNone(out["direction"])
        slow=physical_correction(row(.5,90.),1,chosen,c)
        fast=physical_correction(row(3.,90.),1,chosen,c)
        self.assertAlmostEqual(slow["speed"],.5+2*.125)
        self.assertAlmostEqual(fast["speed"],3.+2*.5)

    def test_frozen_p8d_selections_do_not_include_own_station(self):
        self.assertEqual(set(FROZEN_2024_P8D_ALTITUDE),set(TARGETS))
        for target,donors in FROZEN_2024_P8D_ALTITUDE.items():
            self.assertEqual(len(donors),4)
            self.assertEqual(len(set(donors)),4)
            self.assertNotIn(target,donors)
        self.assertEqual(FROZEN_2024_P8D_ALTITUDE["MUB"],("BER","CRM","NEU","GRE"))

    def test_original_geographic_distance_remains_in_frozen_selector(self):
        t=station("BAS",lat=47.2,lon=7.4)
        meta={"BAS":t}
        for i,sid in enumerate(FROZEN_2024_P8D_ALTITUDE["BAS"]):
            meta[sid]=station(sid,lat=47.1+i*.1,lon=7.5)
        got=frozen_selection(t,meta)
        self.assertEqual([s["station_id"] for _,s in got],
                         list(FROZEN_2024_P8D_ALTITUDE["BAS"]))
        self.assertTrue(all(d >= 0 for d,_ in got))

    def test_method_order_is_frozen_and_has_real_p8d_baseline(self):
        self.assertEqual(METHODS[0],"era5")
        self.assertIn("f1_residual",METHODS)
        self.assertIn("p8d_frozen_altitude_idw4",METHODS)

    def test_paired_score_includes_unresolved_directions_not_dropped(self):
        base={
            "era5":row(1.,359.),
            "f1_residual":row(2.,None),
            "f2_altitude_shrunk":row(2.,0.),
            "f2_exposure_shrunk":row(2.,2.),
            "f1_distance_idw4":row(2.,355.),
            "p8d_frozen_altitude_idw4":row(2.,None),
        }
        rows=[(dt.datetime(2025,2,1),row(2.,1.),base)]
        scores=summarize(rows)
        self.assertEqual(scores["era5"]["direction_fixed90_deg"],2.)
        self.assertEqual(scores["f1_residual"]["direction_fixed90_deg"],90.)
        self.assertAlmostEqual(scores["f2_altitude_shrunk"]["direction_fixed90_deg"],1.)
        self.assertEqual(scores["p8d_frozen_altitude_idw4"]["direction_n_resolved"],0)
        self.assertAlmostEqual(scores["f1_residual"]["delta_mae_vs_era5_mps"],-1.)

    def test_common_hours_fail_closed(self):
        hourly={dt.datetime(2025,1,1):{k:row(2.,180.) for k in METHODS}}
        observed={dt.datetime(2025,1,1):row(3.,180.)}
        with self.assertRaisesRegex(ValueError,"F2_INSUFFICIENT_COMMON"):
            paired_site_rows(hourly,observed,"BAS")

    def test_bootstrap_seeded_and_paired(self):
        hours=[dt.datetime(2025,1,1)+dt.timedelta(hours=i) for i in range(8*24)]
        predicted={k:row(2.,180.) for k in METHODS}
        predicted["era5"]=row(1.,180.)
        rows=[(t,row(2.,180.),predicted) for t in hours]
        a=moving_block_delta_ci(rows,reps=25,seed=6)
        b=moving_block_delta_ci(rows,reps=25,seed=6)
        self.assertEqual(a,b)
        for key in METHODS[1:]:
            self.assertEqual(a[key]["delta_mae_vs_era5_observed_mps"],-1.)
            self.assertEqual(a[key]["block_bootstrap_95pct_interval_mps"],[-1.,-1.])

    def test_validation_year_is_2025_8760_hours(self):
        from p8_3f2_physical_era5 import YEAR
        self.assertEqual(YEAR,2025)
        self.assertEqual(len(annual_hours(YEAR)),8760)

    def test_f2_excludes_target_from_calibration(self):
        target=station("BAS")
        metadata={"BAS":target}
        with self.assertRaisesRegex(AssertionError,"TARGET_LEAK"):
            build_predictions(target,metadata,{"BAS":{"category":"plain"}},
                              {"BAS":{}},{},{})


if __name__=="__main__":
    unittest.main()
