"""R5 startup, idle-page isolation and bounded diagnostic regressions."""
import unittest
from unittest.mock import patch
from collections import Counter,deque
from types import SimpleNamespace
from epw_climate_analyzer import startup_runtime as r
from epw_climate_analyzer import ui_contract as u

class StartupTests(unittest.TestCase):
    def test_one_time_preload_with_pressure_deferred_utci(self):
        stages=(("core",("ige_fixture_core",),None,768*r.MIB),
                ("optional",("ige_fixture_utci",),"utci",1536*r.MIB))
        sample={"process_rss":1,"used":2,"limit":3,"python_blocks":4}
        with patch.object(r,"_STAGES",{}),patch.object(r,"STAGES",stages),patch.object(r,"_sample",return_value=sample),patch.object(r,"container_memory",return_value=(1800*r.MIB,3072*r.MIB)),patch.object(r,"import_module") as load,patch.object(r,"_warmup") as warm:
            first=r.ensure_initialized()
            second=r.ensure_initialized()
            self.assertEqual(first,second)
            self.assertEqual([x["status"] for x in first],["ready","deferred (raw headroom)"])
            load.assert_called_once_with("ige_fixture_core")
            warm.assert_not_called()
            with patch.object(r,"container_memory",return_value=(1000*r.MIB,3072*r.MIB)):
                third=r.ensure_initialized()
            self.assertEqual(third[1]["status"],"ready")
            warm.assert_called_once_with("utci")
            self.assertEqual(load.call_count,2)
    def test_low_headroom_defers_new_core_import(self):
        with patch.object(r,"_STAGES",{}),patch.object(r,"STAGES",(("core",("ige_fixture_core",),None,768*r.MIB),)),patch.object(r,"_sample",return_value={}),patch.object(r,"container_memory",return_value=(2900*r.MIB,3072*r.MIB)),patch.object(r,"import_module") as load:
            self.assertEqual(r.ensure_initialized()[0]["status"],"deferred (raw headroom)")
            load.assert_not_called()
    def test_guard_identity_stable_when_source_unchanged(self):
        from epw_climate_analyzer import runtime_module_guard as guard
        with patch.object(r,"reload") as reload_guard:
            self.assertIs(r.current_runtime_guard(),guard)
            self.assertIs(r.current_runtime_guard(),guard)
            reload_guard.assert_not_called()

    def test_idle_upload_does_not_recompose_parity(self):
        # Emulate app caller globals without importing Streamlit's app script.
        namespace={name:object() for name in ("VARIABLES","load_epw_from_bytes","render_geosphere_source","render_canonical_climate_analysis","render_compare_climates","render_data_quality")}
        state={}
        namespace.update(apply_queued_navigation=u.apply_queued_navigation,state=state)
        with patch("epw_climate_analyzer.chart_presentation.install_global_chart_presentation"),patch("epw_climate_analyzer.source_parity_runtime.install_into_app_globals") as install,patch.object(r,"profile_install",side_effect=lambda fn,ns:fn(ns)):
            for _ in range(20):exec("apply_queued_navigation(state)",namespace)
            install.assert_not_called()
            state["active_climate_file"]=object()
            exec("apply_queued_navigation(state)",namespace)
            install.assert_called_once()
        self.assertTrue(u.needs_source_parity({"climate_source_mode":"GeoSphere Austria"}))
        self.assertTrue(u.needs_source_parity({"active_canonical_climate":object()}))
        self.assertFalse(u.needs_source_parity({"climate_source_mode":"Upload EPW"}))
    def test_runtime_ledger_bounded_and_weak(self):
        import gc
        with patch.object(r,"_EVENTS",deque(maxlen=64)),patch.object(r,"_SCRIPT_REFS",deque(maxlen=64)),patch.object(r,"_EVENT_COUNTS",Counter()),patch.object(r,"_sample",return_value={}):
            for _ in range(90):
                def app():pass
                token=r.begin_script(app)
                r.end_script(token,"Climate File Source")
                del app
            gc.collect()
            summary=r.runtime_summary()
            self.assertEqual(summary["event_counts"]["script rerun"],90)
            self.assertEqual(len(summary["recent_events"]),64)
            self.assertEqual(summary["recent_script_functions_still_alive"],0)
    def test_census_is_blocked_under_pressure(self):
        with patch.object(r,"container_memory",return_value=(2900*r.MIB,3072*r.MIB)),patch.object(r.gc,"get_objects") as scan:
            self.assertIn("blocked",r.heap_census()["status"])
            scan.assert_not_called()
    def test_census_handles_non_string_type_module(self):
        class AbsentModule:pass
        class NumericModule:pass
        class ArbitraryModule:pass
        AbsentModule.__module__=None
        NumericModule.__module__=123
        ArbitraryModule.__module__=object()
        objects=[AbsentModule(),NumericModule(),ArbitraryModule(),[]]
        with patch.object(r,"container_memory",return_value=None),patch.object(r,"_sample",return_value={}),patch.object(r.gc,"get_objects",side_effect=[objects,[],[]]):
            result=r.heap_census()
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["tracked_objects"],4)
        self.assertEqual(sum(row["count"] for row in result["types"] if row["type"].startswith("<unknown module>.")),3)

    def test_census_failure_does_not_interrupt_application(self):
        from epw_climate_analyzer import memory_lifecycle as lifecycle
        state={}
        with patch.object(r,"heap_census",side_effect=TypeError("private diagnostic")),patch.object(lifecycle,"inspect_resources",return_value={"ok":True}):
            result=lifecycle.inspect_heap(state)
        self.assertEqual(result,{"ok":True})
        self.assertEqual(state["_mem_r5_heap_census"],{"status":"failed: TypeError"})

    def test_census_async_generator_and_arbitrary_size_hooks_are_not_measured(self):
        import asyncio
        async def async_objects():
            yield 1
        generator=async_objects()
        class Dangerous:
            def __sizeof__(self):
                raise AssertionError("Arbitrary size hook must not execute")
        objects=[generator,Dangerous(),{},[],()]
        try:
            with patch.object(r,"container_memory",return_value=None),patch.object(r,"_sample",return_value={}),patch.object(r.gc,"get_objects",side_effect=[objects,[],[]]):
                report=r.heap_census()
            self.assertEqual(report["tracked_objects"],5)
            self.assertEqual(report["size_measured_objects"],3)
            self.assertEqual(report["size_unavailable_objects"],2)
            self.assertEqual(report["shallow_bytes"],sum(__import__("sys").getsizeof(o) for o in objects[2:]))
            async_row=next(row for row in report["types"] if row["type"]=="builtins.async_generator")
            self.assertIsNone(async_row["shallow_bytes"])
        finally:
            asyncio.run(generator.aclose())

    def test_census_rejects_impossible_size_even_for_supported_type(self):
        with patch.object(r.sys,"getsizeof",return_value=1119122127661464):
            self.assertIsNone(r._safe_census_size([],3072*r.MIB))

    def test_census_returns_counts_not_object_contents(self):
        with patch.object(r,"container_memory",return_value=None),patch.object(r,"_sample",return_value={}),patch.object(r.gc,"get_objects",side_effect=[[[],{"private_marker":"secret"}],[],[]]):
            report=r.heap_census()
            self.assertEqual(report["tracked_objects"],2)
            self.assertEqual(report["status"],"complete")
            self.assertNotIn("secret",str(report))

if __name__=="__main__":unittest.main()
