"""Memory Management compact UI: no change to inventory or reset semantics."""
import unittest
from unittest.mock import MagicMock,patch
from epw_climate_analyzer import memory_lifecycle as m

class CompactSidebarTests(unittest.TestCase):
    def _ui(self,advanced):
        ui=MagicMock()
        ui.session_state={
            m.INVENTORY_KEY:{"snapshot_schema":m.RUNTIME_INVENTORY_SCHEMA,
                             "captured_at_utc":"2026-11-23T12:00:00+00:00",
                             "cloud_memory_ownership":{"processes":{"other_matching_targets":[]}}},
            m.INVENTORY_BYTES_KEY:b"inventory-payload"}
        ui.checkbox.side_effect=lambda *a,**kw:advanced if kw.get("key")=="mem_r6_detail_tables" else False
        return ui

    def test_default_panel_is_compact_and_download_is_exact(self):
        ui=self._ui(False)
        with patch.object(m,"memory_snapshot",return_value={"used":100,"limit":1000,"process_anon":50}):
            m._render_sidebar(ui)
        captions="\n".join(str(x.args[0]) for x in ui.caption.call_args_list)
        self.assertIn("App RAM:",captions)
        self.assertIn("Snapshot captured:",captions)
        self.assertNotIn("Allocator admission:",captions)
        self.assertNotIn("Library stages:",captions)
        self.assertEqual(ui.download_button.call_count,1)
        self.assertIs(ui.download_button.call_args.kwargs["data"],ui.session_state[m.INVENTORY_BYTES_KEY])
        keys={x.kwargs.get("key") for x in ui.button.call_args_list}
        self.assertTrue({"mem_perf_r1_clean","mem_r12_reset","mem_r4_inspect","mem_r10_release_inventory"}<=keys)
        self.assertFalse({"mem_r9_recovery","mem_r5_heap_inspect"}&keys)
        reset=[x for x in ui.button.call_args_list if x.kwargs.get("key")=="mem_r12_reset"]
        self.assertTrue(reset[0].kwargs["disabled"])

    def test_diagnostics_require_explicit_opt_in(self):
        ui=self._ui(True)
        with patch.object(m,"memory_snapshot",return_value={}),patch.object(m,"cache_inventory",return_value=[]),patch.object(m,"session_cache_inventory",return_value=[]):
            m._render_sidebar(ui)
        keys={x.kwargs.get("key") for x in ui.button.call_args_list}
        self.assertIn("mem_r9_recovery",keys)
        self.assertIn("mem_r5_heap_inspect",keys)
        self.assertEqual(ui.download_button.call_count,1)
