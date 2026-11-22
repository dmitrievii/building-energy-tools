import gc
import unittest
from unittest.mock import patch
from epw_climate_analyzer import epw_lifecycle as e,process_memory as p
from collections import deque,Counter

class HF1Tests(unittest.TestCase):
    def test_weak_epw_tracking_never_owns_frame(self):
        class Frame:pass
        with patch.object(e,"_REFS",deque(maxlen=128)),patch.object(e,"_COUNTS",Counter()):
            obj=Frame()
            e.track("frame",obj);e.track("frame",obj)
            self.assertEqual(e.lifecycle_summary()["alive"],{"frame":1})
            del obj;gc.collect()
            self.assertEqual(e.lifecycle_summary()["alive"],{})
    def test_process_inventory_unavailable_without_finite_cgroup(self):
        with patch.object(p,"_memory_reading",return_value=None):
            self.assertIn("unavailable",p.container_process_inventory()["status"])
    def test_process_category_is_not_raw_command(self):
        self.assertEqual(p._category("python3"),"Python")
        self.assertEqual(p._category("chrome"),"Browser/renderer")
        self.assertEqual(p._category("private-command"),"Other")

    def test_classify_process_relationships(self):
        rows=[{"pid":2,"parent_pid":1,"app":False},{"pid":3,"parent_pid":2,"app":True},
              {"pid":4,"parent_pid":2,"app":False},{"pid":5,"parent_pid":3,"app":False}]
        p._relationships(rows)
        self.assertEqual([r["relation_to_app"] for r in rows],["ancestor","self","sibling","descendant"])

    def test_allowlisted_launch_identity(self):
        from pathlib import Path
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as directory:
            base=Path(directory)
            app=base/"app.py"
            app.touch()
            (base/"cmdline").write_bytes(b"python\x00-m\x00streamlit\x00run\x00"+str(app).encode()+b"\x00secret-argument\x00")
            result=p._identity(base,10.,app)
            self.assertEqual(result["role_hint"],"climate-analyzer-launcher")
            self.assertTrue(result["climate_app_target"])
            self.assertNotIn("secret-argument",str(result))

    def test_replace_legacy_instance_hook_without_stacking(self):
        from epw_climate_analyzer import session_reaper as reaper
        class Manager:
            def __init__(self):
                self._ige_r12_hf1_close=True
                self.close_session=lambda sid:(_ for _ in ()).throw(AssertionError("stale hook"))
                self.disconnect_session=lambda sid:None
                self.closed=[]
            def get_active_session_info(self,sid):return None
            def close_session(self,sid):self.closed.append(sid)
        manager=Manager()
        with patch.object(reaper,"_STATUS",{}):
            reaper._install_disconnect_policy(manager)
            current=manager.close_session
            reaper._install_disconnect_policy(manager)
            self.assertIs(current,manager.close_session)
            manager.close_session("test")
            self.assertEqual(manager.closed,["test"])
            self.assertEqual(reaper.reaper_summary()["policy_replacements"],1)
            self.assertTrue(reaper.reaper_summary()["policy_verified"])
