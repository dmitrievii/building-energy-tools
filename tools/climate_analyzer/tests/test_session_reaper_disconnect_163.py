"""MEM-PERF R14.5D HF1: Streamlit 1.63 websocket-disconnect compatibility."""
import threading
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import patch

from epw_climate_analyzer import session_reaper as r


class SessionReaperDisconnectRegression(unittest.TestCase):
    def _manager(self,session_id="current",context_id="current"):
        from streamlit.runtime.scriptrunner_utils.script_run_context_attr import (
            SCRIPT_RUN_CONTEXT_ATTR_NAME,
        )
        class Session:
            pass
        class Manager:
            def __init__(self):
                self.session=Session()
                self.session._scriptrunner=SimpleNamespace(_script_thread=thread)
                self.closed=[]
            def get_active_session_info(self,sid):
                if sid==session_id and self.session is not None:
                    return SimpleNamespace(session=self.session)
                return None
            def close_session(self,sid):
                self.closed.append(sid)
                self.session=None
        thread=threading.Thread(name="r145d-script-runner-fixture")
        ctx=SimpleNamespace(session_id=context_id)
        setattr(thread,SCRIPT_RUN_CONTEXT_ATTR_NAME,ctx)
        return Manager(),ctx

    def test_disconnect_closes_and_marks_only_matching_script_context(self):
        manager,ctx=self._manager()
        released=[]
        from epw_climate_analyzer import byte_cache
        with (patch.object(r,"_STATUS",{}),
              patch.object(r,"_CLOSED_REFS",[]),
              patch.object(r,"_RETIRED",[]),
              patch.object(r,"_STOPPING_THREADS",weakref.WeakSet()),
              patch.object(byte_cache,"close_session_caches",side_effect=released.append),
              patch("streamlit.runtime.scriptrunner.get_script_run_ctx",
                    side_effect=AssertionError("must not access event-loop thread context"))):
            r._install_disconnect_policy(manager)
            manager.disconnect_session("current")
            self.assertEqual(manager.closed,["current"])
            self.assertEqual(released,["current"])
            self.assertTrue(ctx._ige_session_closed)
            self.assertEqual(r.reaper_summary()["native_closes"],1)
            self.assertEqual(r.reaper_summary()["closed_on_disconnect"],1)

    def test_mismatched_context_does_not_get_annotated(self):
        manager,ctx=self._manager(context_id="unrelated")
        from epw_climate_analyzer import byte_cache
        with (patch.object(r,"_STATUS",{}),
              patch.object(r,"_CLOSED_REFS",[]),
              patch.object(r,"_RETIRED",[]),
              patch.object(r,"_STOPPING_THREADS",weakref.WeakSet()),
              patch.object(byte_cache,"close_session_caches")):
            r._install_disconnect_policy(manager)
            manager.disconnect_session("current")
        self.assertEqual(manager.closed,["current"])
        self.assertFalse(hasattr(ctx,"_ige_session_closed"))

    def test_replaces_faulty_cached_policy_without_stacking(self):
        # A Community Cloud hot code reload can preserve a manager's old
        # instance-bound closure even when the source file changes.
        manager,ctx=self._manager()
        from epw_climate_analyzer import byte_cache
        def stale_close(sid):
            raise TypeError("get_script_run_ctx() got multiple values for argument 'suppress_warning'")
        stale_close._ige_policy_version="r13-hf2"
        def stale_disconnect(sid):
            return stale_close(sid)
        stale_disconnect._ige_policy_version="r13-hf2"
        manager.close_session=stale_close
        manager.disconnect_session=stale_disconnect
        manager._ige_policy_version="r13-hf2"
        manager._ige_r12_hf1_close=True
        with (patch.object(r,"_STATUS",{}),
              patch.object(r,"_CLOSED_REFS",[]),
              patch.object(r,"_RETIRED",[]),
              patch.object(r,"_STOPPING_THREADS",weakref.WeakSet()),
              patch.object(byte_cache,"close_session_caches")):
            r._install_disconnect_policy(manager)
            self.assertEqual(manager._ige_policy_version,r._POLICY_VERSION)
            self.assertIsNot(manager.close_session,stale_close)
            manager.disconnect_session("current")
            self.assertEqual(manager.closed,["current"])
            self.assertTrue(ctx._ige_session_closed)
            self.assertEqual(r.reaper_summary()["policy_replacements"],1)

    def test_upstream_163_getter_no_thread_parameter(self):
        import inspect
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        params=list(inspect.signature(get_script_run_ctx).parameters)
        self.assertEqual(params,["suppress_warning"])


if __name__=="__main__":
    unittest.main()
