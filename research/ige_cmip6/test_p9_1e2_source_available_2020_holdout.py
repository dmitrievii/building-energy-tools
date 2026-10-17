"""P9.1E2 availability-only sampling is a post-E1 exploratory scientific cohort."""
import datetime as dt
import unittest
import p9_1e2_source_available_2020_geographic_holdout as e

class CohortQA(unittest.TestCase):
    def test_01_original_E1_negative_is_not_rewritten(self):
        self.assertEqual(len(e.regular.LOWLAND_TARGETS),6)
        self.assertEqual(e.INDEPENDENT_2020_HOLDOUT[0][1],"2020-01-10")
        self.assertEqual(e.QC_WINDOWS[0][1],"2021-01-10")

    def test_02_previous_nine_alpine_stations_excluded_by_geometry_selection(self):
        src=[{"id":30,"name":"old","lat":48.249,"lon":16.356,"altitude":220},
             {"id":100,"name":"new","lat":48.251,"lon":16.355,"altitude":230}]
        picked=e.freeze_geography_only_candidates({"stations":src})
        self.assertEqual(picked["Vienna"][0]["id"],100)

    def test_03_source_availability_is_not_error_or_hourly_target_temperature(self):
        import inspect
        self.assertEqual(set(inspect.signature(e.read_original_qc_eligibility).parameters),
                         {"data","requested_ids","start","end"})

    def test_04_2021_original_source_counts_only_qc_flags_and_missing(self):
        stamps=[(dt.datetime(2021,1,10,tzinfo=dt.timezone.utc)
                 +dt.timedelta(hours=i)).isoformat() for i in range(168)]
        record={"timestamps":stamps,"features":[{"properties":{"station":111,"parameters":{
            "tl":{"data":[-5.]*168},"tl_flag":{"data":[10]*150+[99]*18}}}}]}
        self.assertEqual(e.read_original_qc_eligibility(record,{111},"2021-01-10","2021-01-16")[111],150)

    def test_05_missing_source_station_means_zero_not_replacement(self):
        stamps=[(dt.datetime(2021,1,10,tzinfo=dt.timezone.utc)
                 +dt.timedelta(hours=i)).isoformat() for i in range(168)]
        record={"timestamps":stamps,"features":[]}
        self.assertEqual(e.read_original_qc_eligibility(record,{111},"2021-01-10","2021-01-16")[111],0)

    def test_06_bad_hour_alignment_refuses_QC_eligibility(self):
        record={"timestamps":["2021-01-10T00:00Z"],"features":[]}
        with self.assertRaisesRegex(ValueError,"QC_TIME_AXIS_INVALID"):
            e.read_original_qc_eligibility(record,{111},"2021-01-10","2021-01-16")

    def test_07_observation_source_minimum_120_hours_frozen(self):
        self.assertEqual(e.MIN_COVERAGE,120)
        self.assertEqual(e.MAX_STATION_DISTANCE_KM,35.)
        self.assertEqual(e.MAX_SOURCE_CANDIDATES_PER_TARGET,12)

if __name__=="__main__":
    unittest.main()
