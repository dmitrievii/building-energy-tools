"""Capture actual render calls with deterministic controls, without a Streamlit server.

Unlike an independently reconstructed figure, this executes the checked-in UI
function body itself. No report renderer is called from this module.
Browser delivery remains a separate smoke/acceptance layer.
"""
from __future__ import annotations

import ast
from pathlib import Path
from functools import lru_cache
from unittest.mock import patch
import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from epw_climate_analyzer import p66_catalogue as cat, p4_ui, p3_ui
from epw_climate_analyzer.degree_metrics import degree_metric_table,degree_metric_interpretation
from epw_climate_analyzer.temporal_filtering import display_period_labels,time_basis
from epw_climate_analyzer.chart_theme import metric_color
from epw_climate_analyzer.sun_path_views import available_radiation_fields
from epw_climate_analyzer.relationship_findings import LABELS
from epw_climate_analyzer.decisions import natural_ventilation_condition

APP=Path(__file__).resolve().parents[1]/"app.py"
APP_ROUTES=frozenset({"render_sun_path","render_monthly_radiation","_render_temperature_degree_days","render_natural_ventilation","render_hvac_passive"})


class Controls:
    def __init__(self,settings):
        self.settings=settings
        self.session_state={}
        self.messages=[]
    def _option(self,label,options,index=0,key=None,**kw):
        opts=list(options)
        value=self.settings.get(key,self.settings.get(label,self.session_state.get(key,opts[index])))
        if value not in opts:raise AssertionError(f"UI control {label}: {value!r} unavailable in {opts!r}")
        return value
    selectbox=_option
    radio=_option
    def multiselect(self,label,options,default=None,key=None,**kw):
        values=self.settings.get(key,self.settings.get(label,default or []))
        assert all(v in options for v in values),(label,values,options)
        return values
    def checkbox(self,label,value=False,key=None,**kw):
        return self.settings.get(key,self.settings.get(label,value))
    def slider(self,label,min_value=None,max_value=None,value=None,step=None,key=None,**kw):
        return self.settings.get(key,self.settings.get(label,value))
    def number_input(self,label,min_value=None,max_value=None,value=None,step=None,key=None,**kw):
        return self.settings.get(key,self.settings.get(label,value))
    def columns(self,count,**kw):
        return [self]* (count if isinstance(count,int) else len(count))
    def expander(self,*a,**kw):return self
    def __enter__(self):return self
    def __exit__(self,*a):return False
    def info(self,msg):self.messages.append(str(msg))
    warning=info
    error=info
    def caption(self,*a,**kw):pass
    markdown=caption
    dataframe=caption
    download_button=caption
    header=caption
    write=caption
    def button(self,*a,**kw):return False


@lru_cache(maxsize=1)
def app_code():
    tree=ast.parse(APP.read_text(encoding="utf-8"),filename=str(APP))
    defs=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in APP_ROUTES]
    if {node.name for node in defs}!=APP_ROUTES:raise AssertionError("Missing website rendering function")
    return compile(ast.Module(body=defs,type_ignores=[]),str(APP),"exec")


def _capture(df,name,settings,*,p4_args=(),app_kwargs=None):
    ui=Controls(settings);captured=[]
    render=lambda fig,note:captured.append((fig,note))
    if name in APP_ROUTES:
        env=dict(pd=pd,np=np,px=px,go=go,st=ui,render_plot=render,
                 degree_metric_table=degree_metric_table,degree_metric_interpretation=degree_metric_interpretation,
                 display_period_labels=display_period_labels,time_basis=time_basis,metric_color=metric_color,
                 natural_ventilation_condition=natural_ventilation_condition)
        exec(app_code(),env)
        with patch.object(p3_ui,"st",ui):
            env[name](df,**(app_kwargs or {}))
    elif name in ("outdoor_comfort","condensation_panel","moisture_panel","illuminance_panel","extensive_total_panel","reference_eligibility_panel","temperature_threshold_panel","snow_hours_panel"):
        with patch.object(p3_ui,"st",ui):
            getattr(p3_ui,name)(df,render,**(app_kwargs or {}))
    else:
        with patch.object(p4_ui,"st",ui):
            if name=="precipitation_panel":
                p4_ui.precipitation_panel(df,None,*p4_args,render)
            else:getattr(p4_ui,name)(df,render,*p4_args)
    if len(captured)!=1:raise AssertionError(f"{name}: expected one live render, got {len(captured)}; {ui.messages}")
    return captured[0]


def capture_atlas(d,df,context):
    k,c,a=d.kind,d.column,d.args
    if k=="total":
        from epw_climate_analyzer.residual_findings import TOTAL_FIELDS
        return _capture(df,"extensive_total_panel",{"extensive_total_quantity":TOTAL_FIELDS[c][0],"extensive_total_period":a[0]},app_kwargs={"columns":(c,)})
    if k in ("eligibility_map","eligibility_total"):
        name,period=a
        return _capture(df,"reference_eligibility_panel",{"reference_screen_name":{"nv":"Natural ventilation","night":"Night flushing","shade":"Solar protection screening"}[name],
            "reference_screen_view":"Eligibility heat map" if k=="eligibility_map" else "Eligible hours by period",
            "reference_screen_period":period.capitalize() if k=="eligibility_map" else period},
            app_kwargs={"names":(name,),"reference_df":df})
    if k=="temp_threshold":
        low,high=context.get("temperature thresholds",(18.,26.))
        return _capture(df,"temperature_threshold_panel",{"temperature_threshold_period":a[0],"temperature_threshold_mode":"Heating and cooling thresholds",
             "temperature_condition_heating":low,"temperature_condition_cooling":high})
    if k=="passive":
        return _capture(df,"render_hvac_passive",{"Analysis type":"Passive strategy summary","passive_strategy_view":"Monthly strategy matrix"})
    if k=="nv_special":
        style=a[0]
        settings={"Analysis type":{"Persistence":"Continuous ventilation periods","Daily duration":"Daily suitable-hours duration curve",
                    "Temperature–wind suitability":"Temperature–wind suitability","Rejected reasons":"Rejected reasons",
                    "Directional suitability":"Directional analysis","Wind during suitable hours":"Directional analysis"}[style],
                  "nv_directional_view":"Strict-screen eligible hours" if style=="Directional suitability" else "Wind during suitable hours",
                  "nv_directional_radial":"Hours","nv_directional_aggregation":"Annual"}
        return _capture(df,"render_natural_ventilation",settings,app_kwargs={"pressure_pa":101325.})
    if k=="condensation":
        return _capture(df,"condensation_panel",{"p3_cond_surface":15.,"p3_cond_chart":"Dew-point margin duration"})
    if k=="moisture":
        return _capture(df,"moisture_panel",{"p3_moist_flow":1000.,"p3_moist_target":9.,"p3_moist_chart":"Monthly water mass"})
    if k=="illumination":
        return _capture(df,"illuminance_panel",{"p3_lux_quantity":{"global_horizontal_illuminance_lux":"Global horizontal",
             "diffuse_horizontal_illuminance_lux":"Diffuse horizontal","direct_normal_illuminance_lux":"Direct normal"}[c],
             "p3_lux_threshold":300.,"p3_lux_period":a[0],"p3_lux_view":"Availability hours"})
    if k=="utci" or k.startswith("utci_"):
        settings={"p3_otc_year":"All selected years","p3_otc_model":"Open-sky screening"}
        if k=="utci":
            model,style=a
            settings.update({"p3_otc_model":"Uniform radiant offset" if model=="Uniform radiant offset" else "Open-sky screening",
                "p3_otc_chart":{"heatmap":"UTCI heat map","stress":"Monthly thermal-stress distribution","duration":"UTCI duration curve"}[style],
                "p3_otc_exposure":model,"p3_otc_duration_exposure":model})
        elif k=="utci_sensitivity":
            # The controlled sensitivity grid is independent of the observed MRT model.
            settings.update({"p3_otc_model":"Uniform radiant offset","p3_otc_chart":"Sensitivity analysis",
                "p3_sens_axis":{"Temperature–wind":"Air temperature × wind speed",
                    "Temperature–radiant offset":"Air temperature × radiant offset",
                    "Wind–radiant offset":"Wind speed × radiant offset"}[a[0]]})
        else:
            settings.update({"p3_otc_chart":"Sun versus shade",
                "p3_otc_pair_view":{"utci_pair":"Monthly mean UTCI","utci_pair_delta":"Monthly UTCI reduction",
                    "utci_pair_stress":"Heat-stress exposure","utci_pair_mrt":"Mean radiant temperature"}[k]})
        return _capture(df,"outdoor_comfort",settings)
    if k=="sunpath_view":
        style,colour=a
        fields=dict(available_radiation_fields(df))
        return _capture(df,"render_sun_path",{
            "Chart type":{"2D":"2D sun-path diagram","Technical":"Technical sun-path diagram","3D":"3D sun-path diagram"}[style],
            "Radiation quantity":fields.get(colour,"None"),
            "Colour mapped quantity":colour if colour in ("Outdoor temperature","Solar benefit / risk") else "None",
        })
    if k=="monthly_radiation":
        return _capture(df,"render_monthly_radiation",{"Chart type":a[0],"Radiation basis":"Source radiation"})
    if k=="degree":
        return _capture(df,"_render_temperature_degree_days",{
            "degree_heating_indoor_c":20.,"degree_heating_limit_c":12.,
            "degree_cooling_indoor_c":26.,"degree_cooling_limit_c":26.,
            "Degree metric":a[0],"Method":a[0],"Calculation method":a[0],
            "degree_metric_type":a[0],"degree_metric_method":a[0],
            "degree_metric_aggregation":a[1],
        })
    if k=="day_indicators":
        return _capture(df,"temperature_panel",{"Extreme-day analysis":"Frost days and tropical nights"})
    if k in ("cumulative","freeze_cycles","snow_calendar"):
        view={"cumulative":"Precipitation accumulation","freeze_cycles":"Freeze–thaw days","snow_calendar":"Snow-cover calendar"}[k]
        settings={"Accumulation type":"Cumulative observed blocks","Chart type":"Observed freeze–thaw sequences"}
        if k=="snow_calendar" and a:settings["Year"]=a[0]
        return _capture(df,"precipitation_panel",settings,p4_args=(view,))
    if k=="correlation":
        return _capture(df,"multivariate_panel",{"Multivariate analysis":"Correlation matrix","Quantities":[LABELS[v] for v in a]})
    if k=="joint":
        return _capture(df,"multivariate_panel",{"Multivariate analysis":"Paired scatter" if a[1]=="scatter" else "Joint probability density","X quantity":LABELS[c],"Y quantity":LABELS[a[0]],"Bins per axis":25})
    raise AssertionError(f"Missing live capture for {k}")


def capture_standard(entry,df,context):
    ident,chapter,title,column,unit,k=entry
    if k in ("nv","night","shade"):
        return capture_atlas(cat.Diagram(ident,chapter,title,"eligibility_total",column,unit,(k,"Monthly")),df,context)
    if k=="snow_hours":
        return _capture(df,"snow_hours_panel",{"snow_hours_period":"Monthly"})
    if k in ("hvac_design_hot","hvac_design_cold"):
        return _capture(df,"hvac_panel",{"p4_hvac_quantity":"Air temperature [°C]",
            "p4_hvac_tail":"Upper (cooling / moisture)" if k=="hvac_design_hot" else "Lower (heating)",
            "p4_hvac_view":"Statistical design conditions"})
    if k=="total" and column==cat.P:
        return capture_atlas(cat.Diagram(ident,chapter,title,"total",column,unit,("Monthly",)),df,context)
    if k=="illumination":
        return _capture(df,"illuminance_panel",{"p3_lux_quantity":"Global horizontal",
             "p3_lux_threshold":10000.,"p3_lux_period":"Monthly","p3_lux_view":"Availability hours"})
    if k=="utci":
        return capture_atlas(cat.Diagram(ident,chapter,title,"utci",args=("Uniform radiant offset","stress")),df,context)
    if k=="utci_shading":
        return capture_atlas(cat.Diagram(ident,chapter,title,"utci_pair_delta"),df,context)
    if k=="sunpath":
        return capture_atlas(cat.Diagram(ident,chapter,title,"sunpath_view",args=("2D",cat.N)),df,context)
    if k=="degree":
        return capture_atlas(cat.Diagram(ident,chapter,title,"degree",column,unit,("Degree-days","Monthly")),df,context)
    if k=="total" and column==cat.G:
        return _capture(df,"render_monthly_radiation",{"Chart type":"Bar chart","Radiation basis":"Source radiation","Radiation quantity":["GHI"]})
    raise AssertionError(f"Missing standard live capture for {k}")
