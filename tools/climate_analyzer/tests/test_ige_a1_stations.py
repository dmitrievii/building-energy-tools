"""A1 scientific source/clock/QC contracts and pure residual mathematics.

Provider observations below are synthetic. Real inputs are metadata only.
No heldout observation or model endpoint is read by this test module.
"""
from __future__ import annotations
from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.station_reconstruction import (
    StationReference, decode_dwd_hourly, decode_geosphere_hourly, decode_meteoswiss_hourly,
    model_reference_operator, select_donors, reconstruct_temperature, T, RH, P,
)

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("ige_a1_prepare",ROOT/"research/ige_cmip6/a1_prepare.py")
preparation = importlib.util.module_from_spec(spec); spec.loader.exec_module(preparation)


def station(country="DE", sid="1", latitude=48., longitude=10., *, group="", history=True):
    return StationReference(country,sid,"synthetic",latitude,longitude,500.,"a"*64,group,history)


def temperature(values, clock=None, operator="published_nominal_node"):
    result = pd.Series(values,index=clock if clock is not None else pd.date_range("2025-01-10",periods=len(values),freq="h",tz="UTC"))
    result.attrs.update({"reference_operator":operator,"unit":"°C"})
    return result


class ProviderAdapterTests(unittest.TestCase):
    def test_DWD_absolute_P0_is_not_swapped_with_reduced_P(self):
        raw=b"STATIONS_ID;MESS_DATUM;QN_8;P;P0;eor\n1;2025011000;10;1020;980;eor\n"
        batch=decode_dwd_hourly(raw,station(),product="P0")
        self.assertEqual(batch.data[P].iloc[0],98000.)
        self.assertEqual(batch.fields[P]["pressure_kind"],"absolute_at_station_barometer")

    def test_DWD_missing_P0_never_falls_back_to_numeric_reduced_pressure(self):
        for extra in ("", ";P0"):
            suffix="" if not extra else ";-999"
            raw=("STATIONS_ID;MESS_DATUM;QN_8;P"+extra+"\n1;2025011000;10;1020"+suffix+"\n").encode()
            batch=decode_dwd_hourly(raw,station(),product="P0")
            self.assertTrue(pd.isna(batch.data[P].iloc[0]))
            self.assertFalse(batch.data["quality_accepted__"+P].iloc[0])

    def test_DWD_hourly_and_urban_pressure_schemas_are_not_interchangeable(self):
        urban=b"STATIONS_ID;MESS_DATUM;QN;PP_ST_10;P0_ST_10\n1;202501100000;10;1020;980\n"
        with self.assertRaises(ValueError):decode_dwd_hourly(urban,station(),product="P0")

    def test_DWD_QN10_and_QN3_remain_separate(self):
        raw=b"STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU\n1;2025011000;10;1;90\n1;2025011001;3;2;80\n"
        batch=decode_dwd_hourly(raw,station())
        self.assertEqual(batch.data["quality_accepted__"+T].tolist(),[True,False])
        self.assertEqual(batch.data["secondary_quality__"+T].tolist(),[False,True])
        self.assertEqual(batch.fields[T]["time_operator"],"unknown")

    def test_DWD_cross_station_duplicates_or_malformed_hour_fail(self):
        for lines in ("2;2025011000;10;2;80", "1;2025011000;10;2;80\n1;2025011000;10;3;80", "1;202501100000;10;2;80"):
            with self.subTest(lines=lines),self.assertRaises(ValueError):
                decode_dwd_hourly(("STATIONS_ID;MESS_DATUM;QN_9;TT_TU;RF_TU\n"+lines+"\n").encode(),station())

    def geo(self, flags):
        n=len(flags)
        obj={"timestamps":[t.isoformat() for t in pd.date_range("2025-01-10",periods=n,freq="h",tz="UTC")],
            "features":[{"properties":{"station":"1","parameters":{
                "tl":{"unit":"°C","data":[-5.]*n},"tl_flag":{"data":flags},
                "rf":{"unit":"%","data":[90.]*n},"rf_flag":{"data":flags},
                "p":{"unit":"hPa","data":[980.]*n},"p_flag":{"data":flags}}}}]}
        return obj

    def test_AT_QC_origin_and_manual_vs_auto_are_not_collapsed(self):
        raw=json.dumps(self.geo([22,21,20,12,11,10,0])).encode()
        batch=decode_geosphere_hourly(raw,station("AT"))
        self.assertEqual(batch.data["quality_accepted__"+T].tolist(),[True,False,False,False,False,False,False])
        self.assertEqual(batch.data["secondary_quality__"+T].tolist(),[False,False,False,True,False,False,False])
        self.assertTrue((batch.data[P]==98000).all())

    def test_AT_missing_QC_naive_clock_or_bad_unit_fail(self):
        for mode in ("QC","clock","unit"):
            obj=self.geo([22])
            if mode=="QC":del obj["features"][0]["properties"]["parameters"]["tl_flag"]
            elif mode=="clock":obj["timestamps"]=["2025-01-10T00:00"]
            else:obj["features"][0]["properties"]["parameters"]["p"]["unit"]="Pa"
            with self.subTest(mode=mode),self.assertRaises(ValueError):decode_geosphere_hourly(json.dumps(obj).encode(),station("AT"))

    def test_RH_and_pressure_means_are_not_turned_into_observed_q(self):
        batch=decode_geosphere_hourly(json.dumps(self.geo([22])).encode(),station("AT"))
        self.assertEqual(batch.fields[RH]["RH_phase"],"SOURCE_PHASE_UNVERIFIED")
        self.assertNotIn("specific_humidity_kg_kg",batch.data)
        self.assertFalse(batch.data.attrs["pressure_and_TRH_collocated_assumed"])

    def test_Swiss_hourly_support_units_QFE_and_missing_sentinel(self):
        raw=b"station_abbr;reference_timestamp;tre200h0;ure200h0;prestah0;pp0qffh0\nBAS;10.01.2025 01:00;2;80;980;1020\nBAS;10.01.2025 02:00;;80;;1020\n"
        batch=decode_meteoswiss_hourly(raw,station("CH","BAS"))
        self.assertEqual(batch.fields[T]["time_operator"],"mean_six_10min_nominal_nodes")
        self.assertEqual(batch.data[P].iloc[0],98000)
        self.assertTrue(pd.isna(batch.data[P].iloc[1]))
        self.assertTrue(pd.isna(batch.data[T].iloc[1]))
        self.assertEqual(str(batch.data.index[0]),"2025-01-10 01:00:00+00:00")
        self.assertIn("not QC10-equivalent",batch.data.attrs["quality_policy"]["label"])

    def test_Swiss_pre2018_support_and_unknown_QC_flag_block(self):
        for text in ("station_abbr;reference_timestamp;tre200h0\nBAS;10.01.2017 01:00;2\n",
                "station_abbr;reference_timestamp;tre200h0;tre200h0_qc\nBAS;10.01.2025 01:00;2;0\n"):
            with self.assertRaises(ValueError):decode_meteoswiss_hourly(text.encode(),station("CH","BAS"))

    def test_historical_geometry_is_not_inferred_from_current_catalog_height(self):
        batch=decode_geosphere_hourly(json.dumps(self.geo([22])).encode(),station("AT",history=False))
        with self.assertRaisesRegex(ValueError,"GEOMETRY_UNVERIFIED"):batch.series(T)
        self.assertEqual(batch.series(T,require_historical_geometry=False).iloc[0],-5)

    def test_wrong_provider_country_and_invalid_identity_are_rejected(self):
        with self.assertRaises(ValueError):station("FR")
        with self.assertRaises(ValueError):decode_geosphere_hourly(json.dumps(self.geo([22])).encode(),station("DE"))


class TimeOperatorTests(unittest.TestCase):
    def test_six_ten_minute_nodes_have_5_12_and_7_12_coefficients(self):
        source=temperature([0.,12.]);index=source.index[1:]
        result=model_reference_operator(source,index,"mean_six_10min_nominal_nodes")
        self.assertAlmostEqual(result.iloc[0],sum([2,4,6,8,10,12])/6)
        self.assertNotEqual(result.iloc[0],6.)
        self.assertNotEqual(result.iloc[0],12.)
        self.assertFalse(result.attrs["true_subhourly_path_or_sensor_filter_known"])

    def test_nominal_point_has_no_hour_shift(self):
        source=temperature([1.,9.,3.])
        pd.testing.assert_series_equal(model_reference_operator(source,source.index,"published_nominal_node"),source,check_names=False)

    def test_missing_previous_model_node_stays_missing(self):
        source=temperature([1.,9.]);result=model_reference_operator(source,source.index,"mean_six_10min_nominal_nodes")
        self.assertTrue(pd.isna(result.iloc[0]))

    def test_unknown_operator_and_undeclared_units_block(self):
        source=temperature([1.,9.])
        with self.assertRaisesRegex(ValueError,"UNKNOWN_TEMPORAL_OPERATOR"):model_reference_operator(source,source.index,"unknown")
        source.attrs["unit"]="K"
        with self.assertRaisesRegex(ValueError,"CELSIUS"):model_reference_operator(source,source.index,"published_nominal_node")


class ResidualTests(unittest.TestCase):
    def setUp(self):
        self.target=station();self.donors=[station(sid="2",latitude=48.1),station(sid="3",latitude=48.2),station(sid="4",latitude=48.3)]
        self.base=temperature([10.,10.,10.]);self.model={d.key:temperature([8.,8.,8.]) for d in self.donors}
        self.obs={d.key:temperature([10.,10.,10.]) for d in self.donors}
        self.qc={d.key:pd.Series(True,index=self.base.index) for d in self.donors}

    def run_candidate(self):return reconstruct_temperature(self.target,self.base,self.donors,self.obs,self.model,self.qc)

    def test_constant_spatial_residual_reproduced_without_target_observations(self):
        result,ledger=self.run_candidate()
        np.testing.assert_array_equal(result,[12.,12.,12.])
        self.assertTrue(ledger["candidate_admitted"].all())
        self.assertFalse(result.attrs["target_observations_used"])
        self.assertFalse(result.attrs["EPW_export_or_default_promotion_allowed"])

    def test_weights_sum_to_one_and_inverse_square_identity(self):
        self.obs[self.donors[0].key]=temperature([8.,8.,8.])
        result,ledger=self.run_candidate()
        weights=ledger.filter(like="weight__").iloc[0].to_numpy()
        expected=np.array([1.,1/4,1/9]);expected/=expected.sum()
        np.testing.assert_allclose(weights,expected,rtol=1e-12)
        self.assertAlmostEqual(result.iloc[0],10+2*(expected[1]+expected[2]))

    def test_QC_missing_donors_are_renormalized_then_explicitly_blocked(self):
        self.qc[self.donors[0].key].iloc[1:]=False;self.qc[self.donors[1].key].iloc[2]=False
        result,ledger=self.run_candidate()
        self.assertEqual(ledger["accepted_donor_count"].tolist(),[3,2,1])
        self.assertAlmostEqual(result.iloc[1],12)
        self.assertTrue(pd.isna(result.iloc[2]))
        self.assertFalse(ledger["candidate_admitted"].iloc[2])

    def test_native_QN_integer_is_not_treated_as_boolean_true(self):
        self.qc[self.donors[0].key]=pd.Series(1,index=self.base.index)
        with self.assertRaisesRegex(ValueError,"REQUIRES_BOOL"):self.run_candidate()

    def test_wrong_temporal_support_does_not_mix_in_residual(self):
        self.obs[self.donors[0].key].attrs["reference_operator"]="mean_six_10min_nominal_nodes"
        with self.assertRaisesRegex(ValueError,"MIXED_TIME_OPERATOR"):self.run_candidate()

    def test_unverified_history_or_duplicate_identity_blocks(self):
        original=self.target;self.target=replace(original,historical_geometry_verified=False)
        with self.assertRaisesRegex(ValueError,"GEOMETRY_UNVERIFIED"):self.run_candidate()
        self.target=original;self.donors[0]=replace(self.donors[0],identity_group="alias");self.donors[1]=replace(self.donors[1],identity_group="alias")
        with self.assertRaisesRegex(ValueError,"IDENTITY_ALIAS"):self.run_candidate()

    def test_target_alias_cannot_be_a_donor(self):
        self.donors[0]=replace(self.donors[0],station_id=self.target.station_id)
        with self.assertRaisesRegex(ValueError,"TARGET_ALIAS"):self.run_candidate()

    def test_invalid_target_baseline_not_rescued_by_an_arbitrary_correction(self):
        self.base.iloc[0]=100.
        result,ledger=self.run_candidate();self.assertTrue(pd.isna(result.iloc[0]))

    def test_metadata_only_selection_excludes_all_targets_groups_and_nearby_aliases(self):
        heldout=station(sid="5",latitude=48.4,group="other_target")
        pool=[*self.donors, self.target, heldout, station(sid="6",latitude=48.405),
            station(sid="7",latitude=48.55,group="other_target")]
        selected=select_donors(self.target,list(reversed(pool)),heldout=[self.target,heldout])
        self.assertEqual([d.key for d in selected],[d.key for d in self.donors])


class OriginalMetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.protocol,cls.status=preparation.prepare()

    def test_real_original_catalog_counts_and_fixed_6_targets_18_donors(self):
        self.assertEqual(self.status["eligible_nominal_catalog_stations"],{"AT":281,"DE":498,"CH":149})
        self.assertEqual([g["target_key"] for g in self.protocol["targets"]],["AT:3202","AT:6305","DE:02928","DE:01443","CH:BAS","CH:ALT"])
        self.assertEqual(self.status["donor_slots"],18)
        self.assertEqual(self.status["target_reference_hours_planned"],4032)

    def test_new_catalog_is_not_mislabeled_validation_or_strictly_blind(self):
        self.assertEqual(self.status["fully_admitted_target_cells"],0)
        self.assertFalse(self.protocol["exposure"]["new_2025_cohort_certified_strictly_blind"])
        self.assertEqual(self.status["target_measurement_values_read"],0)
        self.assertFalse(self.status["production_ready"])

    def test_geosphere_native_QC_codebook_agrees_with_policy(self):
        bodies,_,_=preparation.metadata_sources();meta=json.loads(bodies["AT_hourly_v2_metadata.json"])
        codebook={x["key"]:x["value"] for x in meta["code_lists"]["q21"]}
        self.assertIn("manuell",codebook[22]);self.assertIn("original",codebook[22]);self.assertIn("verändert",codebook[21])
        self.assertEqual(self.status["field_contracts"]["AT"]["QC_primary"],[22])

    def test_swiss_original_parameters_are_hourly_means_and_barometric_pressure(self):
        bodies,_,_=preparation.metadata_sources();records,_=preparation._csv(bodies["CH_parameters.csv"])
        by_code={r["parameter_shortname"]:r for r in records}
        for code in ["tre200h0","ure200h0","prestah0"]:self.assertIn("hourly mean",by_code[code]["parameter_description_en"])
        self.assertIn("barometric altitude",by_code["prestah0"]["parameter_description_en"])

    def test_two_failed_description_URLs_remain_recorded_after_official_recovery(self):
        self.assertEqual(len(self.status["original_failed_requests"]),2)
        self.assertEqual(self.status["raw_metadata_HTTP_attempts"],11)
        self.assertEqual(self.status["raw_metadata_bytes"],2482643)


if __name__ == "__main__":unittest.main()
