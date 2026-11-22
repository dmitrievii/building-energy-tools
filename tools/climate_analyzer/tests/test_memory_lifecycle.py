"""MEM-PERF R1 ownership and pressure-policy regressions."""
import unittest
from unittest.mock import Mock,patch
from epw_climate_analyzer import memory_lifecycle as m

class MemoryLifecycleTests(unittest.TestCase):
    def test_memory_stat_key_value_parsing(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"memory.stat").write_text(
                "anon 1210560512\nfile 700000000\nshmem 0\ninactive_file 600000000\ninvalid xyz\nmalformed\n",
                encoding="utf-8")
            with patch.object(m.m,"_memory_reading",return_value=(2841534464,3221225472,root)):
                sample=m.memory_snapshot()
            self.assertEqual(sample["anonymous"],1210560512)
            self.assertEqual(sample["file"],700000000)
            self.assertEqual(sample["inactive_file"],600000000)
            self.assertEqual(sample["shared"],0)

    def test_cleanup_preserves_user_work(self):
        protected={key:object() for key in ("active_climate_file","active_canonical_climate",
            "_p6_report_items","comparison_climate_payloads","ige_engine_completed_product",
            "_p6_custom_presets","p4_duration_curve_percentages")}
        disk=Mock()
        state={**protected,**{key:object() for key in m.EXPORT_KEYS+m.DERIVED_KEYS+m.TRANSIENT_KEYS},
               m.DISK_KEY:disk}
        samples=[{"used":3000,"limit":3072},{"used":2400,"limit":3072}]
        with patch.object(m,"memory_snapshot",side_effect=samples),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            result=m.manual_cleanup(state)
        for key,value in protected.items():self.assertIs(state[key],value)
        for key in m.EXPORT_KEYS+m.DERIVED_KEYS+m.TRANSIENT_KEYS+(m.DISK_KEY,):
            self.assertNotIn(key,state)
        disk.cleanup.assert_called_once()
        self.assertEqual(result["before"]["used"],3000)
        self.assertEqual(result["after"]["used"],2400)

    def test_export_cleanup_preserves_active_frame_and_new_download(self):
        frame=object();saved=object();disk=Mock()
        state={"_active_filtered_export_df":frame,"_p6_report_items":saved,
               "_p6_pdf":b"old","_utci_perf_r1_result":object(),m.DISK_KEY:disk}
        with patch.object(m,"memory_snapshot",return_value={"used":100,"limit":1000}),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            m.prepare_export(state)
            self.assertNotIn("_p6_pdf",state)
            self.assertNotIn("_utci_perf_r1_result",state)
            self.assertIs(state["_active_filtered_export_df"],frame)
            self.assertIs(state["_p6_report_items"],saved)
            disk.cleanup.assert_not_called()
            state["_p66_atlas_result"]=b"new"
            m.finish_export(state)
            self.assertEqual(state["_p66_atlas_result"],b"new")
            self.assertEqual(state[m.EXPORT_PRE_KEY]["reason"],"Before export")
            self.assertEqual(state[m.EXPORT_POST_KEY]["reason"],"After export")

    def test_pressure_cooldown_and_page_transition(self):
        disk=Mock()
        state={m.PAGE_KEY:"old","_active_filtered_export_df":object(),
               "_p6_pdf":b"ready","_utci_perf_r1_result":object(),m.DISK_KEY:disk}
        with patch.object(m,"memory_snapshot",return_value={"used":950,"limit":1000}),patch.object(m,"monotonic",return_value=100.),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            m.begin_rerun(state,"new")
            self.assertNotIn("_active_filtered_export_df",state)
            self.assertNotIn("_utci_perf_r1_result",state)
            self.assertEqual(state["_p6_pdf"],b"ready")
            state["_utci_perf_r1_result"]=object()
            m.begin_rerun(state,"new")
            self.assertIn("_utci_perf_r1_result",state)
        disk.cleanup.assert_called_once()
        self.assertFalse(m.pressure_high({"used":900,"limit":1000,"file":300,"inactive_file":300}))
        self.assertTrue(m.pressure_high({"used":900,"limit":1000,"file":300,"inactive_file":300,"shared":300}))

    def test_disk_cache_not_removed_during_export(self):
        disk=Mock();state={m.DISK_KEY:disk}
        with patch.object(m,"memory_snapshot",return_value={}),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            self.assertTrue(m.m.EXPORT_LOCK.acquire(blocking=False))
            try:result=m.manual_cleanup(state)
            finally:m.m.EXPORT_LOCK.release()
        self.assertIs(state[m.DISK_KEY],disk)
        disk.cleanup.assert_not_called()
        self.assertTrue(result["warnings"])

if __name__=="__main__":unittest.main()
