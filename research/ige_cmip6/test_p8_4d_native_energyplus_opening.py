"""IGE P8.4D actual EnergyPlus wind/stack opening physical and provenance contracts."""
import unittest
import p8_4d_native_energyplus_opening as a
from test_p8_4d_epw_wind_qualification import fixture


class OpeningContracts(unittest.TestCase):
    def test_uses_real_official_EnergyPlus_source_model(self):
        upstream=("! 1ZoneUncontrolled.idf\nVersion,26.2;\n"
                  "SimulationControl,No,No,No,Yes,No;\n"
                  "Site:Location,Denver,39,-105,-7,1800;\n"
                  "RunPeriod,Annual,1,1,,12,31;\nZone,ZONE ONE;\n")
        result=a.build_native_opening_model(upstream)
        self.assertEqual(result.count("ZoneVentilation:WindandStackOpenArea,"),1)
        self.assertIn("Autocalculate,\n  180.0,",result)
        self.assertIn(a.VENT_VAR,result)

    def test_registered_opening_area_and_temperature_guards(self):
        d=a.MODEL_PARAMETERS
        self.assertEqual(d["opening_area_m2"],.25)
        self.assertEqual(d["height_difference_m"],.5)
        self.assertEqual(d["opening_outward_normal_from_north_deg"],180.)
        self.assertEqual(d["min_indoor_C"],21.)
        self.assertEqual(d["max_outdoor_C"],28.)
        self.assertEqual(d["max_outdoor_wind_speed_mps"],15.)

    def test_wind_speed_only_changes_EPW_speed_column(self):
        source=fixture()
        transformed=a.wind_and_azimuth_fixture(source,1.5,0.)
        self.assertEqual(len(transformed),8760)
        self.assertTrue(all(x[j]==y[j] for x,y in zip(source,transformed)
                            for j in range(35) if j!=21))
        self.assertAlmostEqual(float(transformed[1][21]),3.)

    def test_wind_rotation_only_changes_two_allowed_EPW_columns(self):
        original=fixture()
        output=a.wind_and_azimuth_fixture(original,1.,90.)
        self.assertEqual(len(output),8760)
        self.assertTrue(all(x[j]==y[j] for x,y in zip(original,output)
                            for j in range(35) if j not in (20,21)))
        self.assertAlmostEqual(
            float(output[1][20]),(float(original[1][20])+90)%360,places=8)

    def test_epw_missing_directions_never_invented_by_rotation(self):
        x=fixture()
        self.assertEqual(float(x[0][20]),999.)
        output=a.wind_and_azimuth_fixture(x,1.,90.)
        self.assertEqual(output[0][20],x[0][20])

    def test_no_climate_changing_wind_multiplier_accepted(self):
        for speed,rotate in ((0,0),(float("nan"),0),(1,float("nan"))):
            with self.assertRaisesRegex(ValueError,"INVALID"):
                a.wind_and_azimuth_fixture(fixture()[:2],speed,rotate)

    def test_four_independent_wind_speed_and_azimuth_runs_predeclared(self):
        self.assertEqual(a.EPW_SETTINGS,((.5,0.),(1.,0.),(1.5,0.),(1.,90.)))
        self.assertEqual(a.VENT_VAR,"Zone Ventilation Standard Density Volume Flow Rate")


if __name__=="__main__":
    unittest.main()
