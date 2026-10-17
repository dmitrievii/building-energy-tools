"""IGE P8.4B3 metadata-only 18 novel Swiss stations, frozen model/holdout tests."""
import math
import unittest
from p8_4b3_independent_sites import (
    BIN_COUNTS,N_SITES,SPACING_KM,SOURCE_BLOCK_RADIUS_KM,PRIOR_TARGETS,
    choose_new_targets,geometrically_blocked,registered_research_gates,
    EXPECTED_WEIGHTS,SCIENTIFIC_MIN_EFFECT_MPS,SCIENTIFIC_IMPROVED_SITES,
    SCIENTIFIC_NONWORSE_SITES,
)
from p8_1e_swiss_external import haversine
import p8_4b2_joint_wind as b2


def station(site,latitude,longitude,height):
    return {"station_id":site,"lat":latitude,"lon":longitude,
            "hoehe_m":height}


def generated_metadata():
    sites={}
    # 3 bins of 9 options with >20 km separation in each bin.
    # Make all bins mutually geographically separated.
    for j,z in enumerate((300,900,1700)):
        for i in range(9):
            sid=f"{chr(65+j)}{chr(65+i//3)}{chr(65+i%3)}"
            sites[sid]=station(sid,46.0+j*.60+(i//3)*.17,6.1+(i%3)*.29+j*.08,z)
    return sites


def site_run(site,year,scenario,baseline=1.0,speed_delta=-.04,
             coverage_delta=0.,direction_delta=-.5):
    return {
        "site":site,"year":year,"scenario":scenario,
        "result":{"metrics":[
            {"method":"distance_idw4","scalar_speed_MAE_mps":baseline+0.2,
             "union_coverage_pct":94.,
             "union_fixed90_missing_diagnostic_deg":52.},
            {"method":"altitude_idw4","scalar_speed_MAE_mps":baseline,
             "union_coverage_pct":95.,
             "union_fixed90_missing_diagnostic_deg":48.},
            {"method":"joint_source_coherence_idw4",
             "scalar_speed_MAE_mps":baseline+speed_delta,
             "union_coverage_pct":95.+coverage_delta,
             "union_fixed90_missing_diagnostic_deg":48.+direction_delta},
        ]}
    }


class TestRegisteredUnseenStations(unittest.TestCase):
    def test_previously_evaluated_targets_excluded(self):
        for sid in ("ABO","BER","PAY","AIG","THU","INT","RAG","ZER","VIT",
                    "DIA","CDM","GRE","BIZ","SAE","CRM"):
            self.assertIn(sid,PRIOR_TARGETS)

    def test_six_per_bin_18_total_frozen(self):
        self.assertEqual(BIN_COUNTS,
            (("low",0.,600.,6),("mid",600.,1300.,6),("high",1300.,5000.,6)))
        self.assertEqual(N_SITES,18)
        self.assertEqual(SPACING_KM,15.)
        self.assertEqual(SOURCE_BLOCK_RADIUS_KM,25.)

    def test_exact_original_frozen_b2_weights(self):
        self.assertEqual(EXPECTED_WEIGHTS,(.65,.25,.10))
        self.assertEqual((b2.COEFFICIENT_GEOMETRY,b2.COEFFICIENT_DIRECTION,
                          b2.COEFFICIENT_COVERAGE),EXPECTED_WEIGHTS)

    def test_selection_reproducible_and_metadata_only(self):
        source=generated_metadata()
        a,g=choose_new_targets(source,set(source))
        b,h=choose_new_targets(source,set(source))
        self.assertEqual(a,b)
        self.assertEqual(g,h)
        self.assertEqual(len(a),18)
        self.assertEqual([len(g[k]) for k in ("low","mid","high")],[6,6,6])
        self.assertEqual(set(a).intersection(PRIOR_TARGETS),set())

    def test_minimum_new_target_separation(self):
        source=generated_metadata()
        result,_=choose_new_targets(source,set(source))
        for i,x in enumerate(result):
            for y in result[i+1:]:
                self.assertGreaterEqual(haversine(
                    source[x]["lat"],source[x]["lon"],
                    source[y]["lat"],source[y]["lon"]),15.)

    def test_station_availability_exclusion_not_replaced(self):
        source=generated_metadata()
        low={sid for sid,v in source.items() if v["hoehe_m"]==300}
        available=set(source)-low
        with self.assertRaisesRegex(ValueError,"ALTITUDE_BIN"):
            choose_new_targets(source,available)

    def test_geographic_buffer_excludes_close_source(self):
        m={"AIG":station("AIG",47.,8.,300.),
           "AAA":station("AAA",47.,8.01,350.),
           "BBB":station("BBB",47.,8.5,350.),
           "CCC":station("CCC",46.5,8.,600.)}
        q=geometrically_blocked(m["AIG"],m,{"AAA","BBB","CCC"})
        self.assertNotIn("AAA",q)
        self.assertEqual(q,{"BBB","CCC"})

    def test_registered_acceptance_all_seven_gates(self):
        sites=[f"A{i:02d}" for i in range(18)]
        rows=[site_run(s,2024,"unbuffered") for s in sites]
        score=registered_research_gates(rows,2024,"unbuffered")
        self.assertTrue(score["passed"])
        self.assertEqual(len(score["gates"]),7)
        self.assertEqual(score["n_improved_by_at_least_0p02"],18)

    def test_zero_change_fails_material_gain_even_with_ties(self):
        rows=[site_run(f"A{i:02d}",2025,"exclude_25km",
                       speed_delta=0.,direction_delta=0.) for i in range(18)]
        x=registered_research_gates(rows,2025,"exclude_25km")
        self.assertFalse(x["passed"])
        self.assertFalse(x["gates"]["material_equal_site_MAE_gain_0p02mps"])
        self.assertFalse(x["gates"]["at_least_six_sites_gain_0p02mps"])

    def test_one_site_too_large_wind_speed_deterioration_fails(self):
        rows=[site_run(f"A{i:02d}",2024,"unbuffered",
                       speed_delta=.2 if i==0 else -.08) for i in range(18)]
        r=registered_research_gates(rows,2024,"unbuffered")
        self.assertFalse(r["passed"])
        self.assertFalse(r["gates"]["no_site_speed_deterioration_gt_0p15mps"])

    def test_direction_coverage_not_hidden_by_speed_gain(self):
        rows=[site_run(f"A{i:02d}",2024,"unbuffered",
                       coverage_delta=-11. if i==5 else 0.) for i in range(18)]
        r=registered_research_gates(rows,2024,"unbuffered")
        self.assertFalse(r["gates"]["no_site_union_direction_coverage_loss_gt_10pp"])

    def test_fewer_than_eighteen_rejected(self):
        with self.assertRaisesRegex(ValueError,"MISSING_18"):
            registered_research_gates(
                [site_run(f"A{i:02d}",2024,"unbuffered") for i in range(17)],
                2024,"unbuffered")

    def test_unchanged_subset_must_not_be_called_widespread_gain(self):
        rows=[site_run(f"A{i:02d}",2024,"unbuffered",
                       speed_delta=-.3 if i==0 else 0.) for i in range(18)]
        r=registered_research_gates(rows,2024,"unbuffered")
        self.assertFalse(r["passed"])
        self.assertFalse(r["gates"]["at_least_six_sites_gain_0p02mps"])

    def test_two_years_2024_leap_and_2025_nonleap(self):
        self.assertEqual(b2.EVALUATION_YEARS,(2024,2025))
        self.assertEqual(len(b2.train_hours()),1460)
        self.assertEqual((SCIENTIFIC_MIN_EFFECT_MPS,
                         SCIENTIFIC_IMPROVED_SITES,SCIENTIFIC_NONWORSE_SITES),
                         (.02,6,12))


if __name__=="__main__":
    unittest.main()
