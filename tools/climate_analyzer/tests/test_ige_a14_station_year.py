"""A1.4 independent algebra, temporal, projection and full export checks."""
from dataclasses import replace
import csv
import io
from pathlib import Path
import sys
import unittest

import numpy as np
import pandas as pd

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/"research/ige_cmip6"))
from a14_prepare import build_registration,FIRST,ANCHOR,LAST
from a14_run import annual_donor_subset,csv_bytes
from test_ige_engine import fixture
from epw_climate_analyzer.engine.contracts import HistoricalRequest
from epw_climate_analyzer.engine.historical import assemble_historical
from epw_climate_analyzer.engine.station_year import (StationYearRequest,reconstruct_nodes,project_humidity,
    assemble_station_year,serialize_station_epw,validate_station_state,T,TD,RH,P,Q,PS)
from epw_climate_analyzer.engine.thermodynamics import (EPSILON,saturation_water_pa,saturation_nasa_phase_pa,
    e_from_q,pressure_at_2m,q_saturation_at_2m)
from epw_climate_analyzer.station_reconstruction import model_reference_operator


class MeanInverseTests(unittest.TestCase):
    def series(self,n=200):
        clock=pd.date_range("2025-01-01",periods=n+1,freq="h",tz="UTC")
        b=pd.Series(8+np.sin(np.arange(n+1)/12),index=clock);b.attrs["unit"]="°C"
        return b,clock[1:]

    def test_roundtrip_against_explicit_six_ten_minute_nodes(self):
        b,clock=self.series()
        actual=b.to_numpy()+np.r_[0,np.cos(np.arange(len(clock))/7)]
        means=np.mean(np.column_stack([actual[:-1]*(1-j/6)+actual[1:]*(j/6) for j in range(1,7)]),axis=1)
        recovered,_=reconstruct_nodes(b,pd.Series(means,index=clock))
        np.testing.assert_allclose(recovered,actual,atol=2e-14,rtol=0)

    def test_missing_raw_R1_is_logged_and_mean_fallback_has_inverse_memory(self):
        b,clock=self.series(5)
        raw=model_reference_operator(b,clock,"mean_six_10min_nominal_nodes")+2
        raw.iloc[2]=np.nan
        nodes,ledger=reconstruct_nodes(b,raw)
        self.assertTrue(np.isnan(ledger.raw_R1_mean_C.iloc[2]))
        self.assertEqual(ledger.selection.iloc[2],"EXPLICIT_B0_MEAN_FALLBACK")
        self.assertNotEqual(nodes.iloc[3],b.iloc[3])
        self.assertAlmostEqual((5*nodes.iloc[2]+7*nodes.iloc[3])/12,ledger.B0_mean_C.iloc[2])

    def test_inverse_high_frequency_gain_is_six_not_silent_smoothing(self):
        b,clock=self.series(200)
        base=model_reference_operator(b,clock,"mean_six_10min_nominal_nodes")
        nodes,_=reconstruct_nodes(b,base+(-1.)**np.arange(200))
        np.testing.assert_allclose(np.abs((nodes-b).to_numpy()[-10:]),6,atol=1e-12,rtol=0)

    def test_anchor_error_decay_has_registered_analytic_bound(self):
        # Two inverses of the SAME mean equations differ by (-5/7)^h.
        errors=[20.]
        for _ in range(73):errors.append(-5*errors[-1]/7)
        self.assertAlmostEqual(abs(errors[-1]),20*(5/7)**73,delta=1e-22)
        self.assertLess(abs(errors[-1]),5e-10)

    def test_gap_or_missing_boundary_fails(self):
        b,clock=self.series()
        raw=pd.Series(10.,index=clock)
        with self.assertRaisesRegex(ValueError,"BOUNDARY"):reconstruct_nodes(b.iloc[1:],raw)
        with self.assertRaisesRegex(ValueError,"CONTIGUOUS"):reconstruct_nodes(b,raw.drop(clock[30]))


class HumidityProjectionTests(unittest.TestCase):
    def test_warming_preserves_inferred_specific_humidity(self):
        state,ledger=project_humidity([10,20],[40,60],[95000,100000],[15,25])
        np.testing.assert_array_equal(state[Q],ledger["inferred_background_q_kg_kg"])
        self.assertFalse(ledger["q_projection_active"].any())
        self.assertTrue((state[RH]<[40,60]).all())

    def test_cooling_projection_is_saturated_minimum_distance_feasible_q(self):
        state,ledger=project_humidity([20],[90],[100000],[0])
        q=state[Q][0];q0=ledger["inferred_background_q_kg_kg"][0]
        self.assertTrue(ledger["q_projection_active"][0])
        self.assertAlmostEqual(state[RH][0],100,places=11)
        # Direct objective comparison for other feasible candidates.
        candidates=np.linspace(0,q,101)
        self.assertTrue(np.all((candidates-q0)**2 >= (q-q0)**2-1e-18))
        self.assertLess(e_from_q(q+1e-7,pressure_at_2m([0],[q+1e-7],[100000]))[0],100000)
        self.assertGreater(e_from_q(q+1e-7,pressure_at_2m([0],[q+1e-7],[100000]))[0],saturation_water_pa([0])[0])

    def test_closure_uses_moist_specific_q_not_dry_air_mixing_ratio(self):
        s,_=project_humidity([25],[80],[98000],[30])
        q,p=s[Q],s[P]
        e=q*p/(EPSILON+(1-EPSILON)*q)
        np.testing.assert_allclose(s[RH],100*e/saturation_water_pa(s[T]),atol=1e-12)
        self.assertGreater(float(np.abs(q-q/(1-q)).max()),1e-4)

    def test_ice_supersaturation_does_not_clip_water_states(self):
        s,_=project_humidity([-15],[98],[95000],[-15])
        self.assertGreater((100*e_from_q(s[Q],s[P])/saturation_nasa_phase_pa(s[T])).item(),100)
        self.assertLessEqual(s[RH].item(),100)

    def test_no_zero_RH_floor_or_nonfinite_repair(self):
        for rh in (0,np.nan,-1,101):
            with self.assertRaises(ValueError):project_humidity([10],[rh],[100000],[10])

    def test_pressure_is_explicitly_conditional_and_surface_input_unchanged(self):
        ps=np.array([95000.,100000.]);original=ps.copy()
        s,_=project_humidity([0,10],[60,70],ps,[1,11])
        np.testing.assert_array_equal(ps,original)
        np.testing.assert_array_equal(s[PS],ps)
        self.assertTrue((s[P]<ps).all())


class FullResearchYearTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        req=HistoricalRequest(47.541064,7.58355,2025,60,"A14 BAS")
        raw,receipts=fixture(req);cls.base=assemble_historical(req,raw,receipts)
        t=pd.Series(np.sin(np.arange(8760)/24)-2,index=req.utc_ends)
        cls.result,cls.ledger=assemble_station_year(cls.base,t,station_key="CH:BAS",latitude=req.latitude,
            longitude=req.longitude,nominal_elevation_m=316.,name="A14 BAS",r1_source={"test":"synthetic"},temperature_diagnostics={})

    def test_full_8760_export_and_actual_parser(self):
        from epw_climate_analyzer.epw_parser import parse_epw
        payload,report=serialize_station_epw(self.result)
        self.assertEqual(report["epw_format_readback"],"PASS")
        self.assertEqual(report["serialized_water_closure_quantization_intervals"],"PASS")
        self.assertEqual(len(parse_epw(io.BytesIO(payload)).data),8760)
        rows=list(csv.reader(io.StringIO(payload.decode())))
        self.assertIn("STATION T RESEARCH",rows[0][1])
        self.assertEqual(rows[8][:5],["2025","1","1","1","60"])
        self.assertEqual(rows[-1][:5],["2025","12","31","24","60"])
        self.assertIn("unqualified",rows[5][1])

    def test_canonical_preserves_actual_calendar_phase_and_requires_adapter(self):
        canonical=self.result.to_canonical()
        self.assertEqual(canonical.temporal.calendar_mode,"historical")
        self.assertEqual(canonical.temporal.source_years,(2025,))
        self.assertIn("MURPHY_KOOP",canonical.data.attrs["ige_RH_phase"])
        self.assertTrue(canonical.data.attrs["ige_UI_humidity_phase_adapter_required"])
        self.assertFalse(canonical.data.attrs["ige_existing_U1_display_adapter_supports_this_contract"])

    def test_mutable_frame_tampering_is_rechecked_before_export(self):
        bad=replace(self.result)
        bad.data.loc[bad.data.index[3],RH]+=1
        with self.assertRaisesRegex(ValueError,"CLOSURE_FAILED"):serialize_station_epw(bad)

    def test_other_weather_is_not_changed_by_local_T_policy(self):
        for key in self.base.data:
            if key not in (T,TD,RH,P):np.testing.assert_array_equal(self.base.data[key],self.result.data[key])
        self.assertFalse(self.result.quality.production_ready)
        self.assertIn("NOT_INDEPENDENTLY",self.result.quality.independent_accuracy)
        self.assertEqual(len(self.ledger),8760)

    def test_saved_hourly_CSV_retains_conditional_state_closure(self):
        raw=csv_bytes(self.result.data)
        frame=pd.read_csv(io.BytesIO(raw),index_col=0)
        frame.index=self.result.data.index
        restored=replace(self.result,data=frame)
        validate_station_state(restored)

    def test_new_request_does_not_enable_unregistered_points_or_years(self):
        with self.assertRaises(ValueError):StationYearRequest(47,8,2025,60,station_key="CH:NEW")
        with self.assertRaises(ValueError):StationYearRequest(47,8,2024,60,station_key="CH:BAS")
        with self.assertRaises(ValueError):HistoricalRequest(47,8,2025,60,mode="station_temperature_year")


class SourceAdmissionTests(unittest.TestCase):
    def test_geometry_rechecked_for_entire_spinup_and_export_support(self):
        p=build_registration()
        self.assertEqual(len(p["full_support_admission"]),7)
        for row in p["full_support_admission"].values():
            bounds=row["geometry"]["parser_geometry_check_bounds_UTC"]
            self.assertEqual(pd.Timestamp(bounds[0]),ANCHOR)
            self.assertEqual(pd.Timestamp(bounds[1]),LAST)
        self.assertEqual(len(p["new_source_plan"]),11)
        self.assertEqual(p["source_budget"]["new_station_observation_requests"],0)

    def test_annual_reader_selects_only_donor_temperature_after_clock_filter(self):
        raw=b"station_abbr;reference_timestamp;tre200h0;ure200h0\nMOE;01.01.2020 00:00;not-read;secret\nMOE;29.12.2024 00:00;2.1;not-read\nMOE;01.01.2025 00:00;3.1;not-read\n"
        subset=annual_donor_subset(raw,"MOE")
        self.assertEqual(len(subset.splitlines()),3)
        self.assertNotIn(b"ure200h0",subset)
        self.assertNotIn(b"not-read",subset)
        with self.assertRaisesRegex(ValueError,"ONLY_FROZEN_DONOR"):annual_donor_subset(raw,"BAS")

    def test_duplicate_or_cross_station_donor_data_fails(self):
        for rows in ("MOE;01.01.2025 00:00;1\nMOE;01.01.2025 00:00;2\n","BAS;01.01.2025 00:00;1\n"):
            with self.assertRaises(ValueError):annual_donor_subset(("station_abbr;reference_timestamp;tre200h0\n"+rows).encode(),"MOE")


if __name__=="__main__":unittest.main()
