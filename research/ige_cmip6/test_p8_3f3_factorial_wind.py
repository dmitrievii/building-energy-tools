"""P8.3F3 synthetic contracts: preregistered balanced ablation, source and anti-leakage."""
import datetime as dt
import math
import unittest
import numpy as np

from p8_3f3_factorial_wind import (
    METHODS, BASELINES, ALL_METHODS, F1, F2_ALT, F2_EXP, TARGETS,
    TRAIN_YEAR, TEST_YEARS, factors, variant_weights, exposure_category,
    source_exposure_map, select_four, residual_plan, corrected_prediction,
    paired_rows, score, factor_contrasts, bootstrap,
)


def station(name, lat=47., lon=8., z=450.):
    return {"station_id":name,"lat":lat,"lon":lon,"hoehe_m":z}


def wind(speed=2., direction=90.):
    return {"speed":float(speed),"direction":direction}


def synthetic_predictions(reference=2.):
    p={name:wind(reference) for name in ALL_METHODS}
    return p


class TestFactorialWind(unittest.TestCase):
    def test_32_distinct_variants_and_frozen_aliases(self):
        self.assertEqual(len(METHODS),32)
        self.assertEqual(len(set(METHODS)),32)
        self.assertEqual(set(factors(n) for n in METHODS),
                         {tuple(map(int,f"{i:05b}")) for i in range(32)})
        self.assertEqual(factors(F1),(0,0,0,0,0))
        self.assertEqual(factors(F2_ALT),(1,1,1,1,0))
        self.assertEqual(factors(F2_EXP),(1,1,1,1,1))

    def test_two_declared_2022_and_2025_holdouts(self):
        self.assertEqual(TRAIN_YEAR,2023)
        self.assertEqual(TEST_YEARS,(2022,2025))
        self.assertEqual(len(TARGETS),6)
        self.assertFalse(set(TARGETS)&{"ABO","BER","PAY","DAV","LUG","GVE","SIO","SMA","WYN","ZER"})

    def test_metadata_exposure_fallback(self):
        all_sites={sid:station(sid) for sid in TARGETS}
        raw=("station_abbr;station_exposition_en;station_exposition_de\n"
             + "\n".join(sid+";"+("plain" if sid=="MOE" else "")+";"
                         +("southern oriented slope" if sid=="MAS" else "")
                         for sid in TARGETS)+"\n").encode("utf-8")
        result=source_exposure_map(raw,all_sites)
        self.assertEqual(result["MOE"]["category"],"plain")
        self.assertEqual(result["MAS"]["category"],"slope")
        self.assertEqual(result["BOL"]["category"],"unclassified")
        self.assertNotIn("roughness_length_m",result["MOE"])

    def test_reject_missing_metadata_target(self):
        with self.assertRaisesRegex(ValueError,"F3_TARGET_EXPOSURE_UNAVAILABLE"):
            source_exposure_map(b"station_abbr;station_exposition_en\nMOE;plain\n",
                                {"MOE":station("MOE")})

    def test_selector_target_excluded(self):
        s=station("MOE")
        with self.assertRaisesRegex(AssertionError,"F3_TARGET_STATION_IN_CALIBRATION"):
            select_four(s,{"MOE":s},{"MOE":{}},0)

    def test_selection_physically_penalizes_altitude(self):
        target=station("MOE",z=100.)
        meta={"MOE":target}
        # Geographic distances are small; one distant-in-height donor should
        # lose to moderate-distance matching-height donors under altitude choice.
        for id_,i,z in (("A",1,100.),("B",2,100.),
                        ("C",3,100.),("D",4,1500.),("E",5,100.)):
            meta[id_]=station(id_,lat=47.+i*.015,z=z)
        calibrated={sid:{} for sid in meta if sid!="MOE"}
        distance=select_four(target,meta,calibrated,0)
        altitude=select_four(target,meta,calibrated,1)
        self.assertIn("D",[s["station_id"] for _,s in distance])
        self.assertNotIn("D",[s["station_id"] for _,s in altitude])
        self.assertIn("E",[s["station_id"] for _,s in altitude])

    def test_all_factor_weights_normalized_and_nonnegative(self):
        target=station("MOE",z=300.)
        donors=[(10.,station("A",z=310.)),(20.,station("B",z=1500.))]
        exposures={"MOE":{"category":"plain"},"A":{"category":"plain"},"B":{"category":"slope"}}
        for name in METHODS:
            w=variant_weights(target,donors,exposures,name)
            self.assertAlmostEqual(sum(x[2] for x in w),1.)
            self.assertTrue(all(math.isfinite(x[2]) and x[2]>=0 for x in w))
            self.assertEqual(len(w),2)

    def test_exposure_effect_is_independent_of_altitude_factor(self):
        target=station("MOE")
        donors=[(10.,station("A")),(10.,station("B"))]
        e={"MOE":{"category":"plain"},"A":{"category":"plain"},"B":{"category":"slope"}}
        no=variant_weights(target,donors,e,"S0_W0_H0_T0_E0")
        yes=variant_weights(target,donors,e,"S0_W0_H0_T0_E1")
        self.assertAlmostEqual(no[0][2],no[1][2])
        self.assertAlmostEqual(yes[0][2],2*yes[1][2])

    def test_unclassified_text_is_neutral(self):
        target=station("MOE")
        donors=[(10.,station("A")),(10.,station("B"))]
        e={"MOE":{"category":"unclassified"},"A":{"category":"plain"},"B":{"category":"slope"}}
        self.assertEqual(variant_weights(target,donors,e,"S0_W0_H0_T0_E0"),
                         variant_weights(target,donors,e,"S0_W0_H0_T0_E1"))

    def test_predictor_frozen_without_target_train_meteorology(self):
        target=station("MOE")
        meta={"MOE":target}
        calib={"MOE":{m:{"scalar_bias_mps":0,"u_bias_mps":0,"v_bias_mps":0}
                      for m in range(1,13)}}
        with self.assertRaisesRegex(AssertionError,"F3_TARGET_LEAKED_IN_TRAINING"):
            residual_plan(target,meta,calib,{})

    def test_shrink_only_ablation(self):
        correction={"scalar_bias_mps":2,"u_bias_mps":0,"v_bias_mps":0}
        full=corrected_prediction(wind(4.),correction,{"amplitude":1.,"taper":False})
        shrink=corrected_prediction(wind(4.),correction,{"amplitude":.5,"taper":False})
        self.assertAlmostEqual(full["speed"],6.)
        self.assertAlmostEqual(shrink["speed"],5.)

    def test_speed_taper_only_ablation(self):
        correction={"scalar_bias_mps":2,"u_bias_mps":0,"v_bias_mps":0}
        no=corrected_prediction(wind(1.),correction,{"amplitude":1.,"taper":False})
        yes=corrected_prediction(wind(1.),correction,{"amplitude":1.,"taper":True})
        self.assertAlmostEqual(no["speed"],3.)
        self.assertAlmostEqual(yes["speed"],2.)

    def test_zero_wind_taper_does_not_invent_wind(self):
        corr={"scalar_bias_mps":2,"u_bias_mps":1,"v_bias_mps":1}
        pred=corrected_prediction(wind(0.,None),corr,{"amplitude":.5,"taper":True})
        self.assertEqual(pred["speed"],0.)
        self.assertIsNone(pred["direction"])

    def test_common_hour_gate_and_target_missing(self):
        stamp=dt.datetime(2022,1,1)
        with self.assertRaisesRegex(ValueError,"F3_INSUFFICIENT_COMMON_HOURS"):
            paired_rows({stamp:synthetic_predictions()}, {stamp:wind()},2022,"MOE")
        with self.assertRaisesRegex(ValueError,"F3_INSUFFICIENT_COMMON_HOURS"):
            paired_rows({stamp:synthetic_predictions()}, {},2022,"MOE")

    def test_fixed_denominator_direction_score(self):
        row=synthetic_predictions(2.)
        row["era5"]=wind(1.,359.)
        row[F1]=wind(2.,None)
        observed=wind(2.,1.)
        metrics=score([(dt.datetime(2022,1,1),observed,row)])
        self.assertEqual(metrics["era5"]["direction_fixed90_deg"],2.)
        self.assertEqual(metrics[F1]["direction_fixed90_deg"],90.)
        self.assertEqual(metrics[F1]["direction_resolved_n"],0)
        self.assertEqual(metrics[F1]["speed_mae_mps"],0.)
        self.assertEqual(metrics["era5"]["speed_mae_mps"],1.)

    def test_balanced_factor_main_effect_and_interaction(self):
        # Loss increments are linear in S/W/H/T/E, with H*T interaction.
        fake={name:{"speed_mae_mps":(1+0.1*factors(name)[0]+
             0.2*factors(name)[1]+0.3*factors(name)[2]+
             0.4*factors(name)[3]+0.5*factors(name)[4]+
             0.7*factors(name)[2]*factors(name)[3])}
             for name in METHODS}
        c=factor_contrasts(fake)
        eff=c["factor_main_effect_on_speed_mae_mps"]
        self.assertAlmostEqual(eff["selection"],.1)
        self.assertAlmostEqual(eff["altitude_weight"],.2)
        self.assertAlmostEqual(eff["shrink"],.3+.7/2)
        self.assertAlmostEqual(eff["taper"],.4+.7/2)
        self.assertAlmostEqual(eff["exposure"],.5)
        interactions=c["factor_interaction_on_speed_mae_mps"]
        self.assertAlmostEqual(interactions["shrink_x_taper"],.7)
        self.assertAlmostEqual(interactions["altitude_weight_x_exposure"],0.)

    def test_bootstrap_reproducible_and_gap_fails_closed(self):
        times=[dt.datetime(2022,1,1)+dt.timedelta(hours=i) for i in range(8*24)]
        preds=synthetic_predictions(2.)
        preds["era5"]=wind(1.)
        rows=[(t,wind(2.),preds) for t in times]
        a=bootstrap(rows,2022,"MOE",reps=20)
        self.assertEqual(a,bootstrap(rows,2022,"MOE",reps=20))
        for name in (F1,F2_ALT,F2_EXP):
            self.assertEqual(a[name]["interval_95pct_mps"],[-1.,-1.])
        broken=[(t+dt.timedelta(hours=2*i),obs,p) for i,(t,obs,p) in enumerate(rows)]
        with self.assertRaisesRegex(ValueError,"F3_NO_CONTIGUOUS"):
            bootstrap(broken,2022,"MOE",reps=10)

    def test_reject_unsupported_test_year(self):
        from p8_3f3_factorial_wind import run
        with self.assertRaisesRegex(ValueError,"NOT_PREREGISTERED"):
            run(2024,"some_temp_dir")


if __name__=="__main__":
    unittest.main()
