"""A1.4 research year: frozen station T residuals and explicit humidity policy.

The six-node mean inverse is a disclosed linear-path reconstruction. Neither
its instantaneous accuracy nor the model-surface pressure at a real station
is qualified by algebraic closure. No existing engine default is changed.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import csv
import io

import numpy as np
import pandas as pd

from .contracts import HistoricalRequest, ClimateResult, FieldDefinition, QualityStatus
from .epw import serialize_epw, validate_epw_bytes, validate_weather
from .thermodynamics import (saturation_water_pa, state_from_vapour, e_from_q,
    pressure_at_2m, q_saturation_at_2m, dew_point_water_c)
from ..climate_model import ClimateLocation, CanonicalClimateDataset, ClimateTemporalMetadata, ClimateProvenance

T, TD, RH, P = ("dry_bulb_temperature_c", "dew_point_temperature_c",
    "relative_humidity_pct", "atmospheric_station_pressure_pa")
Q, PS = "specific_humidity_kg_kg", "surface_pressure_proxy_pa"
WATER_PHASE = "MURPHY_KOOP_LIQUID_WATER_NOT_APP_ASHRAE_ICE_BELOW_ZERO"


@dataclass(frozen=True)
class StationYearRequest(HistoricalRequest):
    mode: str = "station_temperature_year"
    station_key: str = ""

    def __post_init__(self):
        if self.mode != "station_temperature_year" or self.station_key not in ("CH:BAS", "CH:ALT"):
            raise ValueError("A14_ONLY_REGISTERED_CH_RESEARCH_YEARS")
        HistoricalRequest(self.latitude, self.longitude, self.year, self.utc_offset_minutes,
            self.label, "grid_background", self.site_elevation_m, self.site_elevation_reference)
        if self.year != 2025 or self.utc_offset_minutes != 60:
            raise ValueError("A14_REGISTERED_2025_FIXED_CET_ONLY")


class StationYearResult(ClimateResult):
    def to_canonical(self):
        self.validate_contract()
        validate_station_state(self)
        frame = self.data.copy(deep=True)
        frame.index = self.request.local_starts
        frame.attrs.update({"ige_field_definitions": {k: asdict(v) for k,v in self.fields.items()},
            "ige_quality_status": asdict(self.quality), "ige_RH_phase": WATER_PHASE,
            "ige_state_sample_offset_minutes_from_row_start": 60,
            "ige_UI_humidity_phase_adapter_required": True,
            "ige_station_year_contract": "IGE_A14_CONDITIONAL_LOCAL_T_YEAR_v1",
            "ige_existing_U1_display_adapter_supports_this_contract": False})
        return CanonicalClimateDataset(
            climate_id=f"ige-a14-{self.request.station_key}-{self.request.year}",
            display_name=f"{self.request.label} {self.request.year} — research station T reconstruction",
            data=frame, location=self.location,
            temporal=ClimateTemporalMetadata(60, "historical", str(self.request.standard_timezone),
                "interval_start", (self.request.year,)),
            provenance=ClimateProvenance("MeteoSwiss / Open-Meteo / NASA POWER",
                "A1.1 frozen R1; A1.4 linear mean inverse and pointwise humidity projection",
                "IGE engine", "limited CH historical research year", notes=(
                    "Instantaneous temperature is a conditional inverse of six-node hourly means.",
                    "Pressure is an unqualified model-surface proxy with a conditional 2m adapter.",
                    "Other weather fields retain background sources; no independent full-weather qualification.",
                    "MK liquid-water humidity requires a compatible analysis adapter before UI use.",)))


def reconstruct_nodes(background: pd.Series, raw_mean: pd.Series):
    """Invert A T_H = (5 T_{H-1} + 7 T_H)/12; never hide missing R1.

    Missing admitted R1 means explicitly select A(B0). Their raw values stay
    missing in the ledger. A mean fallback need not equal B0 at the endpoint,
    because the inverse has memory. The initial endpoint correction is zero.
    """
    clock = raw_mean.index
    if (not isinstance(clock, pd.DatetimeIndex) or clock.tz is None or len(clock) < 2
            or clock.has_duplicates or not np.all(np.diff(clock.asi8) == 3_600_000_000_000)):
        raise ValueError("A14_CONTIGUOUS_AWARE_MEAN_CLOCK_REQUIRED")
    nodes = clock.insert(0, clock[0]-pd.Timedelta(hours=1))
    if not background.index.equals(nodes) or background.attrs.get("unit") != "°C":
        raise ValueError("A14_BACKGROUND_BOUNDARY_NODE_OR_CELSIUS_MISSING")
    b0 = background.to_numpy(dtype=float)
    raw = raw_mean.to_numpy(dtype=float)
    if not np.isfinite(b0).all() or np.isinf(raw).any():
        raise ValueError("A14_NONFINITE_BACKGROUND_OR_INFINITE_R1")
    mean0 = (5*b0[:-1]+7*b0[1:])/12
    admitted = np.isfinite(raw)
    chosen = np.where(admitted, raw, mean0)
    delta_mean = chosen-mean0
    delta = np.zeros(len(nodes))
    for h, change in enumerate(delta_mean, 1):
        delta[h] = (12*change-5*delta[h-1])/7
    result = pd.Series(b0+delta, index=nodes, name=T)
    result.attrs.update({"unit": "°C", "instantaneous_accuracy_qualified": False})
    error = (5*result.to_numpy()[:-1]+7*result.to_numpy()[1:])/12-chosen
    if np.max(np.abs(error)) > 1e-11:
        raise ValueError("A14_MEAN_INVERSE_RESIDUAL")
    ledger = pd.DataFrame({"B0_mean_C": mean0, "raw_R1_mean_C": raw,
        "R1_admitted": admitted, "selected_mean_C": chosen,
        "selection": np.where(admitted, "R1_ADMITTED", "EXPLICIT_B0_MEAN_FALLBACK"),
        "B0_endpoint_C": b0[1:], "reconstructed_endpoint_C": result.to_numpy()[1:],
        "endpoint_delta_K": delta[1:], "mean_roundtrip_residual_K": error}, index=clock)
    return result, ledger


def project_humidity(t0, rh0, surface_p, t):
    """Keep inferred background q unless water saturation requires reduction.

    Background vapour follows the existing historical UI definition: rounded
    provider T/RH and provider liquid-water Magnus. Td is not a second vapour
    authority. Output uses MK water, including below zero. This is a declared
    transfer policy, not a moist parcel or column mass/energy budget.
    """
    t0, rh0, surface_p, t = np.broadcast_arrays(*(np.asarray(x,dtype=float)
        for x in (t0,rh0,surface_p,t)))
    if not all(np.isfinite(x).all() for x in (t0,rh0,surface_p,t)) or np.any((rh0 <= 0)|(rh0 > 100)):
        raise ValueError("A14_FINITE_POSITIVE_SOURCE_HUMIDITY_REQUIRED_NO_FLOOR")
    e0 = rh0/100*610.94*np.exp(17.625*t0/(243.04+t0))
    q0, p0 = state_from_vapour(t0,e0,surface_p)
    upper = q_saturation_at_2m(t,surface_p)
    q = np.minimum(q0,upper)
    p = pressure_at_2m(t,q,surface_p)
    vapour = e_from_q(q,p)
    rh = 100*(vapour/saturation_water_pa(t))
    td = dew_point_water_c(vapour)
    return {T:t, TD:td, RH:rh, P:p, Q:q, PS:surface_p}, {
        "source_vapour_pa":e0, "inferred_background_q_kg_kg":q0,
        "background_conditional_p2m_pa":p0, "saturation_q_upper_kg_kg":upper,
        "projected_q_kg_kg":q, "delta_q_kg_kg":q-q0,
        "delta_mixing_ratio_kg_kg_dry_air":q/(1-q)-q0/(1-q0),
        "q_projection_active":q<q0,
        "RH_before_q_projection_pct":100*e_from_q(q0,pressure_at_2m(t,q0,surface_p))/saturation_water_pa(t)}


def validate_station_state(result):
    result.validate_contract()
    f=result.data
    t,td,rh,p,q,ps=(f[k].to_numpy(dtype=float) for k in (T,TD,RH,P,Q,PS))
    e=e_from_q(q,p)
    residual={"max_RH_closure_pp":float(np.max(np.abs(100*e/saturation_water_pa(t)-rh))),
        "max_Td_vapour_closure_pa":float(np.max(np.abs(saturation_water_pa(td)-e))),
        "max_conditional_pressure_closure_pa":float(np.max(np.abs(pressure_at_2m(t,q,ps)-p)))}
    if (np.any((q<=0)|(q>=1)|(rh<0)|(rh>100)) or np.any(td>t+1e-10)
            or residual["max_RH_closure_pp"]>1e-7 or residual["max_Td_vapour_closure_pa"]>1e-5
            or residual["max_conditional_pressure_closure_pa"]>1e-7):
        raise ValueError("A14_CONDITIONAL_STATE_CLOSURE_FAILED")
    return residual


def assemble_station_year(base, endpoint_t, *, station_key, latitude, longitude,
                          nominal_elevation_m, name, r1_source, temperature_diagnostics):
    base.validate_contract()
    if base.future_request is not None or not endpoint_t.index.equals(base.request.utc_ends):
        raise ValueError("A14_HISTORICAL_ENDPOINT_CLOCK_REQUIRED")
    request=StationYearRequest(latitude,longitude,base.request.year,base.request.utc_offset_minutes,
        name,"station_temperature_year",nominal_elevation_m,
        "Frozen station nominal elevation; datum and ERA5 orography transfer unqualified",station_key)
    state, changes=project_humidity(base.data[T],base.data[RH],base.data[P],endpoint_t.to_numpy())
    frame=base.data.copy(deep=True)
    for key,value in state.items(): frame[key]=value
    fields=dict(base.fields)
    fields[T]=FieldDefinition("°C","instant_at_interval_end","a14_r1","conditional reconstruction at target T sensor",
        "Frozen R1 hourly six-node means; explicit B0-mean fallback; linear inverse with 72h spinup")
    for key,unit,definition in ((TD,"°C","inverse MK water vapour pressure; not frost point"),
            (RH,"%","MK liquid-water RH below and above zero; not NASA daily hurs"),
            (Q,"kg/kg moist air","inferred background q; unique pointwise least-squares saturation projection"),
            (P,"Pa","conditional source-surface to 2m pressure; not actual local station pressure")):
        fields[key]=FieldDefinition(unit,"instant_at_interval_end","a14_state",
            "conditional state referenced to unqualified model-surface pressure proxy",definition)
    fields[PS]=FieldDefinition("Pa","instant_at_interval_end","open_meteo","model surface as provided",
        "Original absolute model-surface pressure proxy; not reduced pressure or verified local pressure")
    sources=(*base.sources,{"id":"a14_r1",**r1_source},
        {"id":"a14_state","method":"KEEP_INFERRED_Q_THEN_POINTWISE_SATURATION_PROJECTION",
         "background_vapour_authority":"provider rounded T/RH liquid-water Magnus; not independently rounded Td"})
    ledger=pd.DataFrame(changes,index=frame.index)
    for key in (T,TD,RH,P):
        ledger["original_"+key]=base.data[key]
        ledger["output_"+key]=frame[key]
        ledger["delta_"+key]=frame[key]-base.data[key]
    ledger["original_surface_pressure_proxy_pa"]=base.data[P]
    diagnostics={"background":base.diagnostics,"temperature":temperature_diagnostics,
        "humidity_policy":"POINTWISE_MINIMUM_Q_CHANGE_WITH_COUPLED_WATER_SATURATION_BOUND",
        "pressure_policy":"CONDITIONAL_MODEL_SURFACE_PLUS_2M_NOT_SITE_HEIGHT_TRANSFER",
        "q_projection_hours":int(ledger.q_projection_active.sum()),
        "atmospheric_water_mass_latent_heat_or_condensate_flux_conserved":False,
        "NASA_NEX_daily_constraints_used":False,"independent_accuracy_qualified":False,
        "full_weather_cross_field_consistency_qualified":False,"production_ready":False,
        "UI_connected":False,"unchanged_background_fields":[k for k in base.data if k not in (T,TD,RH,P)]}
    result=StationYearResult(request,frame,ClimateLocation(latitude,longitude,nominal_elevation_m,city=name),
        fields,sources,(*base.transformations,{"operation":"a14_station_year",**diagnostics}),
        ({"operation":"a14_hourly_adjustment_ledger","all_hours_logged":True,"records":len(ledger)},),
        QualityStatus("SOURCE_CLOCK_AND_METHOD_CHECKS_PASS","CONDITIONAL_T_P_Q_RH_CLOSURE_ONLY",
            "NOT_INDEPENDENTLY_QUALIFIED","CH_2025_RESEARCH_EXPORT; UI_NOT_CONNECTED"),diagnostics)
    diagnostics["conditional_state_closure"]=validate_station_state(result)
    return result,ledger


def serialize_station_epw(result):
    validate_station_state(result)
    raw,_=serialize_epw(result)
    rows=list(csv.reader(io.StringIO(raw.decode())))
    rows[0][1]=result.request.label+" STATION T RESEARCH"
    rows[0][4]="IGE_A14_R1_CONDITIONAL_STATE"
    rows[5]=["COMMENTS 1","R1 T means inverted under linear hourly path; explicit mean fallbacks logged. MK water humidity projection. Pressure remains unqualified model-surface proxy with conditional 2m adapter."]
    rows[6]=["COMMENTS 2","2025 fixed CET; other weather retained from background. Nominal station elevation is not a verified pressure datum. No independent full-weather accuracy or production qualification. See manifest and ledgers."]
    rows[7][3]=f"HISTORICAL {result.request.year} CH LIMITED RESEARCH"
    for row,(_,values) in zip(rows[8:],result.data.iterrows()):
        for column,key in ((6,T),(7,TD),(8,RH),(9,P)):
            row[column]=format(float(values[key]),".7f")
    stream=io.StringIO(newline="");csv.writer(stream,lineterminator="\n").writerows(rows)
    payload=stream.getvalue().encode()
    readback=validate_epw_bytes(payload,result)
    a=np.asarray([list(map(float,r[6:10])) for r in rows[8:]])
    # Readback tolerance is derived from the declared 7-decimal output grid.
    sat_t=saturation_water_pa(a[:,0]);sat_td=saturation_water_pa(a[:,1])
    error=np.abs(100*sat_td/sat_t-a[:,2])
    # Conservative propagation at all corners of the half-grid cells.
    step=5.0001e-8
    lower=100*saturation_water_pa(a[:,1]-step)/saturation_water_pa(a[:,0]+step)
    upper=100*saturation_water_pa(a[:,1]+step)/saturation_water_pa(a[:,0]-step)
    if np.any((lower>a[:,2]+step)|(upper<a[:,2]-step)):
        raise ValueError("A14_EPW_SERIALIZED_WATER_CLOSURE_INTERVALS_INCOMPATIBLE")
    readback.update({"state_numeric_grid":"T/Td/RH/p: 7 decimal places",
        "serialized_water_closure_quantization_intervals":"PASS",
        "max_serialized_RH_from_T_Td_residual_pp":float(error.max()),
        "provider_values_modified":True,"conditional_exact_internal_closure":True,
        "true_local_pressure_or_independent_accuracy_qualified":False})
    return payload,readback
