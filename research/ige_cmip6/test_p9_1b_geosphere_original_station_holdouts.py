"""IGE P9.1B original QC-heldout Austrian station vs fixed ERA5 model contract."""
import datetime as dt
import math
import unittest
import p9_1b_geosphere_original_station_holdouts as p


def metadata():
    return {
        "parameters":[{"name":"tl","unit":"°C"},{"name":"tl_flag","unit":"-"}],
        "stations":[
            {"id":30,"name":"Graz Universität","lat":47.08,"lon":15.44,"altitude":367},
            {"id":39,"name":"Innsbruck","lat":47.27,"lon":11.39,"altitude":578},
            {"id":196,"name":"Patscherkofel","lat":47.21,"lon":11.46,"altitude":2250},
        ],
    }


def observed():
    n=168;first=dt.datetime(2023,1,10,tzinfo=dt.timezone.utc)
    times=[(first+dt.timedelta(hours=i)).isoformat() for i in range(n)]
    f=[]
    for sid in p.IDS:
        f.append({"properties":{
            "station":sid,"parameters":{
                "tl":{"unit":"°C","data":[10.0]*n},
                "tl_flag":{"data":[10]*n},
            }}})
    return {"timestamps":times,"features":f}


class P91IndependentGeoSphereContracts(unittest.TestCase):
    def test_metadata_requires_real_station_coords_and_elevation(self):
        r=p.extract_metadata(metadata())
        self.assertEqual(set(r),{30,39,196})
        self.assertEqual(r[196]["altitude_m"],2250)

    def test_source_metadata_missing_registered_station_rejected(self):
        m=metadata();m["stations"]=m["stations"][:-1]
        with self.assertRaisesRegex(ValueError,"REGISTERED_STATION_MISSING"):
            p.extract_metadata(m)

    def test_observed_original_axis_and_quality_flags(self):
        r=p.decode_observed(observed(),set(p.IDS),"2023-01-10","2023-01-16")
        self.assertEqual(len(r[30]),168)
        self.assertIn("2023-01-10T00:00",r[30])

    def test_original_station_missing_flag_rejected(self):
        x=observed();x["features"][0]["properties"]["parameters"].pop("tl_flag")
        with self.assertRaisesRegex(ValueError,"NO_SOURCE_TEMPERATURE_QC"):
            p.decode_observed(x,set(p.IDS),"2023-01-10","2023-01-16")

    def test_qc_not_accepting_unknown_flag_no_station_leakage(self):
        x=observed()
        x["features"][0]["properties"]["parameters"]["tl_flag"]["data"]=[99]*168
        r=p.decode_observed(x,set(p.IDS),"2023-01-10","2023-01-16")
        model={"hourly":{"time":list(r[39]),
                         "temperature_2m":[10.0]*168}}
        with self.assertRaisesRegex(ValueError,"NOT_ENOUGH_REAL_QC"):
            p.compare_era5_model_to_station(model,r[30])

    def test_independent_model_matches_zero_MAE_without_calibration(self):
        times=list(p.decode_observed(observed(),set(p.IDS),
                 "2023-01-10","2023-01-16")[30])
        model={"hourly":{"time":times,"temperature_2m":[11.0]*168}}
        obs=dict.fromkeys(times,10.)
        score=p.compare_era5_model_to_station(model,obs)
        self.assertEqual(score["QC_accepted_matched_hours"],168)
        self.assertAlmostEqual(score["temperature_raw_grid_vs_station_MAE_C"],1)
        self.assertAlmostEqual(score["temperature_raw_grid_vs_station_bias_C"],1)
        self.assertFalse(score["lapse_orography_correction_applied"])

    def test_hourly_shift_cannot_silently_repair(self):
        x=observed();x["timestamps"][1]=x["timestamps"][0]
        with self.assertRaisesRegex(ValueError,"OBSERVED_UTC_AXIS"):
            p.decode_observed(x,set(p.IDS),"2023-01-10","2023-01-16")

    def test_results_do_not_overstate_global_validation(self):
        self.assertEqual(len(p.IDS),3)
        self.assertEqual(len(p.PERIODS),2)
        self.assertEqual(p.MIN_PAIRS,120)


if __name__=="__main__":unittest.main()
