"""R2.6 rainfall/snow scientific figures, daily admission and interpretations."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.precipitation import (
    complete_daily_precipitation,annual_precipitation_indices,
    aggregate_precipitation_duration,occurrence_records,occurrence_hours,
)
from epw_climate_analyzer.precipitation_findings import (
    P,SNOW,DURATION,T,rainfall_summary,snow_summary,measured_duration_summary,
    wet_dry_interpretation,rolling_interpretation,freeze_interpretation,
    rain_day_classes,rain_day_classes_figure,precipitation_figure_interpretation,
)


class PrecipitationR26Tests(unittest.TestCase):
    def sample(self):
        idx=pd.date_range("2026-02-01",periods=72,freq="h")
        df=pd.DataFrame({
            P:[0.]*24+[1.]*24+[0.]*24,
            DURATION:[0.]*24+[10.]*24+[0.]*24,
            SNOW:[0.]*24+[5.]*12+[0.]*36,
            T:[-1.]*6+[2.]*66,
            "wind_speed_m_s":[2.]*72,
            "wind_direction_deg":[90.]*72,
        },index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_complete_daily_indices_match_standard_wet_day_categories(self):
        df=self.sample()
        daily=complete_daily_precipitation(df)
        self.assertEqual(daily.tolist(),[0.,24.,0.])
        a=annual_precipitation_indices(df).iloc[0]
        self.assertEqual(a.precipitation_total_mm,24.)
        self.assertEqual(a.wet_days_ge_1mm,1)
        self.assertEqual(a.heavy_days_ge_10mm,1)
        self.assertEqual(a.very_heavy_days_ge_20mm,1)
        self.assertEqual(a.longest_dry_spell_days,1)
        self.assertEqual(a.incomplete_or_missing_days,0)

    def test_missing_source_hour_breaks_daily_event_and_dry_spell(self):
        df=self.sample().drop(pd.Timestamp("2026-02-02 12:00"))
        daily=complete_daily_precipitation(df)
        self.assertTrue(pd.isna(daily.iloc[1]))
        a=annual_precipitation_indices(df).iloc[0]
        self.assertEqual(a.valid_daily_totals,2)
        self.assertEqual(a.incomplete_or_missing_days,1)
        self.assertAlmostEqual(a.precipitation_total_mm,23.)
        self.assertEqual(a.wet_days_ge_1mm,0)
        self.assertEqual(a.longest_dry_spell_days,1)

    def test_hour_filter_keeps_observed_sum_but_no_fake_complete_day(self):
        df=self.sample().iloc[::2].copy()
        daily=complete_daily_precipitation(df)
        self.assertTrue(daily.isna().all())
        result=annual_precipitation_indices(df).iloc[0]
        self.assertAlmostEqual(result.precipitation_total_mm,12.)
        self.assertEqual(result.valid_daily_totals,0)
        self.assertTrue(pd.isna(result.max_daily_precipitation_mm))
        self.assertTrue(pd.isna(result.wet_days_ge_1mm))

    def test_negative_rain_snow_and_unphysical_duration_are_screened(self):
        df=self.sample()
        df.loc[df.index[24],P]=-5.
        df.loc[df.index[48],SNOW]=-2.
        df.loc[df.index[25],DURATION]=65.
        daily=complete_daily_precipitation(df)
        self.assertTrue(pd.isna(daily.iloc[1]))
        self.assertEqual(annual_precipitation_indices(df).iloc[0].precipitation_total_mm,23.)
        self.assertIn("source-duration records",measured_duration_summary(df))
        self.assertEqual(float(aggregate_precipitation_duration(df,"Daily").duration_min.sum()),230.)

    def test_measured_wet_duration_and_record_frequency_are_distinct(self):
        df=self.sample()
        a=aggregate_precipitation_duration(df,"Daily")
        self.assertAlmostEqual(float(a.duration_min.sum()/60),4.)
        rec=occurrence_records(df,P,0.1,"Daily")
        self.assertEqual(float(rec.records.sum()),24.)
        cover=occurrence_hours(df,SNOW,0.,"Daily",inclusive=False)
        self.assertAlmostEqual(float(cover.hours.sum()),12.)

    def test_subhour_cadence_and_partial_day_gate(self):
        idx=pd.date_range("2026-03-01",periods=48,freq="30min")
        df=pd.DataFrame({P:[.2]*48},index=idx)
        df.attrs["canonical_native_interval_minutes"]=30.
        daily=complete_daily_precipitation(df)
        self.assertAlmostEqual(float(daily.iloc[0]),9.6)
        df=df.drop(idx[5])
        self.assertTrue(complete_daily_precipitation(df).isna().all())

    def test_wet_spell_interpretation_counts_events_and_dry_days(self):
        df=self.sample()
        wet=wet_dry_interpretation(df,wet=True,threshold=1.)
        dry=wet_dry_interpretation(df,wet=False,threshold=1.)
        self.assertIn("1 observed wet spells",wet)
        self.assertIn("2 observed dry spells",dry)
        self.assertIn("rainwater-storage drawdown",dry)

    def test_rain_day_severity_partition_and_monthly_plot(self):
        df=self.sample()
        data=rain_day_classes(df)
        self.assertEqual(int(data["≥20 mm"].sum()),1)
        self.assertEqual(int(data["1–<10 mm"].sum()),0)
        self.assertEqual(int(data["10–<20 mm"].sum()),0)
        fig=rain_day_classes_figure(data)
        self.assertEqual(len(fig.data),3)
        self.assertEqual(fig.layout.barmode,"stack")

    def test_plot_interpretations_use_actual_plotted_extrema(self):
        df=self.sample()
        fig=go.Figure()
        fig.add_scatter(x=["Feb","Mar"],y=[3.,9.],name="Mean")
        note=precipitation_figure_interpretation(df,fig,"profile",column=P)
        self.assertIn("Feb (3.0 mm)",note)
        self.assertIn("Mar (9.0 mm)",note)
        self.assertIn("roof drainage",note)

    def test_snow_summary_describes_state_duration_and_max(self):
        note=snow_summary(self.sample())
        self.assertIn("5.0 cm",note)
        self.assertIn("12 h",note)
        self.assertIn("roof-weather exposure",note)

    def test_rolling_window_stays_interval_integral(self):
        df=self.sample()
        note=rolling_interpretation(df,3)
        self.assertIn("3-hour precipitation accumulation",note)
        self.assertIn("3.0 mm",note)

    def test_temperature_frost_exposure_interpretation(self):
        df=self.sample()
        df.loc[df.index[6],T]=3.
        note=freeze_interpretation(df,wet_threshold=1.)
        self.assertIn("complete days",note)
        self.assertIn("façade",note.lower() if "façade" in note else note)

    def test_report_admission_and_rendering(self):
        from epw_climate_analyzer import p6_report_structure as rep
        df=self.sample()
        selected=rep.available_catalog(df,{})
        ids={x[0] for x in selected}
        self.assertIn("rain_severity",ids)
        self.assertIn("snow_cover",ids)
        self.assertIn("rain_wind",ids)
        for kind in ("rain_severity","snow_cover","rain_wind"):
            entry=next(x for x in selected if x[0]==kind)
            fig,note=rep.standard_figure(entry,df,{})
            self.assertTrue(fig.data)
            if kind=="rain_severity":
                self.assertIn("Selected-period",note)
            elif kind=="snow_cover":
                self.assertIn("snow cover",note.lower())
            else:
                self.assertIn("wind",note.lower())

    def test_directional_rain_exposure_is_concentrated_in_incoming_sector(self):
        from epw_climate_analyzer.directional_climate import directional_table
        table=directional_table(self.sample(),radial="Wind-driven rain exposure",colour="Wind speed")
        self.assertAlmostEqual(float(table.radius.fillna(0).sum()),48.)
        self.assertEqual(str(table.loc[table.radius.idxmax(),"direction"]),"E")

    def test_atlas_rainfall_notes_are_figure_specific(self):
        from epw_climate_analyzer import p66_catalogue as cat
        from epw_climate_analyzer.p66_render import make_figure
        df=self.sample()
        d=next(x for x in cat.catalogue(df,{},cat.FULL)
               if x.chapter==cat.RAIN and x.kind=="total" and x.column==P
               and x.args==("Monthly",))
        f,note=make_figure(d,df,{})
        self.assertEqual(f.data[0].type,"bar")
        self.assertIn("Selected-period liquid precipitation",note)


if __name__=="__main__":
    unittest.main()
