"""Fixed engineering reference classes for scalar climate occurrence plots.

Edges are descriptive engineering comparison bands in canonical units.
Duration thresholds refer to native interval amounts or complete daily totals.
Physical bounds are separate from class edges and never clip observations.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class Reference:
    edges: tuple[float, ...]
    context: str
    lower: float | None = None
    upper: float | None = None
    positive: bool = False
    zero_label: str = ""

TEMPERATURE = Reference((0.,15.,25.,30.), "The classes characterize freezing exposure, cool conditions, mild weather and warm to hot outdoor air.")
GROUND = Reference((0.,5.,10.,15.,20.,25.,30.), "Ground-temperature classes characterize freezing exposure and the temperature regime relevant to ground-coupled heat transfer.")
REFERENCES = {
    "dry_bulb_temperature_c": TEMPERATURE,
    "dry_bulb_temperature_min_c": TEMPERATURE,
    "dry_bulb_temperature_max_c": TEMPERATURE,
    **{"ground_temperature_"+d+"m_c": GROUND for d in ("0_10","0_20","0_50","1_00","2_00")},
    "moist_air_enthalpy_kj_kg": Reference((0.,20.,35.,50.,55.,70.,90.), "Enthalpy combines sensible and latent energy per kilogram of dry air. The 50 and 55 kJ/kg boundaries align with existing HVAC and moisture screening references; the difference from the indoor target determines ventilation conditioning potential."),
    "wet_bulb_temperature_c": Reference((0.,10.,15.,20.,25.,28.,31.), "Wet-bulb temperature characterizes the evaporative cooling limit and warm-humid exposure; lower values allow a lower ideal evaporatively cooled air temperature."),
    "specific_volume_m3_kg": Reference((.70,.75,.80,.85,.90,.95,1.,1.10), "Specific volume converts volumetric airflow to dry-air mass flow. Larger values imply less dry-air mass per unit volume.", positive=True),
    "moist_air_density_kg_m3": Reference((.90,1.,1.10,1.20,1.25,1.30,1.40), "Moist-air density determines moist-air mass flow at a specified volumetric flow and contributes to buoyancy and wind dynamic pressure.", positive=True),
    "atmospheric_station_pressure_pa": Reference((60000.,70000.,80000.,90000.,95000.,100000.,105000.), "Station pressure characterizes the absolute atmospheric pressure governing air density and pressure-dependent psychrometric properties. The bands distinguish high-altitude and near-sea-level conditions.", positive=True),
    "total_sky_cover_tenths": Reference((2.,5.,8.,10.), "Sky cover classes distinguish clear, low, partial, extensive and complete cloud coverage on the source 0–10 scale.", lower=0., upper=10., zero_label="Clear (= 0)"),
    "opaque_sky_cover_tenths": Reference((2.,5.,8.,10.), "Opaque sky cover describes the fraction covered by clouds that obscure the sky; 10 tenths represents complete opaque cover.", lower=0., upper=10., zero_label="No opaque cover (= 0)"),
    "sunshine_duration_s": Reference((), "Sunshine-duration classes quantify recorded bright sunshine within the source interval or accumulated over a complete day.", lower=0., zero_label="No recorded sunshine (= 0)"),
    "precipitation_duration_min": Reference((), "Precipitation-duration classes quantify time with precipitation within the source interval or accumulated over a complete day.", lower=0., zero_label="No recorded precipitation duration (= 0)"),
    "zenith_luminance_cd_m2": Reference((100.,500.,1000.,2500.,5000.,10000.,20000.), "Zenith luminance classes describe the brightness of the sky at the zenith, relevant to daylight availability.", lower=0., zero_label="No recorded luminance (= 0)"),
    "visibility_km": Reference((.2,.5,1.,2.,5.,10.,20.), "Visibility bands characterize atmospheric optical clarity and restricted visibility; the 1 km boundary marks the conventional fog visibility criterion.", lower=0.),
    "ceiling_height_m": Reference((100.,300.,500.,1000.,2000.,3000.), "Cloud ceiling classes characterize the height of the reported cloud base or obscuring layer.", lower=0.),
    "precipitable_water_mm": Reference((5.,10.,20.,30.,40.,60.), "Precipitable water describes integrated atmospheric water vapour as an equivalent liquid-water depth.", lower=0.),
    "aerosol_optical_depth_thousandths": Reference((50.,100.,200.,400.,600.,1000.), "Aerosol optical depth classes describe increasing atmospheric aerosol extinction in the EPW thousandths convention.", lower=0.),
    "albedo": Reference((.1,.2,.3,.5,.7,.9), "Albedo classes characterize the reflected fraction of incident shortwave radiation, relevant to ground-reflected solar exposure.", lower=0., upper=1.),
    "days_since_last_snowfall": Reference((1.,3.,7.,14.,30.,60.), "Elapsed days since snowfall characterize the age of the reported snow state.", lower=0.),
}
DURATION_UNITS_PER_HOUR = {"sunshine_duration_s":3600., "precipitation_duration_min":60.}
DURATION_TOTAL_EDGES = {
    "sunshine_duration_s": (7200.,14400.,21600.,28800.,36000.,43200.,57600.),
    "precipitation_duration_min": (15.,30.,60.,120.,240.,480.,720.,1440.),
}

def reference_edges(column, *, basis="Hours", daily_stat="Mean", interval_hours=1.):
    spec=REFERENCES.get(column)
    if spec is None:return None
    if column not in DURATION_UNITS_PER_HOUR:return spec.edges
    if basis=="Days" and daily_stat=="Total":return DURATION_TOTAL_EDGES[column]
    maximum=DURATION_UNITS_PER_HOUR[column]*interval_hours
    return tuple(float(f"{maximum*f:.10g}") for f in (.25,.5,.75,1.))

def reference_note(column, edges, *, basis="Hours", daily_stat="Mean", interval_hours=1.):
    spec=REFERENCES.get(column)
    if spec is None:return ""
    expected=reference_edges(column,basis=basis,daily_stat=daily_stat,interval_hours=interval_hours)
    prefix="Fixed engineering reference classes. " if tuple(edges)==expected else "Selected class boundaries. "
    return prefix+spec.context
