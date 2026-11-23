"""R2.4 scientific regression gates: irradiation, interpretation and design context."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.solar_findings import (
    GHI,DNI,DHI,FRACTION,T,POA,solar_figure_interpretation,
    solar_temperature_interpretation,facade_figure_interpretation,
    facade_temperature_table,facade_temperature_figure,
    facade_temperature_interpretation,
)
from epw_climate_analyzer.solar import surface_irradiance_series
from epw_climate_analyzer.facade_orientation import ORIENTATIONS


class SolarR24Tests(unittest.TestCase):
    def sample(self):
        index=pd.date_range("2026-07-01",periods=6,freq="h")
        # The test uses mathematically consistent horizontal GHI = DHI + DNI*cos(z).
        zenith=np.array([75.,55.,35.,50.,60.,80.],dtype=float)
        dhi=np.array([20.,40.,50.,40.,30.,10.],dtype=float)
        dni=np.array([100.,350.,600.,350.,200.,70.],dtype=float)
        ghi=dhi+dni*np.cos(np.deg2rad(zenith))
        df=pd.DataFrame({
            GHI:ghi,DHI:dhi,DNI:dni,
            "solar_apparent_zenith_deg":zenith,
            "solar_azimuth_deg":[80.,100.,145.,195.,240.,285.],
            T:[15.,20.,26.,29.,30.,np.nan],
            FRACTION:100*dhi/ghi,
        },index=index)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_fraction_distinguishes_weighted_from_mean_interval_ratio(self):
        df=self.sample()
        note=solar_figure_interpretation(df,go.Figure(),"duration",column=FRACTION)
        self.assertIn("ratio of coincident positive-GHI sums",note)
        self.assertIn("daylight ratio is calculated over positive-GHI intervals",note)

    def test_monthly_profile_uses_actually_plotted_centre(self):
        df=self.sample()
        fig=go.Figure()
        fig.add_scatter(x=["Jan","Feb"],y=[50.,170.],name="Mean")
        text=solar_figure_interpretation(df,fig,"profile",column=GHI)
        self.assertIn("Jan (50.0 Wh/m²)",text)
        self.assertIn("Feb (170.0 Wh/m²)",text)

    def test_source_planes_are_not_added_as_one_total(self):
        df=self.sample()
        note=solar_figure_interpretation(df,None,"time_series",column=DNI)
        self.assertIn("solar zenith angle",note)
        self.assertIn("interval irradiation",note)

    def test_solar_threshold_uses_watts_not_watt_hours(self):
        df=self.sample().iloc[:2].copy()
        df.index=pd.date_range("2026-07-01",periods=2,freq="30min")
        df.attrs["canonical_native_interval_minutes"]=30.
        df[T]=27.
        df[GHI]=[100.,60.]
        # Two 30-minute samples correspond to 200 and 120 W/m².
        note=solar_temperature_interpretation(df,threshold_w_m2=150.,hot_temperature_c=26.)
        self.assertIn("0.5 observed hours",note)
        self.assertIn("150 W/m²",note)
        self.assertIn("warm-weather solar exposure",note)

    def test_poa_transposition_closure_same_kernel(self):
        df=self.sample()
        table=facade_temperature_table(df,cold_c=18.,hot_c=26.)
        self.assertEqual(len(table),8)
        for name,abbr,azimuth in ORIENTATIONS:
            poa=surface_irradiance_series(df,90.,azimuth)
            row=table.loc[table.direction==abbr].iloc[0]
            self.assertAlmostEqual(row.total_kwh_m2,float(poa.sum()/1000.),places=8)
            self.assertAlmostEqual(
                row.cold_kwh_m2+row.intermediate_kwh_m2+row.hot_kwh_m2+row.unknown_temperature_kwh_m2,
                row.total_kwh_m2,places=8)
            self.assertEqual(int(row.valid_irradiation_intervals),len(df))
            self.assertEqual(int(row.coincident_temperature_intervals),len(df)-1)

    def test_figure_and_interpretation_are_explicitly_climate_screen_only(self):
        table=facade_temperature_table(self.sample())
        fig=facade_temperature_figure(table)
        note=facade_temperature_interpretation(table)
        self.assertEqual(len(fig.data),4)
        self.assertIn("Highest coincident irradiation",note)
        self.assertIn("candidate façades",note)
        self.assertIn("unknown",str(table.columns).lower())

    def test_selected_plane_not_silently_relabelled_south(self):
        df=self.sample()
        df[POA]=surface_irradiance_series(df,60.,90.)
        note=solar_figure_interpretation(df,None,"time_series",column=POA,
               plane="tilt 60°, azimuth 90°")
        # Figure interpretation must describe selected-plane assumptions.
        self.assertIn("tilt 60°, azimuth 90°",note)
        self.assertNotIn("reference vertical south-facing plane",note)

    def test_facade_interpretation_uses_total_customdata_not_component_only(self):
        fig=go.Figure()
        fig.add_bar(x=["N","S"],y=[10.,20.],
                    customdata=[["North",100.],["South",300.]])
        note=facade_figure_interpretation(fig,tilt_deg=90.)
        self.assertIn("South (300.0 kWh/m²)",note)
        self.assertIn("North (100.0 kWh/m²)",note)

    def test_sky_polar_radius_is_not_patch_energy(self):
        note=solar_figure_interpretation(self.sample(),None,"sky_patches")
        self.assertIn("polar bar radius",note.lower())
        self.assertIn("common valid daylight",note)

    def test_report_catalog_has_figure_and_strategy_preset(self):
        from epw_climate_analyzer import p6_report_structure as report
        c={e[0]:e for e in report.CATALOG}
        self.assertIn("solar_exposure",c)
        self.assertIn("solar_exposure",report.PRESETS["Architectural climate study"])
        self.assertIn("solar_exposure",report.PRESETS["Passive design"])
        fig,note=report.standard_figure(c["solar_exposure"],self.sample(),{})
        self.assertEqual(fig.data[0].type,"bar")
        self.assertIn("outdoor T >",note)

    def test_monthly_only_source_is_not_passed_as_hourly_facade_energy(self):
        df=self.sample().iloc[:2].copy()
        df.index=pd.date_range("2026-01-01",periods=2,freq="MS")
        df.attrs["canonical_native_resolution"]="monthly"
        with self.assertRaisesRegex(ValueError,"subdaily"):
            facade_temperature_table(df)


if __name__=="__main__":
    unittest.main()
