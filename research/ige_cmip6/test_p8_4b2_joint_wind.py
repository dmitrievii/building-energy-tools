"""IGE P8.4B2 registered source-only joint wind suitability contract tests."""
import datetime as dt
import math
import unittest
from p8_4b2_joint_wind import (
    TRAIN_YEAR,EVALUATION_YEARS,TARGETS,METHODS,CANDIDATES,DONORS,
    TRAIN_CADENCE_H,TRAIN_YEAR,train_hours,source_three_years,
    donor_pair_direction_dissimilarity,candidate_pool,
    joint_source_coherence_selector,selected_donors,union_direction,
    paired_predictions,method_metrics,equal_hour_joint_inference,
    speed_effect_pairs,calendar_block_ci,evaluate_gates,
    COEFFICIENT_GEOMETRY,COEFFICIENT_DIRECTION,COEFFICIENT_COVERAGE,
)
from p8_1e_swiss_external import haversine


def row(speed=3.,direction=90.):
    return {"speed":speed,"direction":direction}


def station(name,lat,lon,z=500):
    return {"station_id":name,"lat":float(lat),"lon":float(lon),"hoehe_m":float(z)}


def donors():
    m={"DIA":station("DIA",47.0,8.0)}
    for i,name in enumerate(("AAA","AAB","AAC","AAD","AAE","AAF",
                              "AAG","AAH","AAI","AAJ","AAK","AAL")):
        m[name]=station(name,47.0+i*.002,8.01+i*.006,500+i*5)
    return m


def training_data(metadata):
    return {sid:{t:row(3.,90.) for t in train_hours()}
            for sid in metadata if sid not in TARGETS}


def fake_predictions(year=2024):
    hours=tuple(dt.datetime(year,1,2)+dt.timedelta(hours=h) for h in range(48))
    methods={}
    for i,m in enumerate(METHODS):
        methods[m]={
            t:{
                "reference_speed":3.,"reference_direction":90.,
                "scalar":3.+i*.1,
                "vector_direction":90. if i!=2 or t!=hours[0] else None,
                "unit_direction":91.,"nearest_direction":90.,
                "unit_resultant":.98,
            } for t in hours
        }
    return hours,methods


class B2Contracts(unittest.TestCase):
    def test_frozen_2023_source_training_and_2024_2025_holdouts(self):
        self.assertEqual(TRAIN_YEAR,2023)
        self.assertEqual(EVALUATION_YEARS,(2024,2025))
        self.assertEqual(TARGETS,("DIA","CDM","GRE","BIZ","SAE","CRM"))
        self.assertEqual(METHODS,("distance_idw4","altitude_idw4","joint_source_coherence_idw4"))

    def test_training_1460_predetermined_sixhour_steps(self):
        self.assertEqual(len(train_hours()),1460)
        self.assertEqual(train_hours()[0],dt.datetime(2023,1,1))
        self.assertEqual(train_hours()[-1],dt.datetime(2023,12,31,18))
        self.assertEqual(TRAIN_CADENCE_H,6)

    def test_frozen_objective_coefficients_sum_to_one(self):
        self.assertEqual(CANDIDATES,10)
        self.assertEqual(DONORS,4)
        self.assertAlmostEqual(
            COEFFICIENT_GEOMETRY+COEFFICIENT_DIRECTION+COEFFICIENT_COVERAGE,1.)

    def test_original_source_three_year_parser_no_2022_or_mixed_sites(self):
        data=("\n".join([
            "station_abbr;reference_timestamp;fkl010h0;dkl010h0",
            "AAA;01.01.2022 00:00;3;90",
            "AAA;01.01.2023 00:00;2;360",
            "AAA;01.01.2023 01:00;7;135",
            "AAA;01.01.2024 00:00;3;180",
            "BBB;01.01.2025 00:00;8;90",
            "AAA;01.01.2025 00:00;0;",
        ])+"\n").encode()
        parsed,flags=source_three_years(data,"AAA")
        self.assertFalse(flags)
        self.assertEqual(parsed[2023][dt.datetime(2023,1,1)]["direction"],0.)
        self.assertEqual(len(parsed[2023]),1)
        self.assertEqual(len(parsed[2024]),1)
        self.assertEqual(len(parsed[2025]),1)
        self.assertIsNone(parsed[2025][dt.datetime(2025,1,1)]["direction"])

    def test_duplicate_training_stamp_detected(self):
        data=("station_abbr;reference_timestamp;fkl010h0;dkl010h0\n"
              "AAA;01.01.2023 00:00;2;90\n"
              "AAA;01.01.2023 00:00;2;90\n").encode()
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            source_three_years(data,"AAA")

    def test_census_independent_target_id_excluded_from_candidates(self):
        m=donors()
        ids=set(m)-{"DIA"}
        ranked=candidate_pool(m["DIA"],m,ids)
        self.assertEqual(len(ranked),10)
        self.assertFalse(any(x[2]=="DIA" for x in ranked))

    def test_target_cannot_be_donor_even_with_valid_meta(self):
        m=donors()
        with self.assertRaisesRegex(AssertionError,"TARGET_DONOR_LEAK"):
            candidate_pool(m["DIA"],m,set(m))

    def test_circular_difference_wrap_noncalm(self):
        stamps=train_hours()
        a={t:row(3.,359.) for t in stamps}
        b={t:row(3.,1.) for t in stamps}
        diff,n,insufficient=donor_pair_direction_dissimilarity(
            "AAA","BBB",{"AAA":a,"BBB":b})
        self.assertEqual(n,1460)
        self.assertFalse(insufficient)
        self.assertAlmostEqual(diff,2/180)

    def test_unknown_training_direction_pair_has_conservative_penalty(self):
        stamps=train_hours()
        a={t:row(3.,0.) for t in stamps[:80]}
        b={t:row(3.,0.) for t in stamps[:80]}
        d,n,insufficient=donor_pair_direction_dissimilarity(
            "AAA","BBB",{"AAA":a,"BBB":b})
        self.assertEqual(n,80)
        self.assertTrue(insufficient)
        self.assertEqual(d,1.)

    def test_joint_selection_210_combinations_and_training_only(self):
        m=donors()
        chosen,proof=joint_source_coherence_selector(m["DIA"],m,
                    set(m)-{"DIA"},training_data(m))
        self.assertEqual(len(chosen),4)
        self.assertEqual(proof["search_combinations"],210)
        self.assertEqual(proof["frozen_training_year"],2023)
        self.assertTrue(proof["no_target_observations_used"])
        self.assertEqual(len(proof["candidate_ids"]),10)
        self.assertNotIn("DIA",proof["chosen_ids"])

    def test_frozen_selections_include_three_distinct_labels(self):
        m=donors()
        choices,_=selected_donors(m["DIA"],m,set(m)-{"DIA"},training_data(m))
        self.assertEqual(set(choices),set(METHODS))
        self.assertTrue(all(len(x)==4 for x in choices.values()))

    def test_direction_fallback_no_invented_vector(self):
        x={"vector_direction":None,"unit_direction":275.}
        self.assertEqual(union_direction(x),275.)
        x["vector_direction"]=0.
        self.assertEqual(union_direction(x),0.)
        x["unit_direction"]=None
        x["vector_direction"]=None
        self.assertIsNone(union_direction(x))

    def test_direction_scored_only_on_same_reference_noncalm(self):
        hours,p=fake_predictions()
        score=[method_metrics("DIA",2024,m,p,hours) for m in METHODS]
        self.assertEqual({r["n_common_full_year_hours"] for r in score},{48})
        self.assertEqual({r["n_reference_noncalm"] for r in score},{48})
        self.assertEqual({r["union_coverage_pct"] for r in score},{100.})
        self.assertEqual(score[2]["vector_n_resolved"],47)
        self.assertEqual(score[2]["unit_n_resolved"],48)

    def test_three_selector_strict_direction_eligible_hours(self):
        hours,p=fake_predictions()
        inference=equal_hour_joint_inference("DIA",2024,p,hours)
        self.assertEqual(inference["n_three_selector_resolved_direction_hours"],48)

    def test_speed_loss_effect_is_joint_minus_altitude(self):
        hours,p=fake_predictions()
        pairs=speed_effect_pairs(p,hours)
        self.assertEqual(len(pairs),48)
        self.assertTrue(all(abs(x[1]-.1)<1e-10 for x in pairs))

    def test_leap_year_seven_day_bootstrap(self):
        start=dt.datetime(2024,1,1)
        pairs=tuple((start+dt.timedelta(hours=i),-.2) for i in range(8784))
        x=calendar_block_ci(pairs,2024,"DIA",reps=40)
        y=calendar_block_ci(pairs,2024,"DIA",reps=40)
        self.assertEqual(x,y)
        self.assertEqual(x["calendar_days"],366)
        self.assertEqual(x["n_paired_hours"],8784)
        self.assertAlmostEqual(x["CI95_low_mps"],-.2,places=8)

    def test_nonleap_year_seven_day_bootstrap(self):
        start=dt.datetime(2025,1,1)
        pairs=tuple((start+dt.timedelta(hours=i),.07) for i in range(8760))
        x=calendar_block_ci(pairs,2025,"DIA",reps=30)
        self.assertEqual(x["calendar_days"],365)
        self.assertAlmostEqual(x["delta_MAE_mps"],.07,places=8)

    def test_bootstrap_rejects_wrong_year(self):
        with self.assertRaisesRegex(ValueError,"OUTSIDE"):
            calendar_block_ci(((dt.datetime(2022,1,1),-.1),),2025,"DIA",reps=40)

    def test_joint_acceptance_requires_six_sites(self):
        with self.assertRaisesRegex(ValueError,"NOT_SIX"):
            evaluate_gates([],2025)

    def test_joint_acceptance_denies_speed_gain_at_expense_of_coverage(self):
        entries=[]
        for site in TARGETS:
            scores=[]
            for method in METHODS:
                improved=method=="joint_source_coherence_idw4"
                scores.append({
                    "method":method,
                    "scalar_speed_MAE_mps":.8 if improved else 1.0,
                    "union_coverage_pct":75. if improved else 95.,
                    "union_fixed90_missing_diagnostic_deg":55. if improved else 50.,
                })
            entries.append({"site":site,"year":2025,"metrics":scores})
        check=evaluate_gates(entries,2025)
        self.assertFalse(check["joint_selection_accepted"])
        self.assertTrue(check["gates"]["equal_site_speed_MAE_nonworsening"])
        self.assertFalse(check["gates"]["equal_site_direction_coverage_within_minus_2pp"])


if __name__=="__main__":
    unittest.main()
