"""P6.7 isolation, cache, recycling, failure and cleanup contracts."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import plotly.graph_objects as go
from epw_climate_analyzer import p6_static_render as r

class RenderTests(unittest.TestCase):
    def fixture(self,value=1):
        return go.Figure(go.Scatter(x=[1,2],y=[value,2])).update_layout(width=300,height=200)
    def fake(self,fig,target,**kwargs):
        Image.new("RGB",(300,200),(10,20,30)).save(target)
        return target

    def test_cache_reuse_invalidation_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r,"render_disposable",side_effect=self.fake) as cold:
            path=Path(tmp);cache=path/"cache";out=path/"out.png"
            with r.render_session(mode="disposable",cache_dir=cache) as a:
                r.render_png(self.fixture(),out)
                self.assertEqual(a.renders,1)
            with r.render_session(mode="disposable",cache_dir=cache) as b:
                r.render_png(self.fixture(),out)
                self.assertEqual(b.hits,1)
                r.render_png(self.fixture(3),out)
                r.render_png(self.fixture(),out,scale=2)
                self.assertEqual(b.renders,2)
            for p in cache.glob("*.png"):p.write_bytes(b"corrupt")
            with r.render_session(mode="disposable",cache_dir=cache) as c:
                r.render_png(self.fixture(),out)
                self.assertEqual(c.hits,0)
            self.assertEqual(cold.call_count,4)
            self.assertIsNone(r._ACTIVE.get())

    def test_cache_limits_and_distinct_session_owners(self):
        state1={};state2={}
        try:
            a=r.session_cache_dir(state1);b=r.session_cache_dir(state2)
            self.assertNotEqual(a,b)
            self.assertEqual(a,r.session_cache_dir(state1))
            with tempfile.TemporaryDirectory() as tmp, patch.object(r,"_CACHE_ITEMS",2), patch.object(r,"render_disposable",side_effect=self.fake):
                with r.render_session(mode="disposable",cache_dir=a):
                    for i in range(4):r.render_png(self.fixture(i),Path(tmp)/"out.png")
                self.assertEqual(len(list(a.glob("*.png"))),2)
                self.assertEqual(list(b.glob("*.png")),[])
        finally:
            for state in (state1,state2):
                if "_p67_render_cache" in state:state["_p67_render_cache"].cleanup()

    def test_memory_recycling_policy(self):
        from unittest.mock import Mock
        if os.name!="posix":self.skipTest("POSIX policy")
        with patch.object(r,"container_memory",return_value=(800*r.MIB,3072*r.MIB)):
            session=r.RenderSession(max_jobs=8)
            self.assertTrue(session.reusable())
            with patch.object(r,"container_memory",return_value=(2400*r.MIB,3072*r.MIB)):
                self.assertFalse(session.reusable())
            with patch.object(r,"container_memory",return_value=None):
                self.assertFalse(session.reusable())
            session.proc=Mock();session.proc.poll.return_value=None
            session.jobs=8
            self.assertFalse(session.reusable())
            session.jobs=2;session.warm_used=600*r.MIB
            self.assertFalse(session.reusable())

    @unittest.skipUnless(os.name=="posix","persistent worker requires POSIX")
    def test_real_worker_reuse_and_cleanup(self):
        # Force the policy fixture only; the actual guard still monitors memory.
        with tempfile.TemporaryDirectory() as tmp, patch.object(r,"container_memory",return_value=(800*r.MIB,3072*r.MIB)):
            with r.render_session(max_jobs=3,mode="adaptive") as s:
                for i in range(2):
                    p=Path(tmp)/f"{i}.png";r.render_png(self.fixture(i),p)
                    self.assertTrue(r._valid_png(p))
                self.assertEqual(s.starts,1)
                self.assertEqual(s.fallbacks,0)
                proc=s.proc
                self.assertIsNotNone(proc)
            self.assertIsNotNone(proc.poll())

    @unittest.skipUnless(os.name=="posix","persistent worker requires POSIX")
    def test_fallback_and_memory_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(r,"container_memory",return_value=(800*r.MIB,3072*r.MIB)), patch.object(r,"render_disposable",side_effect=self.fake) as cold:
            target=Path(tmp)/"out.png"
            with r.render_session(mode="adaptive") as s:
                with patch.object(s,"_persistent",side_effect=RuntimeError("fixture crash")):
                    r.render_png(self.fixture(),target)
                self.assertEqual(s.fallbacks,1)
                self.assertEqual(cold.call_count,1)
                with patch.object(s,"_persistent",side_effect=MemoryError("fixture pressure")):
                    with self.assertRaises(MemoryError):r.render_png(self.fixture(),target)
                self.assertFalse(target.exists())
                self.assertEqual(cold.call_count,1)

if __name__=="__main__":unittest.main()
