"""R7 page ownership and disconnected TTL contracts."""
import gc
import unittest
import weakref
from types import SimpleNamespace
from unittest.mock import Mock,patch
import plotly.graph_objects as go
from epw_climate_analyzer import chart_lifecycle as c,p6_report as r,session_reaper as reaper

class ChartLifecycleTests(unittest.TestCase):
    def test_callback_has_only_lightweight_identifiers_and_saves_exact_figure(self):
        state={r.CONTEXT_KEY:{"page":"Temperature"}}
        ui=SimpleNamespace(session_state=state,button=Mock(),caption=Mock(),success=Mock(),warning=Mock())
        token=c.begin_page(state)
        fig=go.Figure(go.Scatter(y=[1,2]))
        r.capture_control(ui,fig,1)
        kw=ui.button.call_args.kwargs
        self.assertEqual(kw["args"],("p6_capture_Temperature_1",token))
        self.assertIs(kw["on_click"],r.save_chart_by_token)
        with patch.object(r.st,"session_state",state):kw["on_click"](*kw["args"])
        self.assertEqual(len(state[r.REPORT_KEY]),1)
        ref=weakref.ref(fig);del fig
        c.begin_page(state);gc.collect()
        self.assertIsNone(ref())
        self.assertEqual(len(state[r.REPORT_KEY]),1)
        with patch.object(r.st,"session_state",state):kw["on_click"](*kw["args"])
        self.assertEqual(len(state[r.REPORT_KEY]),1)

    def test_repeated_navigation_releases_unsaved_figures(self):
        state={}
        refs=[]
        for i in range(50):
            c.begin_page(state)
            fig=go.Figure(go.Scatter(y=[i]))
            refs.append(weakref.ref(fig))
            c.register_figure(state,fig,{},"","same")
            del fig
        c.release_page(state);gc.collect()
        self.assertTrue(all(ref() is None for ref in refs))
        self.assertNotIn(c.DISPLAYED,state)

    def test_repeat_slot_replaces_and_sessions_are_independent(self):
        a,b={},{}
        c.begin_page(a);c.begin_page(b)
        old=go.Figure();ref=weakref.ref(old)
        c.register_figure(a,old,{},"","slot")
        del old
        c.register_figure(a,go.Figure(),{},"","slot")
        c.register_figure(b,go.Figure(),{},"","slot")
        gc.collect()
        self.assertIsNone(ref())
        self.assertEqual(len(a[c.DISPLAYED]),1)
        c.release_page(a)
        self.assertEqual(len(b[c.DISPLAYED]),1)

    def test_forward_queue_sampling_is_bounded_and_read_only(self):
        from streamlit.runtime.forward_msg_queue import ForwardMsgQueue
        from streamlit.proto.ForwardMsg_pb2 import ForwardMsg
        queue=ForwardMsgQueue()
        for _ in range(150):
            msg=ForwardMsg()
            msg.script_finished=ForwardMsg.FINISHED_SUCCESSFULLY
            queue.enqueue(msg)
        manager=SimpleNamespace(list_active_sessions=lambda:[SimpleNamespace(
            session=SimpleNamespace(_browser_queue=queue))])
        sample=reaper._queue_sample(manager)
        self.assertEqual(sample["status"],"sampled")
        self.assertEqual(sample["pending_messages_in_sampled_sessions"],150)
        self.assertEqual(sample["messages_sized"],128)
        self.assertTrue(sample["limited"])
        self.assertEqual(len(queue),150)
        self.assertEqual(sample["sampled_wire_bytes"],sum(msg.ByteSize() for msg in queue._queue[:128]))

    def test_post_session_recovery_waits_for_idle_next_sweep(self):
        from epw_climate_analyzer import memory_recovery
        session=SimpleNamespace(_scriptrunner=object(),_browser_queue=Mock())
        session._browser_queue.is_empty.return_value=True
        manager=SimpleNamespace(list_active_sessions=lambda:[SimpleNamespace(session=session)])
        with patch.object(reaper,"_RECOVERY_PENDING",False),patch.object(reaper,"_STATUS",{}),patch.object(memory_recovery,"recovery_probe",return_value={"status":"complete"}) as probe:
            reaper._recover_if_idle(manager,{},1)
            probe.assert_not_called()
            reaper._recover_if_idle(manager,{},0)
            probe.assert_not_called()
            session._scriptrunner=None
            reaper._recover_if_idle(manager,{"valid":object()},0)
            probe.assert_not_called()
            reaper._recover_if_idle(manager,{},0)
            probe.assert_called_once()
            reaper._recover_if_idle(manager,{},0)
            probe.assert_called_once()

    def test_native_ttl_reaps_only_expired_disconnected_entries(self):
        from streamlit.runtime.caching.ttl_cache import TTLCache
        now=[0.]
        cache=TTLCache(maxsize=8,ttl=120,timer=lambda:now[0])
        old,valid,active=Mock(),Mock(),Mock()
        cache["old"]=SimpleNamespace(session=old)
        cache["active"]=SimpleNamespace(session=active)
        now[0]=100.;cache["valid"]=SimpleNamespace(session=valid)
        manager=Mock();manager.is_active_session.side_effect=lambda key:key=="active"
        now[0]=121.
        with patch.object(reaper,"_STATUS",{"expired_reaped":0,"shutdown_failures":0,"sweeps":0}):
            reaper._expire_storage(manager,cache)
            self.assertEqual(reaper.reaper_summary()["expired_reaped"],1)
            self.assertEqual(reaper.reaper_summary()["disconnected_sessions"],1)
        old.shutdown.assert_called_once()
        valid.shutdown.assert_not_called()
        active.shutdown.assert_not_called()
        self.assertIn("valid",cache)

if __name__=="__main__":unittest.main()
