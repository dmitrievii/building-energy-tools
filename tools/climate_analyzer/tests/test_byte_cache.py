"""MEM-PERF R4: bounded retention, independent data hits and safe eviction."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from epw_climate_analyzer import byte_cache as b
from epw_climate_analyzer import memory_lifecycle as m

class ByteCacheTests(unittest.TestCase):
    def test_lru_and_oversized_admission(self):
        cache=b.ByteLRU("fixture",1600,8)
        for i in range(12):cache.put(i,np.arange(64,dtype=float))
        self.assertLessEqual(cache.info()["estimated_bytes"],1600)
        self.assertGreater(cache.info()["evictions"],0)
        self.assertIs(cache.get(0),b.MISS)
        self.assertIsNot(cache.get(11),b.MISS)
        self.assertFalse(cache.put("large",np.zeros(10000)))
        self.assertEqual(cache.info()["not_retained"],1)
        generation=cache.generation
        cache.clear()
        self.assertFalse(cache.put("late",np.array([1]),generation=generation))
    def test_data_cache_exact_keys_and_independent_outputs(self):
        calls=[]
        @b.bounded_cache(name="r4_test_data",max_bytes=100000,max_entries=2)
        def build(x,_ignored=None):
            calls.append(x)
            return pd.DataFrame({"a":[x]})
        first=build(1);first.iloc[0,0]=999
        second=build(x=1,_ignored="not a key")
        self.assertEqual(second.iloc[0,0],1)
        self.assertEqual(calls,[1])
        build(2);build(3);build(1)
        self.assertEqual(calls,[1,2,3,1])
        build.clear()
    def test_ttl_and_resource_reference_survives_eviction(self):
        cache=b.ByteLRU("ttl",10000,2,ttl=2)
        v=np.arange(10)
        with patch.object(b,"monotonic",return_value=10.):cache.put("x",v)
        with patch.object(b,"monotonic",return_value=13.):self.assertIs(cache.get("x"),b.MISS)
        np.testing.assert_array_equal(v,np.arange(10))
    def test_shared_eviction_protects_active_data(self):
        cache=b.pool("r4_test_shared",10000,2)
        frame=pd.DataFrame({"a":[1.,2.]})
        cache.put("x",frame)
        state={"active_canonical_climate":frame,"_p6_report_items":[{"figure":"data"}]}
        sample={"used":2402*b.MIB,"limit":3072*b.MIB}
        with patch.object(m,"memory_snapshot",return_value=sample),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            result=m.prepare_export(state)
        self.assertTrue(any(r["cache"]=="r4_test_shared" for r in result["evicted_caches"]))
        self.assertIs(state["active_canonical_climate"],frame)
        self.assertEqual(state["_p6_report_items"][0]["figure"],"data")
        self.assertIs(cache.get("x"),b.MISS)
        self.assertTrue(m.cache_pressure(sample))
    def test_inventory_unknown_objects(self):
        rows=b.session_inventory({"known":b"payload","unknown":object()},("known","unknown"))
        self.assertGreater(rows[0]["estimated_bytes"],0)
        self.assertIsNone(rows[1]["estimated_bytes"])
    def test_registered_application_budget(self):
        import ast
        from pathlib import Path
        source=(Path(__file__).resolve().parents[1]/"app.py").read_text(encoding="utf-8")
        tree=ast.parse(source)
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=="bounded_cache"]
        self.assertEqual(len(calls),9)
        budget=sum(int(next(k.value.left.value for k in n.keywords if k.arg=="max_bytes")) for n in calls)
        self.assertEqual(budget,121)
        self.assertNotIn("@st.cache_data",source)
        self.assertNotIn("@st.cache_resource",source)
    def test_ten_repeated_cleanup_cycles_have_bounded_retention(self):
        cache=b.pool("r4_test_repeat",1600,3)
        state={"active_climate_file":b"untouched"}
        sample={"used":2402*b.MIB,"limit":3072*b.MIB}
        with patch.object(m,"memory_snapshot",return_value=sample),patch.object(m.gc,"collect"),patch.object(m.m,"_trim_allocator"):
            for i in range(10):
                cache.put(i,np.zeros(64))
                state["_p66_atlas_result"]=b"previous"
                m.prepare_export(state)
                self.assertEqual(cache.info()["estimated_bytes"],0)
                self.assertNotIn("_p66_atlas_result",state)
                self.assertEqual(state["active_climate_file"],b"untouched")
        cache.clear()
    def test_combined_filter_preserves_values_and_source(self):
        from epw_climate_analyzer.aggregations import filter_by_months_and_hours
        idx=pd.date_range("2025-01-31",periods=48,freq="h")
        df=pd.DataFrame({"month_index":idx.month,"hour_of_day":idx.hour,"value":np.arange(48)},index=idx)
        df.attrs["fixture"]="yes"
        for months,hours in (([],[]),([1],[0,1]),([2],[]),([1,2],list(range(24))),([12],[1])):
            expected=df.copy()
            if months:expected=expected[expected.month_index.isin(months)]
            if hours:expected=expected[expected.hour_of_day.isin(hours)]
            actual=filter_by_months_and_hours(df,months,hours)
            pd.testing.assert_frame_equal(actual,expected)
            if len(actual):
                actual.iloc[0,-1]=-99
                self.assertTrue((df.value>=0).all())

if __name__=="__main__":unittest.main()
