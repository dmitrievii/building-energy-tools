"""R2.3 — wind climate-to-design, denominator and directional-screen gates."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.wind_findings import (
    wind_opportunity,wind_opportunity_figure,wind_design_interpretation,
    wind_figure_interpretation,opposite_sector,
)
from epw_climate_analyzer.directional_climate import (
    directional_table,directional_figure,directional_interpretation,
)


class WindR23Tests(unittest.TestCase):
    def sample(self):
        idx=pd.date_range("2026-01-01",periods=8,freq="h")
        df=pd.DataFrame({
            "wind_speed_m_s":[0.,0.5,2.,3.,3.,2.,4.,1.],
            "wind_direction_deg":[90.,90.,22.5,22.5,202.5,360.,np.nan,180.],
            "dry_bulb_temperature_c":[25.,25.,25.,28.,27.,25.,26.,26.],
            "humidity_ratio_g_kg":[20.,20.,20.,20.,20.,20.,20.,20.],
            "liquid_precipitation_depth_mm":[0.,0.,0.,1.,0.,0.,0.,0.],
        },index=idx)
        return df

    def test_threshold_calm_and_unknown_direction_do_not_disappear(self):
        df=self.sample()
        summary,detail=wind_opportunity(df,min_speed_m_s=0.5)
        row=summary.iloc[0]
        self.assertAlmostEqual(row["valid_source_hours"],8.)
        self.assertAlmostEqual(row["low_wind_hours"],2.)
        self.assertAlmostEqual(row["direction_missing_hours"],1.)
        self.assertAlmostEqual(row["directional_wind_hours"],5.)
        self.assertAlmostEqual(row["selected_directional_hours"],5.)
        self.assertAlmostEqual(detail.selected_hours.sum(),5.)
        self.assertAlmostEqual(detail.share_of_valid_source_hours_pct.sum(),62.5)
        self.assertAlmostEqual(row["low_wind_pct_of_valid"],25.)

    def test_meteorological_from_and_opposite_sector(self):
        self.assertEqual(opposite_sector("NNE"),"SSW")
        df=self.sample()
        _,detail=wind_opportunity(df,min_speed_m_s=.5)
        self.assertEqual(float(detail.loc[detail.sector=="N","selected_hours"].sum()),1.)
        self.assertEqual(float(detail.loc[detail.sector=="NNE","selected_hours"].sum()),2.)
        self.assertEqual(float(detail.loc[detail.sector=="SSW","selected_hours"].sum()),1.)
        self.assertEqual(float(detail.loc[detail.sector=="S","selected_hours"].sum()),1.)

    def test_rain_and_temperature_screens_only_when_enabled(self):
        df=self.sample()
        base,_=wind_opportunity(df,min_speed_m_s=.5)
        dry,_=wind_opportunity(df,min_speed_m_s=.5,rain_max_mm_h=0.)
        conditioned,_=wind_opportunity(df,min_speed_m_s=.5,temperature_range_c=(24.,26.))
        self.assertEqual(float(base.selected_directional_hours.sum()),5.)
        self.assertEqual(float(dry.selected_directional_hours.sum()),4.)
        self.assertEqual(float(conditioned.selected_directional_hours.sum()),3.)

    def test_explicit_humidity_cap_does_not_imply_no_natural_ventilation(self):
        df=self.sample()
        filtered,_=wind_opportunity(df,min_speed_m_s=.5,max_humidity_ratio_g_kg=9.)
        self.assertEqual(float(filtered.selected_directional_hours.sum()),0.)
        wording=wind_design_interpretation(df,min_speed_m_s=.5,max_humidity_ratio_g_kg=9.)
        self.assertIn("adjust the climatic screening criteria",wording)
        self.assertIn("no qualifying windward sector",wording)

    def test_cadence_sensitive_rain_intensity(self):
        df=self.sample().iloc[:4].copy()
        df.index=pd.date_range("2026-01-01",periods=4,freq="30min")
        df.attrs["canonical_native_interval_minutes"]=30
        df.loc[df.index[2],"liquid_precipitation_depth_mm"]=.1  # 0.2 mm/h
        _,screen=wind_opportunity(df,min_speed_m_s=.5,rain_max_mm_h=.15)
        self.assertEqual(float(screen.selected_hours.sum()),0.) # last sample rain 1 mm/30min

    def test_monthly_dominant_reversal_and_heatmap_share(self):
        df=self.sample()
        summer=df.iloc[[2,3,4,5]].copy()
        summer.index=pd.date_range("2026-07-01",periods=4,freq="h")
        merged=pd.concat([df,summer])
        summary,sectors=wind_opportunity(merged,min_speed_m_s=.5)
        self.assertEqual(summary.month.tolist(),[1,7])
        f=wind_opportunity_figure(summary,sectors)
        self.assertEqual(len(f.data),1)
        self.assertEqual(f.data[0].type,"heatmap")
        self.assertEqual(np.asarray(f.data[0].z).shape,(2,17))

    def test_gust_and_direction_avoid_linear_angle_interpretation(self):
        df=self.sample()
        df.loc[df.index[2],"wind_direction_deg"]=359.
        df.loc[df.index[3],"wind_direction_deg"]=1.
        note=wind_figure_interpretation(df,go.Figure(),"profile",
               column="wind_direction_deg")
        self.assertIn("circular",note)
        self.assertIn("359° and 1°",note)
        self.assertIn("meteorological FROM",note)
        df["wind_gust_speed_m_s"]=[0,0.6,4,4,6,5,6,4]
        df["wind_gust_direction_deg"]=df["wind_direction_deg"]
        gust=wind_figure_interpretation(df,go.Figure(),"duration",column="wind_gust_speed_m_s")
        self.assertIn("Gust peaks",gust)

    def test_true_eligible_hours_do_not_equal_wind_observations(self):
        df=self.sample()
        mask=pd.Series([False,False,True,False,False,False,False,False],index=df.index)
        observations=directional_table(df,radial="Hours",
              colour="Natural ventilation suitability",nv_mask=mask)
        eligible=directional_table(df,radial="Eligible hours",
              colour="Natural ventilation suitability",nv_mask=mask)
        self.assertEqual(float(observations.radius.sum()),6.)
        self.assertEqual(float(eligible.radius.sum()),1.)
        self.assertIn("1.0 wind-direction observation hours",directional_interpretation(
              eligible,"Eligible hours","Natural ventilation suitability"))
        self.assertEqual(directional_figure(
              eligible,"Eligible hours","Natural ventilation suitability","NV").data[0].type,"barpolar")

    def test_no_eligible_hours_are_never_plotted_as_nonzero(self):
        df=self.sample()
        mask=pd.Series(False,index=df.index)
        table=directional_table(df,radial="Eligible hours",
                                colour="Natural ventilation suitability",nv_mask=mask)
        self.assertAlmostEqual(float(table.radius.sum()),0.)
        note=directional_interpretation(table,"Eligible hours","Natural ventilation suitability")
        self.assertIn("zero eligible wind-direction hours",note)
        self.assertIn("Seasonal wind availability",note)

    def test_monthly_aggregates_do_not_generate_invented_hour_counts(self):
        frame=self.sample().iloc[:2].copy()
        frame.index=pd.date_range("2026-01-01",periods=2,freq="MS")
        frame.attrs["canonical_native_resolution"]="monthly"
        with self.assertRaisesRegex(ValueError,"subdaily observations"):
            wind_opportunity(frame)
        note=wind_figure_interpretation(frame,go.Figure(),"profile",
                                         column="wind_speed_m_s")
        self.assertIn("Hourly calm frequencies",note)
        self.assertIn("hourly observations",note)

    def test_report_has_causal_wind_orientation_diagram(self):
        from epw_climate_analyzer.p6_report_structure import (
            CATALOG,PRESETS,available_catalog,standard_figure,
        )
        ids=[c[0] for c in CATALOG]
        self.assertIn("wind_orientation",ids)
        self.assertIn("wind_orientation",PRESETS["Architectural climate study"])
        df=self.sample()
        entry=next(c for c in CATALOG if c[0]=="wind_orientation")
        fig,note=standard_figure(entry,df,{})
        self.assertEqual(fig.data[0].type,"heatmap")
        self.assertIn("Candidate windward/exhaust",note)


if __name__=="__main__":
    unittest.main()
