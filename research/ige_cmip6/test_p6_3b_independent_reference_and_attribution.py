"""P6.3B observation/source units, station daily QC and anomaly science tests."""
from __future__ import annotations
import unittest,json,math,tempfile
from pathlib import Path
from unittest.mock import patch

from p6_3b_independent_reference_sources import (
    STATION_SPECS,POWER_PARAMS,validate_metadata,geosphere_block,
    power_radiation_kwh,get_power_params,days
)
from p6_3b_anomaly_attribution_and_observed_validation import (
    ANOMALIES,unpaired_corr,estimate,block_bootstrap,decile_mechanism,
    case_audit,save_union
)
from p6_3a_solar_joint_coherence import METHODS,NEW

class IndependentSourcesAndForensicsTests(unittest.TestCase):
    def station_meta(self):
        params=[{"name":name,"unit":unit} for name,(unit,_,_) in STATION_SPECS.items()]
        params.extend({"name":name+"_flag","unit":"code"} for name in STATION_SPECS)
        return {"parameters":params,"stations":[{"id":30,"name":"Graz Universität"}]}

    def test_metadata_station_and_units_are_exact(self):
        spec,station=validate_metadata(self.station_meta())
        self.assertEqual(station["id"],30)
        self.assertIn("tl_mittel",spec)
        bad=self.station_meta()
        bad["parameters"][0]["unit"]="K"
        with self.assertRaisesRegex(ValueError,"unit changed"):
            validate_metadata(bad)

    def test_station_q21_rejects_unverified_daily_source(self):
        from datetime import date,timedelta
        dates=list(days(2005,2005))
        source={"timestamps":[d.isoformat()+"T00:00:00+00:00" for d in dates],
                "features":[{"properties":{"station":30,"parameters":{}}}]}
        for key,(unit,_,_) in STATION_SPECS.items():
            vec=[1.5]*len(dates)
            q=[20]*len(dates)
            q[0]=0
            source["features"][0]["properties"]["parameters"][key]={
                "unit":unit,"data":vec}
            source["features"][0]["properties"]["parameters"][key+"_flag"]={
                "data":q}
        rows,qa=geosphere_block(self.station_meta(),source,2005,2005)
        self.assertEqual(len(rows),365)
        self.assertIsNone(rows[0]["temperature_air_c"])
        self.assertEqual(rows[0]["temperature_air_c_raw"],1.5)
        self.assertEqual(rows[0]["temperature_air_c_q21"],0)
        self.assertEqual(rows[1]["temperature_air_c"],1.5)
        self.assertEqual(qa["tl_mittel"]["not_accepted"],1)

    def test_station_missing_field_does_not_silently_impute(self):
        s={"timestamps":[d.isoformat()+"T00:00:00+00:00" for d in days(2005,2005)],
           "features":[{"properties":{"station":30,"parameters":{}}}]}
        with self.assertRaisesRegex(ValueError,"lacks source parameter"):
            geosphere_block(self.station_meta(),s,2005,2005)

    def test_nasa_power_radiation_unit_conversions_strict(self):
        self.assertAlmostEqual(power_radiation_kwh(3.6,"MJ/m^2/day"),1.0)
        self.assertAlmostEqual(power_radiation_kwh(41.6666666667,"W/m^2"),1.0)
        self.assertEqual(power_radiation_kwh(1.,"kW-hr/m^2/day"),1.0)
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            power_radiation_kwh(1.,"J/cm²")

    def test_nasa_power_metadata_contract_fails_if_missing_field(self):
        payload={
            "properties":{"parameter":{k:{"20050101":1} for k in POWER_PARAMS}},
            "parameters":{k:{"units":("C" if k=="T2M" else
                 "%" if k=="RH2M" else "mm/day" if k=="PRECTOTCORR" else
                 "m/s" if k=="WS2M" else "kW-hr/m^2/day")}
                 for k in POWER_PARAMS}}
        table,units=get_power_params(payload)
        self.assertEqual(len(table),6)
        self.assertEqual(units["T2M"],"C")
        del payload["parameters"]["RH2M"]
        with self.assertRaisesRegex(ValueError,"units unavailable"):
            get_power_params(payload)

    def test_unpaired_reference_correlation_matches_known_synthetic_climate(self):
        obs=[]
        for year in range(2005,2015):
            for day in range(1,31):
                obs.append({"year":year,"month":6,"day":day,
                    "ghi_kwh_m2_day":.3+day*.05,
                    "temperature_air_c":float(day),
                    "is_complete":True})
        refs=unpaired_corr(obs,"temperature_air_c")
        result=block_bootstrap(refs,seed=6301)
        self.assertEqual(result["n"],300)
        self.assertAlmostEqual(result["pearson"],1.0)
        self.assertAlmostEqual(result["spearman"],1.0)
        self.assertAlmostEqual(result["ci_95_low"],1.0)
        self.assertAlmostEqual(result["ci_95_high"],1.0)

    def test_station_quality_gap_reduces_correlation_n(self):
        rows=[{"year":2005,"month":6,"temperature_air_c":None,
               "ghi_kwh_m2_day":2.} for _ in range(20)]
        pairs=unpaired_corr(rows,"temperature_air_c")
        self.assertEqual(len(pairs),0)
        self.assertIsNone(estimate(pairs)["pearson"])

    def test_model_anomaly_specs_match_accepted_p6_3a(self):
        self.assertEqual({x["model"] for x in ANOMALIES},{"CanESM5","IPSL-CM6A-LR"})
        self.assertEqual({x["window"] for x in ANOMALIES},{"ssp585-2080-2099"})
        self.assertEqual({x["relationship"] for x in ANOMALIES},
                         {"tas_rsds","longwave_rsds"})

    def test_m3_decile_shift_is_model_period_internal_not_observed_future(self):
        anomaly=ANOMALIES[0]
        model="CanESM5"
        def group(year):
            joint=[];solar=[];geometry=[]
            for y in range(year,year+20):
                for m in (6,7,8):
                    for day in range(1,31):
                        joint.append({"year":y,"month":m,"tas_c":5+day*.25})
                        solar.append({METHODS[0]:2+day*.01,NEW:1.2+day*.008})
                        geometry.append({"rso":5.,"ra":6.})
            return {"joint":joint,"solar":solar,"geometry":geometry}
        item={"name":model,"historical":group(1995),"future":group(2080)}
        rows=decile_mechanism(item,anomaly)
        self.assertEqual(len(rows),20)
        self.assertTrue(all(r["M3_minus_raw_GHI_kwh_m2_day"]<0 for r in rows))

    def test_anomaly_reproduction_must_match_previous_validated_evidence(self):
        anomaly=ANOMALIES[0]
        # A material distortion mismatch is a scientific failure, not a
        # reason to adopt the earlier archived result without recomputation.
        partial={"name":"CanESM5","change_drift":[{
            "model":"CanESM5","method":NEW,"season":"JJA",
            "relationship":"tas_rsds",
            "pearson_signal_distortion_vs_original":.9}]}
        with self.assertRaisesRegex(ValueError,"could not be reproduced"):
            case_audit(partial,anomaly,[],[])

    def test_heterogeneous_observation_schema_preserved(self):
        records=[{"reference_kind":"station","n":100,"station_qc":"yes"},
                 {"reference_kind":"gridded","n":100,"satellite_unit":"kWh"}]
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/"sources.csv"
            sha=save_union(path,records)
            source=path.read_text(encoding="utf8")
        self.assertEqual(len(sha),64)
        self.assertIn("station_qc",source)
        self.assertIn("satellite_unit",source)

if __name__=="__main__":unittest.main()
