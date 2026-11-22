"""MEM-PERF R1 ownership and pressure-policy regressions."""
import unittest
from unittest.mock import Mock,patch
from epw_climate_analyzer import memory_lifecycle as m

class MemoryLifecycleTests(unittest.TestCase):
    def test_inventory_refresh_has_timestamp_and_preserves_separate_heap(self):
        state={"_mem_r5_heap_census":{"status":"complete"},"_mem_r5_heap_census_at":"earlier"}
        from epw_climate_analyzer import startup_runtime as runtime
        with patch.object(runtime,"_sample",side_effect=[{"used":100}]*4+[{"used":200}]*4):
            first=m.inspect_resources(state)
            second=m.inspect_resources(state)
        self.assertEqual(first["snapshot_schema"],"MEM-PERF-R12")
        self.assertIn("captured_at_utc",first)
        self.assertEqual(first["memory"]["used"],100)
        self.assertEqual(second["memory"]["used"],200)
        self.assertIs(state[m.INVENTORY_KEY],second)
        self.assertEqual(second["heap_census_captured_at_utc"],"earlier")
        import json
        self.assertEqual(json.loads(state[m.INVENTORY_BYTES_KEY])["memory"]["used"],200)
        self.assertEqual(second["diagnostic_capture"]["event"],"inventory capture callback")

    def test_sidebar_reuses_inventory_payload_and_does_not_build_tables(self):
        import json
        from types import SimpleNamespace
        from epw_climate_analyzer import startup_runtime as runtime
        snapshot={"snapshot_schema":"MEM-PERF-R12","captured_at_utc":"2026-11-22T15:00:00+00:00",
                  "shared_caches":[],"session_resources":[],"python_allocated_blocks":10}
        payload=json.dumps(snapshot).encode()
        state={m.INVENTORY_KEY:snapshot,m.INVENTORY_BYTES_KEY:payload}
        from unittest.mock import MagicMock
        ui=MagicMock()
        ui.session_state=state
        ui.checkbox.return_value=True
        status={"startup":[],"event_counts":{},"persistent_runtime":{}}
        with patch.object(m,"memory_snapshot",return_value={}),patch.object(runtime,"runtime_status",return_value=status),patch.object(m.json,"dumps",side_effect=AssertionError("unexpected serialization")):
            for _ in range(20):m._render_sidebar(ui)
        self.assertEqual(ui.download_button.call_count,20)
        self.assertTrue(all(call.kwargs["data"] is payload for call in ui.download_button.call_args_list))
        ui.dataframe.assert_not_called()
        ui.json.assert_not_called()

    def test_manual_cleanup_releases_diagnostic_downloads(self):
        state={key:object() for key in m.DIAGNOSTIC_KEYS}
        report=object()
        state["_p6_report_items"]=report
        with patch.object(m,"memory_snapshot",return_value={}),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            m.manual_cleanup(state)
        self.assertTrue(all(key not in state for key in m.DIAGNOSTIC_KEYS))
        self.assertIs(state["_p6_report_items"],report)

    def test_recovery_probe_separates_gc_and_trim_without_clearing_state(self):
        from epw_climate_analyzer import memory_recovery as recovery
        samples=[{"process_anon":300},{"process_anon":280},{"process_anon":250}]
        with patch.object(m,"memory_snapshot",side_effect=samples),patch.object(recovery,"allocator_snapshot",return_value={"status":"unavailable"}),patch.object(recovery.gc,"collect",return_value=7),patch.object(m.m,"_trim_allocator",return_value=True),patch.object(recovery,"_LAST",None),patch.object(recovery,"_COUNT",0):
            result=recovery.recovery_probe("test")
            self.assertEqual(result["status"],"complete")
            self.assertEqual(result["collected_objects"],7)
            self.assertEqual(result["before"]["process_anon"],300)
            self.assertEqual(result["after_gc"]["process_anon"],280)
            self.assertEqual(result["after_trim"]["process_anon"],250)
            self.assertTrue(result["trim_reported_release"])
        self.assertTrue(m.m.EXPORT_LOCK.acquire(blocking=False))
        try:
            self.assertEqual(recovery.recovery_probe("busy")["status"],"busy export")
        finally:m.m.EXPORT_LOCK.release()

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
