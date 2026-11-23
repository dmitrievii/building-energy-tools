"""R2.7: quantified shading interpretations, orientation decision and UI/report admission."""
from __future__ import annotations

import ast
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from epw_climate_analyzer.solar_shading import shaded_fraction,shading_ledger
from epw_climate_analyzer.shading_findings import (
    shading_mask_interpretation,shading_ledger_interpretation,
    shading_temporal_interpretation,shading_monthly_interpretation,
    shading_cells_interpretation,orientation_shading_table,
    orientation_shading_figure,orientation_shading_interpretation,
)
from epw_climate_analyzer.shading_calendar import shading_frame,OCCURRENCE
from epw_climate_analyzer.shading_temporal import (
    AREA,ENERGY,REDUCTION,temporal_shading_tables,
)
from epw_climate_analyzer.facade_orientation import ORIENTATIONS


GEOMETRY=dict(facade=180.,width=2.,height=1.5,
              overhang=.6,left_fin=0.,right_fin=0.)


def observations():
    index=pd.date_range("2026-06-21 08:00",periods=12,freq="h")
    df=pd.DataFrame({
        "solar_apparent_zenith_deg":[60.,50.,40.,30.,20.,30.,40.,50.,60.,70.,100.,110.],
        "solar_azimuth_deg":[80.,105.,130.,160.,180.,205.,230.,260.,285.,300.,0.,20.],
        "global_horizontal_radiation_wh_m2":[120.,200.,300.,400.,450.,420.,320.,210.,110.,20.,0.,0.],
        "direct_normal_radiation_wh_m2":[200.,330.,450.,500.,530.,510.,430.,360.,250.,60.,0.,0.],
        "diffuse_horizontal_radiation_wh_m2":[55.,75.,95.,100.,105.,110.,110.,90.,60.,18.,0.,0.],
        "dry_bulb_temperature_c":[16.,18.,22.,25.,28.,30.,32.,31.,25.,20.,15.,14.],
    },index=index)
    df.attrs["canonical_native_interval_minutes"]=60.
    return df


class ShadingR27Tests(unittest.TestCase):
    def test_normal_azimuth_has_closed_analytical_shade(self):
        shade=shaded_fraction(np.array([180.,180.,180.]),
            np.array([20.,45.,70.]),**GEOMETRY)
        self.assertTrue(np.all(np.diff(shade)>0))
        self.assertAlmostEqual(float(shade[1]),.4,places=12)
        self.assertAlmostEqual(float(shade[2]),1.,places=12)
        description=shading_mask_interpretation(GEOMETRY)
        self.assertIn("40.0%",description)
        self.assertIn("100.0%",description)
        self.assertIn("20°",description)

    def test_zero_devices_have_zero_energy_across_all_orientations(self):
        df=observations()
        simple={**GEOMETRY,"overhang":0.}
        table=orientation_shading_table(df,geometry=simple)
        self.assertEqual(len(table),8)
        self.assertTrue(np.allclose(table.intercepted_direct_kwh_m2,0.))
        self.assertTrue(np.allclose(table.hot_intercepted_kwh_m2,0.))

    def test_ledger_describes_peak_month_and_thermal_condition(self):
        df=observations()
        ledger=shading_ledger(df,**GEOMETRY)
        note=shading_ledger_interpretation(ledger,df,geometry=GEOMETRY)
        for token in ("180° façade","direct beam","intercept","June 2026",
                      "outdoor T >26 °C","T <18 °C"):
            self.assertIn(token,note)
        self.assertAlmostEqual(float(ledger["Intercepted direct"].sum()),
            sum(float(ledger[c+" intercepted direct"].sum())
                for c in ("Overhang","Left fin","Right fin")),places=9)

    def test_all_eight_orientation_rows_match_primary_solver(self):
        df=observations()
        table=orientation_shading_table(df,geometry=GEOMETRY)
        self.assertEqual(table.direction.tolist(),[x[1] for x in ORIENTATIONS])
        self.assertTrue(((table.direct_reduction_pct>=0)&
                         (table.direct_reduction_pct<=100)).all())
        for _,row in table.iterrows():
            g={**GEOMETRY,"facade":row.azimuth_deg}
            ledger=shading_ledger(df,**g)
            self.assertAlmostEqual(float(row.incident_direct_kwh_m2),
                ledger["Unshaded direct"].sum()/1000.,places=10)
            self.assertAlmostEqual(float(row.intercepted_direct_kwh_m2),
                ledger["Intercepted direct"].sum()/1000.,places=10)
            parts=sum(float(row[c]) for c in (
                "cold_intercepted_kwh_m2",
                "intermediate_intercepted_kwh_m2",
                "hot_intercepted_kwh_m2",
                "unknown_temperature_intercepted_kwh_m2"))
            self.assertAlmostEqual(parts,float(row.intercepted_direct_kwh_m2),places=10)
        fig=orientation_shading_figure(table)
        self.assertEqual(fig.layout.barmode,"stack")
        self.assertEqual(len(fig.data),3)
        note=orientation_shading_interpretation(table)
        self.assertIn("greatest total direct-beam interception",note)
        self.assertIn("warm-weather interception",note)
        self.assertIn("winter solar admission",note)

    def test_temperature_missing_retains_intercepted_energy_as_unknown(self):
        df=observations().drop(columns=["dry_bulb_temperature_c"])
        table=orientation_shading_table(df,geometry=GEOMETRY)
        self.assertTrue(np.allclose(
            table.unknown_temperature_intercepted_kwh_m2,
            table.intercepted_direct_kwh_m2))
        self.assertEqual(len(orientation_shading_figure(table).data),4)

    def test_invalid_threshold_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"Cold temperature threshold"):
            orientation_shading_table(observations(),geometry=GEOMETRY,
                                      cold_c=30.,hot_c=20.)

    def test_temporal_geometry_and_energy_have_different_statistics(self):
        df=observations()
        area=shading_frame(df,geometry=GEOMETRY,metric=AREA)
        energy=shading_frame(df,geometry=GEOMETRY,metric=ENERGY)
        occurrence=shading_frame(df,geometry=GEOMETRY,metric=OCCURRENCE,threshold=80.)
        area_note=shading_temporal_interpretation(area,AREA)
        energy_note=shading_temporal_interpretation(energy,ENERGY)
        event_note=shading_temporal_interpretation(occurrence,OCCURRENCE,threshold=80.)
        self.assertIn("front-facing solar observations",area_note)
        self.assertIn("kWh/m²",energy_note)
        self.assertIn("80%",event_note)
        self.assertIn("eligible duration",event_note)

    def test_temporal_monthly_summary_and_peak_cells(self):
        df=observations()
        for metric in (AREA,ENERGY,REDUCTION):
            monthly,cells=temporal_shading_tables(df,geometry=GEOMETRY,metric=metric)
            note=shading_monthly_interpretation(monthly,metric,year=2026)
            cell=shading_cells_interpretation(cells,metric,year=2026)
            self.assertIn("June",note)
            self.assertIn("June",cell)
            self.assertIn("2026",cell)
        energy=shading_monthly_interpretation(monthly,REDUCTION,year=2026)
        self.assertIn("ratio",energy)

    def test_shading_mask_is_reachable_from_shading_page(self):
        root=Path(__file__).resolve().parents[1]
        source=(root/"app.py").read_text(encoding="utf-8")
        parsed=ast.parse(source)
        funcs={n.name:ast.get_source_segment(source,n)
               for n in parsed.body if isinstance(n,ast.FunctionDef)}
        nav=funcs["render_shading_design"]
        self.assertIn('options.append("Geometric shading mask")',nav)
        self.assertIn('render_sun_path(df,shading_geometry=geometry)',nav)
        self.assertIn('options.append("Façade orientation comparison")',nav)
        self.assertIn("orientation_shading_table(",nav)
        self.assertEqual(nav.count('_shading_geometry("shading_analysis")'),1)
        self.assertIn("overlay_shading_mask(fig",funcs["render_sun_path"])

    def test_architectural_and_passive_reports_include_shaded_energy(self):
        from epw_climate_analyzer import p6_report_structure as rep
        ids=[row[0] for row in rep.CATALOG]
        for id in ("shading_energy","shading_orientation"):
            self.assertIn(id,ids)
            self.assertIn(id,rep.PRESETS["Architectural climate study"])
            self.assertIn(id,rep.PRESETS["Passive design"])
        entries=rep.available_catalog(observations(),{})
        for name in ("shading_energy","shading_orientation"):
            entry=next(e for e in entries if e[0]==name)
            fig,note=rep.standard_figure(entry,observations(),{})
            self.assertGreater(len(fig.data),0)
            self.assertIn("kWh/m²",note)

    def test_atlas_shading_diagrams_have_metric_specific_findings(self):
        from epw_climate_analyzer import p66_catalogue as cat
        from epw_climate_analyzer.p66_render import make_figure
        df=observations()
        charts=cat.catalogue(df,{},cat.FULL)
        for kind,token in (
            ("shading_mask","Analytical geometric shading"),
            ("shading_calendar","front-facing solar observations"),
            ("shading_temporal","Monthly"),
            ("shading_irradiation","incident direct beam"),
        ):
            candidates=[d for d in charts if d.chapter==cat.SHADE
                        and d.kind==kind and d.status=="available"]
            if not candidates:continue
            fig,note=make_figure(candidates[0],df,{})
            self.assertTrue(fig.data)
            self.assertIn(token.lower(),note.lower())


if __name__=="__main__":
    unittest.main()
