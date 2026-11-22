"""R6 diagnostics: count-only session inspection and optional backends."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from epw_climate_analyzer import session_memory as m

class SessionMemoryTests(unittest.TestCase):
    def test_backend_payload_stats_are_aggregate_only(self):
        uploader=Mock()
        uploader.get_stats.return_value=[SimpleNamespace(byte_length=100,cache_name="private upload"),
                                         SimpleNamespace(byte_length=250,cache_name="another private upload")]
        store=Mock()
        store.get_stats.return_value={"cache_memory_bytes":[SimpleNamespace(byte_length=400,cache_name="private media")]}
        runtime=SimpleNamespace(_session_mgr=SimpleNamespace(num_active_sessions=lambda:3),
                                uploaded_file_mgr=uploader,media_file_mgr=SimpleNamespace(_storage=store))
        result=m._backend_stats(runtime)
        self.assertEqual(result,{"active_sessions":3,"uploaded_payload_bytes":350,"media_payload_bytes":400})
        self.assertNotIn("private",str(result))

    def test_missing_unsupported_backend_is_unavailable(self):
        self.assertEqual(m._backend_stats(object()),{"active_sessions":None,"uploaded_payload_bytes":None,"media_payload_bytes":None})
        provider=Mock();provider.get_stats.return_value=[SimpleNamespace(byte_length=-1)]
        self.assertIsNone(m._payload_total(provider))
        provider.get_stats.return_value=[SimpleNamespace(byte_length=1.5)]
        self.assertIsNone(m._payload_total(provider))
        provider.get_stats.side_effect=RuntimeError("not supported")
        self.assertIsNone(m._payload_total(provider))

    def test_current_state_counts_do_not_read_values_or_export_names(self):
        class CountOnly(dict):
            def __getitem__(self,key):raise AssertionError("content accessed")
            def get(self,key,*args):raise AssertionError("content accessed")
        state=CountOnly({"active_climate_file":object(),"secret dynamic name":object()})
        with patch("streamlit.runtime.Runtime.exists",return_value=False):
            result=m.inspect_session_counters(state,("active_climate_file","_p6_report_items"))
        self.assertEqual(result["visible_keys"],2)
        self.assertEqual(result["known_resource_keys_present"],1)
        self.assertNotIn("secret",str(result))
        self.assertIsNone(result["active_sessions"])

if __name__=="__main__":unittest.main()
