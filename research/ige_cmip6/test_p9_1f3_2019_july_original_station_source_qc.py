"""P9.1F3 source forensic counts never relax original GeoSphere QC."""
import datetime as dt
import unittest
import p9_1f3_2019_july_original_station_source_qc as f

def fake(values=None,flags=None):
    if values is None:values=[1.]*168
    if flags is None:flags=[10]*168
    t0=dt.datetime(2019,7,10,tzinfo=dt.timezone.utc)
    times=[(t0+dt.timedelta(hours=i)).isoformat() for i in range(168)]
    return {"timestamps":times,"features":[
        {"properties":{"station":105,"parameters":{
            "tl":{"data":values},"tl_flag":{"data":flags}}}}]}

class SourceCounts(unittest.TestCase):
    def test_original_9_registered_sites_unchanged(self):
        self.assertEqual(len(f.study.IDS),9)
        self.assertEqual(len(f.PERIODS),5)
        self.assertEqual(f.PERIODS[2][0],"july_2019")

    def test_only_accepted_original_QC_counts(self):
        x=f.original_source_qc_metadata_only(fake(flags=[10]*50+[99]*118),
                                             (105,),"2019-07-10","2019-07-16")
        self.assertEqual(x[0]["temperature_nonmissing_hour_count"],168)
        self.assertEqual(x[0]["original_QC_accepted_hour_count"],50)
        self.assertEqual(x[0]["original_QC_flag_frequencies"],{"10":50,"99":118})

    def test_missing_original_temperature_is_not_invented(self):
        values=[None]*168;flags=[10]*168
        result=f.original_source_qc_metadata_only(fake(values,flags),(105,),
                                                  "2019-07-10","2019-07-16")
        self.assertEqual(result[0]["original_QC_accepted_hour_count"],0)
        self.assertEqual(result[0]["temperature_nonmissing_hour_count"],0)

    def test_unreported_registered_station_is_explicit_zero(self):
        result=f.original_source_qc_metadata_only(fake(),(105,14305),
                                                  "2019-07-10","2019-07-16")
        self.assertEqual(result[1]["source_station_id"],14305)
        self.assertFalse(result[1]["source_feature_present"])
        self.assertEqual(result[1]["original_QC_accepted_hour_count"],0)

    def test_wrong_UTC_record_timestamps_never_counted(self):
        b=fake();b["timestamps"][0]=b["timestamps"][1]
        with self.assertRaisesRegex(ValueError,"TIME_AXIS_GAP"):
            f.original_source_qc_metadata_only(b,(105,),"2019-07-10","2019-07-16")

    def test_source_only_diagnostic_does_not_score_target_temperature(self):
        import inspect
        s=inspect.signature(f.original_source_qc_metadata_only)
        self.assertEqual(set(s.parameters),{"result","sids","start","end"})

if __name__=="__main__":
    unittest.main()
