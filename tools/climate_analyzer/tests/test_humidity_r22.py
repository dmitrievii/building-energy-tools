"""R2.2 regression gates: figure-specific humidity findings and safe design claims."""
from __future__ import annotations

import unittest

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.humidity_findings import humidity_figure_interpretation as explain
from epw_climate_analyzer.humidity_findings import W, RH, DP, WB, H, SV, T, RHO
from epw_climate_analyzer.p3_comfort import moisture_loads, condensation_margin


class HumidityR22Tests(unittest.TestCase):
    def setUp(self):
        idx = pd.date_range("2026-07-01", periods=4, freq="h")
        self.df = pd.DataFrame({
            T: [18., 22., 28., 30.],
            RH: [90., 85., 75., 65.],
            W: [8., 8., 10., 10.],
            DP: [14., 16., 17., 19.],
            WB: [16., 19., 24., 25.],
            H: [39., 42., 55., 61.],
            SV: [0.8]*4,
            RHO: [1.26]*4,
        }, index=idx)

    def test_rh_is_not_absolute_moisture(self):
        fig = go.Figure(go.Scatter(x=[1,2],y=[85.,70.]))
        note=explain(self.df,fig,"duration",column=RH)
        self.assertIn("humidity ratio",note)
        self.assertIn("9 g/kg",note)
        self.assertIn("high relative humidity can coincide",note)

    def test_psychrometric_reference_zones_are_not_comfort_hours(self):
        note=explain(self.df,go.Figure(),"psychrometric",
                     title="Psychrometric · i-d · Climate zone")
        self.assertIn("moisture content versus enthalpy",note)
        self.assertIn("smoothed",note)
        self.assertIn("candidate passive strategies",note)
        self.assertIn("overlap of zones",note)

    def test_plot_specific_profile_uses_actual_shown_values(self):
        fig=go.Figure()
        fig.add_scatter(x=["Jan","Feb"],y=[5.,17.],name="Mean")
        note=explain(self.df,fig,"profile",column=W)
        self.assertIn("Jan (5.0 g/kg",note)
        self.assertIn("Feb (17.0 g/kg",note)

    def test_heatmap_uses_selected_reduced_cells(self):
        fig=go.Figure(go.Heatmap(x=["Jan","Feb"],y=[0,12],
             z=[[21.,22.],[14.,25.]]))
        note=explain(self.df,fig,"heatmap",column=DP)
        self.assertIn("14.0 °C",note)
        self.assertIn("25.0 °C",note)
        self.assertIn("strongest and weakest periods",note)

    def test_illustrative_thresholds_do_not_require_full_air_conditioning(self):
        note=explain(self.df,go.Figure(),"threshold",column=W,args=(9.,">"))
        self.assertIn("2 h",note)
        self.assertIn("frequency of the selected atmospheric moisture condition",note)
        self.assertIn("elevated outdoor water-vapour content",note)

    def test_surface_condensation_uses_dew_point_and_boundary_equality(self):
        self.df.loc[self.df.index[0],DP]=15.
        note=explain(self.df,None,"condensation",surface_c=15.)
        self.assertIn("4 h",note)
        self.assertIn("reference surface temperature of 15 °C",note)
        self.assertIn("potential surface-moisture exposure",note)
        margin=condensation_margin(self.df,15.)
        self.assertEqual(int(margin.le(0).sum()),4)

    def test_moisture_flow_is_water_mass_not_latent_energy(self):
        # 1000 m³/h / 0.8 m³/kg dry air = 1250 kg dry air/h;
        # one g/kg deviation gives 1.25 kg water each hour.
        calculated=moisture_loads(self.df,airflow=1000.,target=9.)
        self.assertAlmostEqual(float(calculated["Humidification"].sum()),2.5)
        self.assertAlmostEqual(float(calculated["Dehumidification"].sum()),2.5)
        note=explain(self.df,None,"moisture",airflow_m3_h=1000.,target_g_kg=9.)
        self.assertIn("2.5 kg removal",note)
        self.assertIn("2.5 kg addition",note)
        self.assertIn("water mass needed",note)

    def test_persistence_distinguishes_hours_from_events(self):
        note=explain(self.df,None,"persistence",column=W,args=(10.,True,"duration"))
        self.assertIn("2 observed hours",note)
        self.assertIn("Continuous runs",note)

    def test_scatter_states_association_not_causality(self):
        note=explain(self.df,go.Figure(),"scatter",args=(T,W))
        self.assertIn("sample Pearson r",note)
        self.assertIn("vary together",note)


if __name__=="__main__":
    unittest.main()
