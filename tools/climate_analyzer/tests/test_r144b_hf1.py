import unittest
import threading
from unittest.mock import patch,Mock
from epw_climate_analyzer import source_parity_runtime as runtime,session_reaper as reaper
from epw_climate_analyzer.memory_recovery import _arena_origin

class HF1Tests(unittest.TestCase):
    def test_idle_compatibility_release_never_waits_on_other_thread(self):
        locked=threading.Event();done=threading.Event()
        def hold():
            with runtime._RUNTIME_PATCH_LOCK:
                locked.set();done.wait(5)
        thread=threading.Thread(target=hold);thread.start()
        try:
            self.assertTrue(locked.wait(2))
            self.assertIs(runtime.release_idle_bindings(),False)
            self.assertFalse(done.is_set())
        finally:
            done.set();thread.join(2)

    def test_reaper_leaves_recovery_pending_on_deferral(self):
        manager=Mock();manager.list_active_sessions.return_value=[]
        with patch.object(reaper,"_RECOVERY_PENDING",True),patch.object(reaper,"_RETIRED",[]),patch.object(reaper,"_idle_for_recovery",return_value=True),patch.object(runtime,"release_idle_bindings",return_value=False),patch("epw_climate_analyzer.memory_recovery.recovery_probe") as recovery:
            reaper._recover_if_idle(manager,[],0)
            recovery.assert_not_called()
            self.assertTrue(reaper._RECOVERY_PENDING)

    def test_allocator_late_environment_not_startup(self):
        state=_arena_origin(b"UNRELATED_SECRET=private\0",2)
        self.assertIsNone(state["arena_max_exec_env"])
        self.assertIn("NOT established",state["arena_setting_origin"])
        self.assertNotIn("private",str(state))
    def test_exec_setting_and_tunable_reported_separately(self):
        state=_arena_origin(b"MALLOC_ARENA_MAX=2\0GLIBC_TUNABLES=glibc.malloc.arena_max=4:other=secret\0",2)
        self.assertEqual(state["arena_max_exec_env"],2)
        self.assertEqual(state["arena_tunable_exec"],4)
        self.assertNotIn("secret",str(state))
    def test_unavailable_exec_evidence_not_inferred(self):
        self.assertIsNone(_arena_origin(None,2)["arena_max_exec_env"])
