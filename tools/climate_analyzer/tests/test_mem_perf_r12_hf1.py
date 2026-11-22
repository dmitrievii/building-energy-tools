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
