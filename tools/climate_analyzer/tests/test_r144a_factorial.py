"""Unit checks for factorial contrasts; no browser or server required."""
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location("r144a_factorial",Path(__file__).resolve().parents[1]/"scripts/r144a_factorial.py")
m=importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

class FactorialTests(unittest.TestCase):
    def test_effects_and_interaction(self):
        rows={k:{"rss":v} for k,v in zip(m.ARMS,[300,280,240,210])}
        e=m.effects(rows,"rss")
        self.assertEqual(e["runtime_default"],-20)
        self.assertEqual(e["runtime_arena2"],-30)
        self.assertEqual(e["allocator_baseline"],-60)
        self.assertEqual(e["allocator_persistent"],-70)
        self.assertEqual(e["interaction"],-10)
        self.assertEqual(e["combined_vs_reference"],-90)
        self.assertEqual(e["combined_percent"],-30)
    def test_missing_metric_not_imputed(self):
        rows={k:{"rss":v} for k,v in zip(m.ARMS,[300,None,240,210])}
        self.assertIsNone(m.effects(rows,"rss"))
    def test_factorial_design(self):
        self.assertEqual(set(m.ARMS.values()),{("0",None),("1",None),("0","2"),("1","2")})
        self.assertEqual(set(m.ORDER),set(m.ARMS))

if __name__=="__main__":unittest.main()
