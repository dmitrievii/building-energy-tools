#!/usr/bin/env python3
"""P9.2D explicit NON-CLIMATE synthetic fixture for EnergyPlus EPW parser.

These 8760 hourly rows are generated from analytic trigonometric functions,
not original ERA5 or original NASA CMIP6. Test only exporter field semantics
and real EnergyPlus model execution. Fixture has clear provenance in header.
"""
from __future__ import annotations
import argparse,csv,datetime as dt,json,math
from pathlib import Path
from p9_2a_joint_weather_regimes import Day
from p9_2b_cmip6_daily_joint_regime_solver import sat_pa,SIGMA
from p9_1h23_physical_inversion_candidate import solar_altitude_degrees
from p9_2d_annual_cet_epw_export import raw_series_to_epw,readback,LOCATION_LAT,LOCATION_LON

SHA="f"*64
DATES=[dt.date(2012,12,31)]+[
    dt.date(2013,1,1)+dt.timedelta(days=i) for i in range(365)]

def dummy_weather(yearly_temp_offset):
    days=[];longwave=[]
    for d in DATES:
        arr=[];lw=[]
        doy=d.timetuple().tm_yday
        for h in range(24):
            when=dt.datetime(d.year,d.month,d.day,h,30,tzinfo=dt.timezone.utc)
            alt=solar_altitude_degrees(when,LOCATION_LAT,LOCATION_LON)
            cos=max(0.,math.sin(math.radians(alt)))
            t=(9+yearly_temp_offset+10*math.sin(2*math.pi*(doy-100)/365)
                +4*math.sin(2*math.pi*(h-8)/24))
            td=t-4
            RH=100*sat_pa(td)/sat_pa(t)
            wet= (doy%9==0 and h in (8,9,10))
            cover=90. if wet else 20.
            ghi= (170 if wet else 780)*cos
            beam=(.08 if wet else .68)*ghi
            diffuse=ghi-beam
            arr.append({"temperature_2m":t,"dew_point_2m":td,
                "relative_humidity_2m":RH,"surface_pressure":980.,
                "precipitation":.7 if wet else 0.,
                "cloud_cover":cover,
                "shortwave_radiation":ghi,"direct_radiation":beam,
                "diffuse_radiation":diffuse,
                "direct_normal_irradiance":(beam/cos if cos>0 else 0),
                "wind_speed_10m":2.2,"wind_direction_10m":240.})
            lw.append(.8*SIGMA*(t+273.15)**4)
        days.append(Day(d,tuple(arr),SHA))
        longwave.append(lw)
    return days,longwave

def write_fixture(out,offset):
    name=f"P9_2D_EXPLICIT_SYNTHETIC_FORMAT_FIXTURE_TEMP_OFFSET_{int(offset)}C_NOT_CMIP6_NOT_ERA5.epw"
    fp=out/name
    days,lw=dummy_weather(offset)
    audit=raw_series_to_epw(days,lw,fp)
    with fp.open("r",encoding="utf8",newline="") as f:
        rows=list(csv.reader(f))
    rows[0][4]="IGE_P92D_PURE_SYNTHETIC_FORMAT_TEST_NOT_CLIMATE_SOURCE"
    rows[5]=["COMMENTS 1","SYNTHETIC trig-periodic temperature and solar test vectors; no NASA, ERA5 or station source. Format smoke only; NOT observed weather."]
    rows[6]=["COMMENTS 2","DO NOT use for buildings climate/energy decisions; static verification of P9.2D UTC-to-CET and 35-field EPW encoding only."]
    with fp.open("w",encoding="utf8",newline="") as f:
        w=csv.writer(f,lineterminator="\n");w.writerows(rows)
    check=readback(fp)
    if check["sha256"]==audit["sha256"]:
        raise ValueError("P92D_TEST_FIXTURE_HEADER_PROVENANCE_NOT_CHANGED")
    return {"source_type":"MATHEMATICAL_SYNTHETIC_FIXTURE_ONLY",
            "EPW_filename":name,"SHA256":check["sha256"],"readback":check}

def run(out):
    out.mkdir(parents=True,exist_ok=True)
    cases=[write_fixture(out,0),write_fixture(out,5)]
    audit={"phase":"P92D_ONLY_FORMAT_AND_REAL_ENERGYPLUS_COMPATIBILITY_SYNTHETIC_CONTROL",
           "original_NASA_CMIP6_or_ERA5_real_hourly_weather_used":False,
           "source": "deterministic analytic function, no real climate values",
           "input_fixture_count":len(cases),
           "annual_EPWs_are_genuine_climate_files":False,
           "P9_2D_real_CanESM5_annual_epw_not_generated_from_six_blocked_days":True,
           "production_epw_ready":False,"files":cases}
    (out/"p9_2d_synthetic_format_fixture_provenance.json").write_text(
        json.dumps(audit,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    print("P92D_FORMAT_FIXTURE_FINAL",json.dumps({
       "n_generated_format_epw_test_fixtures":len(cases),
       "each_8760x35":all(x["readback"]["n_records"]==8760 for x in cases),
       "actual_weather_source":False,"production_ready":False}),flush=True)
    return audit
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("--out",default="outputs/p92d-fixture")
    a=p.parse_args();run(Path(a.out))
