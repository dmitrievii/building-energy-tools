"""R2.8 generic chart parity: independent explorer and atlas construction."""
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer import p66_catalogue as cat
from epw_climate_analyzer import charts as ch, extended_visualization as ex
from epw_climate_analyzer.p66_render import make_figure
from epw_climate_analyzer.p6_report_structure import CATALOG, standard_figure
from epw_climate_analyzer.profile_interpretation import (
    generic_figure_interpretation, quantity_domain,
)
from epw_climate_analyzer.figure_interpretation_contract import validate_figure_interpretation
from epw_climate_analyzer.p6_report import snapshot


def weather():
    idx=pd.date_range("2026-01-30",periods=96,freq="h")
    x=np.arange(len(idx))
    cycle=np.sin(x*2*np.pi/24.)
    frame=pd.DataFrame({
        cat.T:15+10*cycle,cat.DEW:5+4*cycle,
        "wet_bulb_temperature_c":10+6*cycle,
        cat.RH:55+15*cycle,cat.W:6+2*cycle,cat.H:30+10*cycle,
        cat.SV:.85+.02*cycle,"moist_air_density_kg_m3":1.2+.01*cycle,
        "atmospheric_station_pressure_pa":95000+200*cycle,
        cat.V:2+cycle,cat.WD:180+40*cycle,
        cat.G:np.maximum(0,500*cycle),cat.D:np.maximum(0,100*cycle),
        cat.N:np.maximum(0,600*cycle),
        cat.P:np.where(x%7==0,1+x%3,0.),cat.S:2+cycle,
        cat.LUX:np.maximum(0,30000*cycle),
        "total_sky_cover_tenths":5+2*cycle,
        "hour_of_day":idx.hour,"month_index":idx.month,
    },index=idx)
    frame.attrs["canonical_native_interval_minutes"]=60.
    return frame


def explorer_figure(d,df):
    """Build the live explorer representation from the same settings.

    This calls the public numerical chart builders separately from Atlas;
    it deliberately uses different presentation titles and route aliases.
    """
    c,u,a,k=d.column,d.unit,d.args,d.kind
    title="Website: "+cat.LABELS[c]
    scope=df
    if k=="profile":
        f=ch.time_series_profile_chart(df,c,a[0],title+" · "+a[0]+" · Min–mean–max",u,"Min–mean–max")
        alias="Time series / Profile"
    elif k=="percentile":
        f=ch.time_series_profile_chart(df,c,a[0],title+" · "+a[0]+" · P05–median–P95",u,"P05–median–P95")
        alias="Time series / Profile"
    elif k=="time_series":
        f=ch.time_series_profile_chart(df,c,a[0],title+" · "+a[0]+" · "+a[1],u,a[1])
        alias="Time series / Profile"
    elif k=="heatmap":
        f=ch.temporal_heatmap_chart(df,c,*a,title,u)
        alias="Heat map"
    elif k in ("duration","histogram","box","violin"):
        if a[0]=="wet":scope=df.loc[df[c].gt(0)].copy()
        if k=="duration":
            from epw_climate_analyzer.p4_design_charts import (
                add_design_quantiles,supports_design_quantiles,DESIGN_PERCENTAGES,
            )
            f=ex.probability_figure(scope,c,u,a[1]) if a[2]=="probability" else ch.duration_chart(scope,c,title,u,ascending=a[1])
            if supports_design_quantiles(scope,c):
                add_design_quantiles(f,scope,c,u,ascending=a[1],percentage=a[2]=="probability",percentages=DESIGN_PERCENTAGES)
            alias="Duration curve"
        elif k=="histogram":f=ch.histogram_chart(scope,c,title,u,bins=40);alias="Histogram"
        else:
            f=ch.monthly_box_chart(scope,c,title,u,violin=k=="violin")
            alias="Monthly violin plot" if k=="violin" else "Monthly boxplot"
    elif k=="diurnal":
        f=ex.diurnal_figure(ex.diurnal_statistics(df,c),c,u,representation=a[0],centre=a[1],band=a[2])
        alias="Typical daily profile"
    elif k=="occurrence":
        from epw_climate_analyzer.aggregations import native_interval_hours
        edges=ex.occurrence_default_edges(df[c],c,basis=a[0],daily_stat=a[1],interval_hours=native_interval_hours(df))
        if c=="diffuse_radiation_fraction_pct" and a[0]=="Days":
            from epw_climate_analyzer.solar_findings import diffuse_fraction_daily_occurrence
            table=diffuse_fraction_daily_occurrence(df,edges,daily_stat=a[1])
        else:table=ex.occurrence_table(df,c,edges,basis=a[0],daily_stat=a[1])
        f=ex.occurrence_figure(table,u,a[0]);alias="Monthly occurrence classes"
    elif k=="amplitude":
        f=ex.amplitude_figure(df,c,a[0],cat.LABELS[c]);alias="Amplitude"
    else:raise ValueError(k)
    return scope,f,alias


class R28VariableParityTests(unittest.TestCase):
    def test_quantity_taxonomy_is_independent_of_chapter(self):
        for chapter,variables in cat.VARIABLE_GROUPS.items():
            for column,_,_ in variables:
                with self.subTest(column=column):
                    self.assertEqual(quantity_domain(column,"Unrelated tab"),chapter)

    def test_independently_built_explorer_and_atlas(self):
        df=weather()
        rows=cat.catalogue(df,{},cat.REP)
        allowed={"profile","percentile","time_series","heatmap","duration","histogram","box","violin","diurnal","occurrence","amplitude"}
        # At least one registered variant of each available quantity/kind.
        for d in rows:
            if d.status!="available" or d.kind not in allowed:continue
            with self.subTest(diagram=d.id):
                scope,live,alias=explorer_figure(d,df)
                actual,note=make_figure(d,df,{})
                expected=generic_figure_interpretation(scope,live,alias,domain=d.chapter,column=d.column,args=d.args)
                self.assertEqual(expected,note)
                self.assertTrue(note.strip())
                self.assertTrue(validate_figure_interpretation(actual,note,require_binding=True))

    def test_wet_only_distributions_use_positive_observations(self):
        df=weather()
        for d in cat.catalogue(df,{},cat.FULL):
            if d.column!=cat.P or d.kind not in ("duration","histogram","box","violin") or d.args[0]!="wet":continue
            with self.subTest(diagram=d.id):
                scope,live,alias=explorer_figure(d,df)
                self.assertTrue(scope[cat.P].gt(0).all())
                _,note=make_figure(d,df,{})
                expected=generic_figure_interpretation(scope,live,alias,domain=cat.RAIN,column=cat.P,args=d.args)
                self.assertEqual(note,expected)
                self.assertIn("positive precipitation intervals",note)

    def test_standard_duration_and_heatmap(self):
        df=weather()
        rows=cat.catalogue(df,{},cat.FULL)
        for ident,kind,args in (("temperature_duration","duration",("all",False,"hours")),
                                ("temperature_heatmap","heatmap",("month","Hour of day","Mean"))):
            entry=next(e for e in CATALOG if e[0]==ident)
            fig,note=standard_figure(entry,df,{})
            # Standard duration omits optional quantile markers; compare with
            # the identically configured explorer rather than a different graph.
            if kind=="duration":
                live=ch.duration_chart(df,cat.T,"Explorer", "°C",ascending=False)
            else:
                live=ch.temporal_heatmap_chart(df,cat.T,*args,"Explorer","°C")
            expected=generic_figure_interpretation(df,live,kind,domain=cat.TEMP,column=cat.T,args=args)
            self.assertEqual(note,expected)
            self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))

    def test_dew_and_wet_bulb_extended_routes_are_quantity_first(self):
        df=weather()
        for column in (cat.DEW,"wet_bulb_temperature_c"):
            for d in cat.catalogue(df,{},cat.FULL):
                if d.column!=column or d.kind not in ("diurnal","occurrence"):continue
                scope,live,alias=explorer_figure(d,df)
                a=generic_figure_interpretation(scope,live,alias,domain=cat.TEMP,column=column,args=d.args)
                b=generic_figure_interpretation(scope,live,alias,domain=cat.HUM,column=column,args=d.args)
                self.assertEqual(a,b)
                self.assertIn("dew point" if column==cat.DEW else "wet-bulb",a.lower().replace("dew-point","dew point"))

    def test_snapshot_preserves_exact_narrative(self):
        df=weather()
        d=next(d for d in cat.catalogue(df,{},cat.REP) if d.column==cat.DEW and d.kind=="diurnal")
        fig,note=make_figure(d,df,{})
        self.assertEqual(snapshot(fig,{"page":cat.HUM},note)["interpretation"],note)


if __name__=="__main__":
    unittest.main()
