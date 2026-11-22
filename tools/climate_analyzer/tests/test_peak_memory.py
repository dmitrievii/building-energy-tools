"""R2 qualification: real worker parity, admission and safe cleanup."""
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from epw_climate_analyzer import p66_catalogue as c
from epw_climate_analyzer.exporting import dataframe_to_csv_bytes
from epw_climate_analyzer.p66_export import generate_atlas,PDF_MODES
from epw_climate_analyzer import atlas_isolation as iso

class PeakMemoryTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2026-01-01",periods=48,freq="h")
        df=pd.DataFrame({c.T:range(48),c.RH:60.,c.V:2.,c.WD:90.},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        ds=[d for d in c.catalogue(df,{},c.REP) if d.status=="available" and d.kind=="profile"][:2]
        return df,ds
    def test_csv_index_parity_without_dataframe_copy(self):
        df,_=self.fixture()
        for frame in (df,df.rename_axis("date"),df.reset_index(drop=True)):
            legacy=frame.copy()
            if not isinstance(legacy.index,pd.RangeIndex):legacy=legacy.reset_index(names=legacy.index.name or "timestamp")
            self.assertEqual(dataframe_to_csv_bytes(frame),legacy.to_csv(index=False).encode("utf-8-sig"))
    def test_direct_archive_matches_ordinary_export(self):
        df,ds=self.fixture()
        data,m,_=generate_atlas(ds,df,{},mode=PDF_MODES[2])
        with tempfile.TemporaryDirectory() as tmp:
            dest=Path(tmp)/"atlas.zip"
            direct,manifest,_=generate_atlas(ds,df,{},mode=PDF_MODES[2],output_path=dest)
            self.assertIsNone(direct)
            self.assertEqual(m,manifest)
            with zipfile.ZipFile(io.BytesIO(data)) as a,zipfile.ZipFile(dest) as b:
                self.assertEqual(a.namelist(),b.namelist())
                for name in a.namelist():
                    if name!="atlas_metadata.json":self.assertEqual(a.read(name),b.read(name))
    def test_real_worker_and_repeat_export(self):
        df,ds=self.fixture()
        for _ in range(2):
            data,manifest,metadata=iso.isolated_html_atlas(ds,df,{},timeout=120)
            self.assertEqual([r["id"] for r in manifest],[d.id for d in ds])
            self.assertEqual(metadata["counts"]["generated"],len(ds))
            self.assertEqual(metadata["execution_diagnostics"]["mode"],"isolated HTML worker")
            with zipfile.ZipFile(io.BytesIO(data)) as z:self.assertIsNone(z.testzip())
    def test_chart_exports_are_not_eager(self):
        import ast
        source=Path(__file__).resolve().parents[1]/"app.py"
        tree=ast.parse(source.read_text(encoding="utf-8"))
        fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=="render_chart_export_controls")
        branch=next(n for n in ast.walk(fn) if isinstance(n,ast.If) and isinstance(n.test,ast.Call)
                    and isinstance(n.test.func,ast.Attribute) and n.test.func.attr=="button")
        exports=[n for n in ast.walk(fn) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                 and n.func.id in ("figure_to_csv_bytes","dataframe_to_csv_bytes")]
        self.assertEqual(len(exports),2)
        self.assertTrue(all(any(n is child for child in ast.walk(branch)) for n in exports))
    def test_prepare_frame_does_not_mutate_source(self):
        df,_=self.fixture()
        df[c.G]=100.;df[c.D]=25.
        original=df.copy(deep=True)
        prepared=c.prepare_frame(df)
        pd.testing.assert_frame_equal(df,original)
        self.assertIn("diffuse_radiation_fraction_pct",prepared)
        self.assertTrue((prepared["diffuse_radiation_fraction_pct"]==25.).all())
    def test_rejects_launch_without_raw_memory(self):
        df,ds=self.fixture()
        with patch.object(iso,"container_memory",return_value=(2800*iso.MIB,3072*iso.MIB)),patch.object(iso.subprocess,"Popen") as launch:
            with self.assertRaises(MemoryError):iso.isolated_html_atlas(ds,df,{})
            launch.assert_not_called()
        self.assertTrue(iso.EXPORT_LOCK.acquire(blocking=False));iso.EXPORT_LOCK.release()

if __name__=="__main__":unittest.main()
