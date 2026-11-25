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

    def test_r28b_complete_month_gate_and_positive_walter_lieth(self):
        from epw_climate_analyzer.p6_report_structure import available_catalog
        from r28_specialized_routes import standard_live
        df=weather()
        e=next(e for e in CATALOG if e[0]=="climograph")
        self.assertNotIn(e,available_catalog(df,{}))
        with self.assertRaisesRegex(ValueError,"complete paired"):
            standard_figure(e,df,{})
        idx=pd.date_range("2026-02-01","2026-03-01",freq="h",inclusive="left")
        full=pd.DataFrame({cat.T:12.,cat.P:0.1},index=idx)
        full.attrs["canonical_native_interval_minutes"]=60.
        self.assertIn(e,available_catalog(full,{}))
        fig,note=standard_figure(e,full,{})
        _,expected=standard_live(e,full,{})
        self.assertEqual(note,expected)
        self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))

    def test_r28b_independent_wind_and_psychrometric_routes(self):
        from r28_specialized_routes import atlas_live
        df=weather()
        rows=cat.catalogue(df,{},cat.REP)
        for kind in ("wind_mean","wind_classes","wind_panel","psychrometric"):
            d=next(d for d in rows if d.kind==kind and d.status=="available")
            with self.subTest(diagram=d.id):
                fig,note=make_figure(d,df,{})
                _,expected=atlas_live(d,df,{})
                self.assertEqual(note,expected)
                self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))

    def test_r28b_native_monthly_observations_do_not_invent_hourly_exposure(self):
        idx=pd.date_range("2026-01-01",periods=3,freq="MS")
        df=pd.DataFrame({cat.T:[1.,2.,4.],cat.DEW:[-2.,0.,1.]},index=idx)
        df.attrs["canonical_native_resolution"]="monthly"
        for d in cat.catalogue(df,{},cat.REP):
            if d.kind!="native":continue
            fig,note=make_figure(d,df,{})
            live=ch.time_series_profile_chart(df,d.column,"Native",
                "Website · Native · Observed values",d.unit,"Observed values")
            expected=generic_figure_interpretation(df,live,"Time series / Profile",
                    domain=d.chapter,column=d.column)
            self.assertEqual(note,expected)
            self.assertIn("3 valid native monthly",note)
            self.assertNotIn("observed hours",note)

    def test_r28c_actual_render_calls_match_reports(self):
        from r28_interpretation_audit import fixture
        from r28_live_route_capture import capture_atlas,capture_standard
        df=fixture()
        context={"latitude":47.07}
        rows=cat.catalogue(df,context,cat.REP)
        selected=[]
        for kind in ("sunpath_view","monthly_radiation","degree","day_indicators",
                     "cumulative","snow_calendar","correlation","joint"):
            selected.extend([d for d in rows if d.kind==kind and d.status=="available"][:2])
        for d in selected:
            with self.subTest(diagram=d.id):
                fig,note=make_figure(d,df,context,reference_df=df)
                live,expected=capture_atlas(d,df,context)
                self.assertEqual(note,expected)
                self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))
                self.assertEqual(snapshot(fig,{"page":d.chapter},note)["interpretation"],expected)
                if d.kind in ("joint","correlation","degree","monthly_radiation","day_indicators","cumulative"):
                    self.assertEqual(len(fig.data),len(live.data))
                    for rt,lt in zip(fig.data,live.data):
                        for field in ("y","z","r","theta"):
                            rv=getattr(rt,field,None);lv=getattr(lt,field,None)
                            if rv is None and lv is None:continue
                            if rv is None or lv is None:self.fail(f"Missing trace field {field}")
                            try:rv=np.asarray(rv,dtype=float);lv=np.asarray(lv,dtype=float)
                            except (ValueError,TypeError):continue
                            np.testing.assert_allclose(rv,lv,rtol=1e-12,atol=1e-12,equal_nan=True)
        for ident in ("ghi","sunpath","degree"):
            entry=next(e for e in CATALOG if e[0]==ident)
            with self.subTest(standard=ident):
                fig,note=standard_figure(entry,df,context,reference_df=df)
                _,expected=capture_standard(entry,df,context)
                self.assertEqual(note,expected)
                self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))

    def test_r28c_complete_degree_days_are_the_same_on_all_surfaces(self):
        from epw_climate_analyzer.degree_metrics import degree_metric_table
        index=pd.date_range("2026-01-01",periods=48,freq="h").delete(24)
        df=pd.DataFrame({cat.T:10.},index=index)
        df.attrs["canonical_native_interval_minutes"]=60.
        actual=degree_metric_table(df,metric="Degree-days",aggregation="Monthly",
                                   require_complete_days=True)
        self.assertAlmostEqual(float(actual.iloc[0,0]),10.)
        self.assertEqual(actual.attrs["method"],"complete-daily-mean")


    def test_r28e_residual_numeric_and_narrative_parity(self):
        from r28_interpretation_audit import fixture
        from r28_specialized_routes import atlas_live,standard_live
        from epw_climate_analyzer.p6_report_structure import available_catalog
        from epw_climate_analyzer.p66_render import NotApplicable
        df=fixture();context={"latitude":47.07}
        families={"total","eligibility_total","eligibility_map","temp_threshold","nv_special",
                  "passive","sky_conditions","shading_mask"}
        checked=set()
        def compare(fig,note,live,expected):
            self.assertEqual(note,expected)
            self.assertTrue(validate_figure_interpretation(fig,note,require_binding=True))
            self.assertEqual(len(fig.data),len(live.data))
            for rt,lt in zip(fig.data,live.data):
                for field in ("y","z","r","theta","customdata"):
                    rv=getattr(rt,field,None);lv=getattr(lt,field,None)
                    if rv is None and lv is None:continue
                    if rv is None or lv is None:self.fail(f"Missing trace field {field}")
                    try:rv=np.asarray(rv,dtype=float);lv=np.asarray(lv,dtype=float)
                    except (ValueError,TypeError):continue
                    np.testing.assert_allclose(rv,lv,rtol=1e-12,atol=1e-12,equal_nan=True)
        for d in cat.catalogue(df,context,cat.FULL):
            if d.status!="available" or d.kind not in families:continue
            with self.subTest(diagram=d.id):
                try:fig,note=make_figure(d,df,context,reference_df=df)
                except NotApplicable:continue
                live,expected=atlas_live(d,df,context)
                compare(fig,note,live,expected);checked.add(d.kind)
        self.assertEqual(checked,families)
        for entry in available_catalog(df,context):
            if entry[-1] not in ("nv","night","shade","snow_hours","hvac_design_hot","hvac_design_cold") and entry[0]!="rain":continue
            with self.subTest(standard=entry[0]):
                fig,note=standard_figure(entry,df,context,reference_df=df)
                live,expected=standard_live(entry,df,context)
                compare(fig,note,live,expected)

    def test_r28e_extensive_totals_and_snow_native_cadence(self):
        from epw_climate_analyzer.residual_findings import extensive_total_figure,snow_hours_figure
        from epw_climate_analyzer.decisions import rejection_reasons_for_nv
        idx=pd.date_range("2026-01-01",periods=6,freq="10min")
        df=pd.DataFrame({cat.P:[1.,2.,0.,np.nan,3.,0.],cat.T:[10.,20.,20.,20.,30.,np.nan],
                         cat.W:[5.,10.,5.,5.,5.,5.],cat.S:[0.,1.,1.,np.nan,0.,2.],
                         "precipitation_duration_min":[10.,5.,0.,np.nan,11.,0.]},index=idx)
        df.attrs["canonical_native_interval_minutes"]=10.
        fig,_=extensive_total_figure(df,cat.P,"Monthly")
        self.assertAlmostEqual(float(np.nansum(fig.data[0].y)),6.)
        fig,_=extensive_total_figure(df,"precipitation_duration_min","Monthly")
        self.assertAlmostEqual(float(np.nansum(fig.data[0].y)),.25)
        fig,_=snow_hours_figure(df)
        self.assertAlmostEqual(float(np.nansum(fig.data[0].y)),.5)
        reasons=rejection_reasons_for_nv(df,16.,26.,9.).set_index("reason")
        for reason in ("Too cold","Too hot","Too humid"):
            self.assertAlmostEqual(float(reasons.loc[reason,"hours"]),1./6.)


if __name__=="__main__":
    unittest.main()
