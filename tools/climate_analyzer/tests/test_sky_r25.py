"""R2.5 sky/daylight, measured sunshine and outdoor-light scientific gates."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from epw_climate_analyzer.daylight import (
    daylight_duration_hours,monthly_daylight_sunshine_summary,_complete_daily_sunshine_hours,
)
from epw_climate_analyzer.sky_findings import (
    TOTAL,OPAQUE,GLOBAL,DIFFUSE,DIRECT,SUN,GHI,
    sky_condition_interpretation,sky_light_table,sky_joint_interpretation,
    sky_figure_interpretation,daylight_interpretation,illuminance_interpretation,
    sunshine_interpretation,sky_radiation_scatter_interpretation,
)


class SkyDaylightR25Tests(unittest.TestCase):
    def sample(self, *, periods=48,freq="h"):
        index=pd.date_range("2026-06-01",periods=periods,freq=freq)
        hour=index.hour.to_numpy()
        daylight=(hour>=6)&(hour<18)
        bright=np.where(daylight,10000.,0.)
        sunshine=np.where(daylight,1800.,0.)
        frame=pd.DataFrame({
            TOTAL:np.where(hour<8,9.,np.where(hour<18,1.,5.)),
            OPAQUE:np.where(hour<8,8.,np.where(hour<18,2.,4.)),
            GLOBAL:bright,
            DIFFUSE:bright*.7,
            DIRECT:bright*.4,
            SUN:sunshine,
            GHI:bright/20.,
        },index=index)
        frame.attrs["canonical_native_interval_minutes"]=60.
        return frame

    def test_latitude_changes_daylight_seasonality(self):
        winter,summer=355,172
        graz=daylight_duration_hours(47.,np.array([winter,summer]))
        singapore=daylight_duration_hours(1.35,np.array([winter,summer]))
        self.assertGreater(float(graz[1]-graz[0]),7.)
        self.assertLess(float(singapore[1]-singapore[0]),.6)
        for lat,word in ((47.,"strong seasonal difference"),(1.35,"changes modestly")):
            frame=self.sample().iloc[:24]
            second=frame.copy()
            second.index=pd.date_range("2026-12-21",periods=24,freq="h")
            combined=pd.concat([frame,second])
            note=daylight_interpretation(combined,lat)
            self.assertIn(word,note)
            self.assertIn("seasonal variation",note)

    def test_complete_days_and_relative_sunshine(self):
        df=self.sample()
        result=monthly_daylight_sunshine_summary(df,47.)
        june=result.loc[result.month_index==6].iloc[0]
        self.assertEqual(int(june.sunshine_days),2)
        self.assertAlmostEqual(float(june.total_sunshine_h),12.)
        self.assertGreater(float(june.relative_sunshine_pct),0.)
        self.assertLess(float(june.relative_sunshine_pct),100.)
        note=sunshine_interpretation(df,47.,"relative_sunshine")
        self.assertIn("complete observation days",note)
        self.assertIn("direct-sun access",note)

    def test_gap_fails_complete_day_with_declared_one_hour_cadence(self):
        df=self.sample().iloc[::2].copy()
        df.attrs["canonical_native_interval_minutes"]=60.
        s=monthly_daylight_sunshine_summary(df,47.)
        self.assertNotIn("relative_sunshine_pct",s)

    def test_invalid_sunshine_duration_fails_that_day(self):
        df=self.sample()
        df.loc[df.index[5],SUN]=5000.
        s=monthly_daylight_sunshine_summary(df,47.)
        june=s.loc[s.month_index==6].iloc[0]
        self.assertEqual(int(june.sunshine_days),1)
        self.assertAlmostEqual(float(june.total_sunshine_h),6.)

    def test_negative_and_nan_sunshine_reject_complete_day(self):
        for bad in (float("nan"),-10.):
            with self.subTest(bad=bad):
                df=self.sample()
                df.loc[df.index[5],SUN]=bad
                s=monthly_daylight_sunshine_summary(df,47.)
                self.assertEqual(int(s.loc[s.month_index==6,"sunshine_days"].iloc[0]),1)

    def test_half_hour_source_uses_physical_duration(self):
        idx=pd.date_range("2026-03-01",periods=48,freq="30min")
        df=pd.DataFrame({SUN:[900.]*48},index=idx)
        df.attrs["canonical_native_interval_minutes"]=30.
        s=monthly_daylight_sunshine_summary(df,47.)
        march=s.loc[s.month_index==3].iloc[0]
        self.assertEqual(int(march.sunshine_days),1)
        self.assertAlmostEqual(float(march.total_sunshine_h),12.)
        df.loc[idx[12],SUN]=1801.
        s=monthly_daylight_sunshine_summary(df,47.)
        self.assertNotIn("relative_sunshine_pct",s)

    def test_dry_zero_sunshine_is_observed_valid(self):
        df=self.sample();df[SUN]=0.
        s=monthly_daylight_sunshine_summary(df,47.)
        june=s.loc[s.month_index==6].iloc[0]
        self.assertEqual(int(june.sunshine_days),2)
        self.assertEqual(float(june.relative_sunshine_pct),0.)

    def test_sky_cover_classes_partition_all_valid_samples(self):
        df=self.sample()
        note=sky_condition_interpretation(df,TOTAL)
        self.assertIn("clear (0–2 tenths)",note)
        self.assertIn("overcast (8–10 tenths)",note)
        self.assertIn("diffuse-light collection",note)

    def test_opaque_cover_above_total_is_reported_as_source_consistency_issue(self):
        df=self.sample()
        df[OPAQUE]=df[TOTAL]
        df.loc[df.index[:5],OPAQUE]=10.
        df.loc[df.index[:5],TOTAL]=2.
        note=sky_condition_interpretation(df,OPAQUE)
        self.assertIn("Source-field consistency flag: 5 paired hours",note)
        self.assertIn("greater than total sky cover",note)
        self.assertEqual(int((df[OPAQUE]>df[TOTAL]).sum()),5)

    def test_monthly_joint_sky_exterior_illuminance_hours_close(self):
        df=self.sample()
        table=sky_light_table(df,threshold_lux=3000.)
        self.assertEqual(table.index.tolist(),[6])
        classes=("Clear 0–2 tenths","Intermediate >2–<8","Overcast 8–10 tenths")
        self.assertAlmostEqual(float(table.loc[6,list(classes)].sum()),24.)
        self.assertAlmostEqual(float(table.loc[6,"Bright exterior hours"]),24.)
        self.assertAlmostEqual(float(table.loc[6,"Valid paired hours"]),48.)
        note=sky_joint_interpretation(df,3000.)
        self.assertIn("clear sky",note)
        self.assertIn("overcast sky",note)

    def test_illuminance_exposure_uses_observation_denominator(self):
        df=self.sample()
        note=illuminance_interpretation(df,GLOBAL,threshold_lux=10000.)
        self.assertIn("24 h",note)
        self.assertIn("50.0%",note)
        self.assertIn("electric-light dimming",note)

    def test_figures_interpret_chart_specific_months_and_extrema(self):
        df=self.sample()
        f=go.Figure()
        f.add_scatter(x=["Jun","Jul"],y=[4.,9.],name="Mean")
        note=sky_figure_interpretation(df,f,"profile",column=TOTAL)
        self.assertIn("Jun (4.0 tenths)",note)
        self.assertIn("Jul (9.0 tenths)",note)
        hm=go.Figure(go.Heatmap(x=["Jun","Jul"],y=[12,15],z=[[5.,15.],[10.,25.]]))
        note=sky_figure_interpretation(df,hm,"heatmap",column=GLOBAL)
        self.assertIn("25.0 lux",note)

    def test_scatter_uses_daylight_positive_ghi(self):
        df=self.sample()
        note=sky_radiation_scatter_interpretation(df)
        self.assertIn("positive-GHI daylight observations",note)
        self.assertIn("solar positions",note)

    def test_report_catalog_contains_daylight_cloud_and_exterior_light(self):
        from epw_climate_analyzer import p6_report_structure as rep
        df=self.sample()
        entries=rep.available_catalog(df,{"latitude":47.})
        ids={entry[0] for entry in entries}
        for name in ("daylight","sky_cover","exterior_light","sunshine_ratio"):
            self.assertIn(name,ids)
        self.assertIn("sky_cover",rep.PRESETS["Architectural climate study"])
        self.assertIn("exterior_light",rep.PRESETS["Passive design"])
        for name in ("sky_cover","exterior_light","sunshine_ratio"):
            item=next(e for e in entries if e[0]==name)
            fig,note=rep.standard_figure(item,df,{"latitude":47.})
            self.assertTrue(len(fig.data))
            self.assertTrue(len(note)>40)


if __name__=="__main__":
    unittest.main()
