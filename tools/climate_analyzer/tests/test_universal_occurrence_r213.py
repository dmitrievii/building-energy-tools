"""R2.13 fixed occurrence bands, physical admission and calendar parity."""
import unittest
import numpy as np
import pandas as pd
from epw_climate_analyzer.climate_model import CANONICAL_VARIABLES
from epw_climate_analyzer.extended_visualization import (
    occurrence_default_edges, occurrence_table, occurrence_figure,
    radiation_occurrence_kind, WIND_SPEED_COLUMNS, DEPTH_OCCURRENCE_COLUMNS,
    ILLUMINANCE_OCCURRENCE_COLUMNS, W_OCCURRENCE_COLUMN, RH_OCCURRENCE_COLUMN,
    DEW_POINT_COLUMN,
)
from epw_climate_analyzer.occurrence_reference import REFERENCES, DURATION_UNITS_PER_HOUR
from epw_climate_analyzer.profile_interpretation import generic_figure_interpretation

class UniversalOccurrence(unittest.TestCase):
    def frame(self,c,values,minutes=60):
        df=pd.DataFrame({c:values},index=pd.date_range("2026-01-01",periods=len(values),freq=f"{minutes}min"))
        df.attrs["canonical_native_interval_minutes"]=minutes
        return df

    def test_all_canonical_scalar_quantities_have_fixed_edges(self):
        existing=set(WIND_SPEED_COLUMNS+DEPTH_OCCURRENCE_COLUMNS+ILLUMINANCE_OCCURRENCE_COLUMNS+
                     (W_OCCURRENCE_COLUMN,RH_OCCURRENCE_COLUMN,DEW_POINT_COLUMN))
        for c in CANONICAL_VARIABLES:
            if "direction" in c:continue
            with self.subTest(column=c):
                self.assertTrue(c in REFERENCES or c in existing or radiation_occurrence_kind(c))
                for basis,stat in (("Hours","Mean"),("Percentage","Mean"),("Days","Minimum"),("Days","Maximum")):
                    a=occurrence_default_edges(pd.Series([1.,2.,3.]),c,basis=basis,daily_stat=stat)
                    b=occurrence_default_edges(pd.Series([100.,200.,300.]),c,basis=basis,daily_stat=stat)
                    self.assertEqual(a,b)
                    self.assertTrue(len(a)>0 and all(x<y for x,y in zip(a,a[1:])))

    def test_state_bins_and_invalid_daily_observations(self):
        for c in ("moist_air_enthalpy_kj_kg","wet_bulb_temperature_c","specific_volume_m3_kg",
                  "moist_air_density_kg_m3","atmospheric_station_pressure_pa","total_sky_cover_tenths",
                  "opaque_sky_cover_tenths"):
            with self.subTest(column=c):
                spec=REFERENCES[c]
                edges=spec.edges
                valid=edges[0]
                df=self.frame(c,[valid]*48)
                for basis,stat,total in (("Hours","Mean",48.),("Percentage","Mean",100.),
                                         ("Days","Mean",2.),("Days","Minimum",2.),("Days","Maximum",2.)):
                    table=occurrence_table(df,c,edges,basis=basis,daily_stat=stat)
                    self.assertAlmostEqual(float(table.to_numpy().sum()),total)
                    fig=occurrence_figure(table,CANONICAL_VARIABLES[c].unit,basis)
                    self.assertEqual(list(fig.layout.xaxis.ticktext),["Jan"])
                if spec.positive or spec.lower==0.:
                    df.iloc[0,0]=-1.
                    self.assertEqual(float(occurrence_table(df,c,edges).to_numpy().sum()),47.)
                    self.assertEqual(float(occurrence_table(df,c,edges,basis="Days").to_numpy().sum()),1.)
                # Negative enthalpy/wet-bulb observations are physically admitted.
                else:
                    df.iloc[0,0]=-10.
                    self.assertEqual(float(occurrence_table(df,c,edges).to_numpy().sum()),48.)

    def test_duration_cadence_and_daily_totals(self):
        for c,per_hour in DURATION_UNITS_PER_HOUR.items():
            for minutes in (15,60):
                with self.subTest(column=c,minutes=minutes):
                    limit=per_hour*minutes/60
                    df=self.frame(c,[0.,limit/2,limit,limit+1.],minutes)
                    edges=occurrence_default_edges(df[c],c,interval_hours=minutes/60)
                    self.assertEqual(edges[-1],limit)
                    table=occurrence_table(df,c,edges)
                    self.assertAlmostEqual(float(table.to_numpy().sum()),3*minutes/60)
                    self.assertAlmostEqual(float(table.iloc[0,0]),minutes/60)
                    full=self.frame(c,[limit]*(24*60//minutes),minutes)
                    total_edges=occurrence_default_edges(full[c],c,basis="Days",daily_stat="Total",interval_hours=minutes/60)
                    self.assertEqual(float(occurrence_table(full,c,total_edges,basis="Days",daily_stat="Total").to_numpy().sum()),1.)

    def test_enthalpy_custom_edges_and_shared_interpretation(self):
        c="moist_air_enthalpy_kj_kg"
        df=self.frame(c,[50.]*48)
        edges=occurrence_default_edges(df[c],c)
        fig=occurrence_figure(occurrence_table(df,c,edges),"kJ/kg dry air","Hours")
        note=generic_figure_interpretation(df,fig,"occurrence",domain="",column=c,args=("Hours","Mean"))
        self.assertIn("Fixed engineering reference classes",note)
        self.assertIn("50 and 55",note)
        custom=occurrence_figure(occurrence_table(df,c,[40.,60.]),"kJ/kg dry air","Hours")
        note=generic_figure_interpretation(df,custom,"occurrence",domain="",column=c,args=("Hours","Mean"))
        self.assertIn("Selected class boundaries",note)
