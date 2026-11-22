"""MEM-PERF R3: exclusive timing, bounded reuse and unchanged UTCI physics."""
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from epw_climate_analyzer import atlas_profile as ap
from epw_climate_analyzer import p3_comfort as p
from epw_climate_analyzer import p66_catalogue as c
from epw_climate_analyzer.p66_export import generate_atlas,PDF_MODES
from epw_climate_analyzer.p66_render import make_figure

class AtlasProfilingTests(unittest.TestCase):
    def fixture(self):
        idx=pd.date_range("2025-06-01",periods=96,freq="h")
        night=idx.hour<6
        df=pd.DataFrame({p.T:20.,p.RH:50.,p.V:1.,p.GHI:np.where(night,0.,400.),
                         p.DHI:np.where(night,0.,100.),p.DNI:np.where(night,0.,600.),
                         p.LW:350.,p.ZEN:np.where(night,110.,45.)},index=idx)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df
    def test_exclusive_nested_timing(self):
        now=[0.]
        prof=ap.AtlasProfiler(clock=lambda:now[0])
        d=c.Diagram("x","Temperature","Fixture","profile",c.T,"°C",(),"available","")
        with prof.activate():
            prof.begin_diagram(d)
            with ap.phase("outer"):
                now[0]+=2.
                with ap.phase("inner"):now[0]+=3.
                now[0]+=1.
            now[0]+=1.
            prof.end_diagram("generated")
        result=prof.summary()
        self.assertEqual(result["exclusive_phase_seconds"],{"outer":3.,"inner":3.})
        self.assertEqual(result["wall_seconds"],7.)
        self.assertEqual(result["unattributed_seconds"],1.)
        self.assertEqual(result["diagrams"][0]["phase_seconds"],{"outer":3.,"inner":3.})
    def test_separate_bounded_cache(self):
        prof=ap.AtlasProfiler()
        cache=ap.AtlasCache(prof,general_bytes=1024,utci_bytes=4096)
        model=np.arange(24,dtype=float)
        with prof.activate():
            self.assertIs(cache.get_or_compute(("utci","A"),lambda:model),model)
            for i in range(40):cache.get_or_compute(("other",i),lambda:np.zeros(64))
            self.assertIs(cache.get_or_compute(("utci","A"),lambda:self.fail("UTCI evicted")),model)
            cache.get_or_compute(("large",1),lambda:np.zeros(10000))
        self.assertEqual(prof.cache_stats["utci.hits"],1)
        self.assertGreater(prof.cache_stats["other.evictions"],0)
        self.assertEqual(prof.cache_stats["large.not_retained"],1)
        self.assertLessEqual(prof.cache_peak["general"],1024)
        self.assertLessEqual(prof.cache_peak["utci"],4096)
    def test_sun_shade_exact_reuse_matches_independent_reference(self):
        df=self.fixture()
        df.loc[df.index[0],p.RH]=np.nan
        df.loc[df.index[7],p.V]=.1
        df.loc[df.index[8],p.GHI]=np.nan
        mrt=p.radiant_scenarios(df)
        expected=pd.DataFrame({name:p.utci_values(df[p.T],mrt[name],df[p.V],df[p.RH]) for name in mrt},index=df.index)
        expected.attrs.update(df.attrs)
        prof=ap.AtlasProfiler()
        with prof.activate():actual,tr=p.utci_frame(df,model="Open-sky screening")
        pd.testing.assert_frame_equal(actual,expected,check_exact=True)
        pd.testing.assert_frame_equal(tr,mrt,check_exact=True)
        same=np.isfinite(mrt.iloc[:,0])&np.isfinite(mrt.iloc[:,1])&(mrt.iloc[:,0]==mrt.iloc[:,1])
        self.assertEqual(prof.utci_stats["identical_scenario_states_reused"],int(same.sum()))
        self.assertGreater(int(same.sum()),0)
        self.assertEqual(prof.utci_stats["requested_states"],2*len(df)-int(same.sum()))
    def test_atlas_profiles_and_reuses_two_models(self):
        df=self.fixture()
        # Source attributes may include rich provider objects. UTCI cache
        # must retain only numerical outputs, not those unrelated attributes.
        df.attrs["provider_metadata_fixture"]=object()
        selected=[d for d in c.catalogue(df,{},c.FULL) if d.status=="available" and d.kind in ("utci","utci_pair","utci_sensitivity")]
        self.assertEqual(len(selected),13)
        with patch.object(p,"utci_frame",wraps=p.utci_frame) as compute:
            data,manifest,meta=generate_atlas(selected,df,{},mode=PDF_MODES[2])
        self.assertEqual(compute.call_count,2)
        self.assertEqual(meta["counts"]["generated"],len(selected))
        prof=meta["atlas_profile"]
        self.assertEqual(len(prof["diagrams"]),len(selected))
        self.assertEqual(prof["cache"]["utci.misses"],2)
        self.assertEqual(prof["cache"]["utci.hits"],8)
        self.assertGreater(prof["phase_calls"]["utci_library_evaluation"],0)
        self.assertLessEqual(sum(prof["exclusive_phase_seconds"].values()),prof["wall_seconds"]+1e-6)
        for r in prof["diagrams"]:
            self.assertLessEqual(sum(r["phase_seconds"].values()),r["wall_seconds"]+1e-6)

if __name__=="__main__":unittest.main()
