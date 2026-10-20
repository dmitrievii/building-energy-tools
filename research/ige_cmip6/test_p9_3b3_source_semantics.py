import dataclasses
import unittest
import numpy as np
from p9_3b3_source_semantics import SourceSemantics,DailyTarget,parse_das
from p9_3b3_pressure_reference import PressureReference,station_pressure
from p9_3b3_joint_solver import affine_temperature


def target(phase="WATER",operator="DERIVED_TAS_MIDRANGE",**changes):
    args=dict(date="2014-01-02",Tmin_K=280.,Tmax_K=300.,tas_K=290.,
              q_mean_kgkg=.006,RH_mean_pct=60.,semantics=SourceSemantics(
                  operator,phase,time_support="SYNTHETIC_UTC_NODE_DAY",verified=phase!="UNKNOWN"))
    args.update(changes)
    return DailyTarget(**args)


class Semantics(unittest.TestCase):
    def test_midrange_does_not_constrain_temporal_mean(self):
        a=affine_temperature([0,0,0,1],target())
        b=affine_temperature([0,1,1,1],target())
        self.assertEqual((min(a)+max(a))/2,290)
        self.assertEqual((min(b)+max(b))/2,290)
        self.assertNotEqual(np.mean(a),np.mean(b))

    def test_wrong_derived_midrange_rejected(self):
        with self.assertRaisesRegex(ValueError,"MIDRANGE"):
            target(tas_K=291)

    def test_time_mean_is_distinct_operator(self):
        self.assertEqual(target(operator="TIME_MEAN_TAS",tas_K=291).tas_K,291)

    def test_unknown_phase_not_certified(self):
        with self.assertRaises(ValueError):SourceSemantics("DERIVED_TAS_MIDRANGE","UNKNOWN",verified=True)

    def test_no_leap_fabrication(self):
        with self.assertRaisesRegex(ValueError,"LEAP"):
            target(date="2012-02-29")

    def test_nonfinite_and_units_fail(self):
        for change in (dict(tas_K=float("nan")),dict(Tmin_K=5.),dict(q_mean_kgkg=6.)):
            with self.assertRaises(ValueError):target(**change)

    def test_target_roundtrip_frozen(self):
        a=target();self.assertEqual(a,DailyTarget.from_dict(a.to_dict()))
        with self.assertRaises(dataclasses.FrozenInstanceError):a.tas_K=2

    def test_das_native_mean_phase_and_absent_bounds(self):
        text='Attributes {\n time { String calendar "365_day"; }\n hurs { String cell_methods "area: time: mean"; String comment "ice"; }\n NC_GLOBAL { String version "2.0"; }\n}'
        d=parse_das(text)
        self.assertFalse(d["time_bounds_declared"])
        self.assertEqual(d["blocks"]["hurs"]["cell_methods"],"area: time: mean")

    def test_dwd_native_fields_no_msl_fallback(self):
        for product,row in (("DWD_HOURLY_P0",{"P":1020}),
                            ("DWD_URBAN_10MIN",{"PP_ST_10":1020})):
            self.assertIsNone(station_pressure(row,product)[0])
        self.assertEqual(station_pressure({"P0":980,"P":1020,"QN_8":3},"DWD_HOURLY_P0"),
                         (98000,"DWD_QN3_AUTOMATIC"))
        self.assertEqual(station_pressure({"P0_ST_10":990,"QN":""},"DWD_URBAN_10MIN"),
                         (99000,"NATIVE_QC_FIELD_EMPTY"))
        self.assertEqual(station_pressure({"PP_TER":950},"DWD_SUBDAILY_PP")[0],95000)

    def test_pressure_is_immutable_and_hpa_rejected(self):
        p=PressureReference((98000.,)*24,"ERA5","GRID")
        with self.assertRaises(dataclasses.FrozenInstanceError):p.values_Pa=(1,)
        with self.assertRaises(ValueError):PressureReference((980.,),"ERA5","GRID")
        self.assertFalse(p.metadata()["pressure_model_qualified"])
        self.assertEqual(p.stress(-500).values_Pa[0],97500)
        self.assertIsNone(p.metadata()["uncertainty_Pa"])

    def test_no_fake_uncertainty_or_height(self):
        with self.assertRaises(ValueError):PressureReference((98000.,),"ERA5","GRID",uncertainty_calibrated=True)
        with self.assertRaises(ValueError):PressureReference((98000.,),"ERA5","SITE",mode="SITE_HYDROSTATIC_PROVISIONAL")
        with self.assertRaisesRegex(ValueError,"NOT_RECOVERED"):
            PressureReference((98000.,),"invented","GCM",mode="NATIVE_GCM_HIGH_FREQUENCY")


if __name__=="__main__":unittest.main()
