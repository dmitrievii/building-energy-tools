"""R2.4: complete daylight-only daily diffuse fraction is not invalidated by night."""
from __future__ import annotations

import unittest
import numpy as np
import pandas as pd

from epw_climate_analyzer.solar_findings import (
    GHI,DHI,diffuse_fraction_daily_occurrence,
)


class SolarR24DaylightFractionTests(unittest.TestCase):
    def sample(self):
        i=pd.date_range("2026-01-01",periods=48,freq="h")
        g=np.zeros(48,dtype=float);d=np.full(48,np.nan,dtype=float)
        for day in range(2):
            g[day*24+9:day*24+15]=200.
            d[day*24+9:day*24+15]=40. if day==0 else 160.
        df=pd.DataFrame({GHI:g,DHI:d},index=i)
        df.attrs["canonical_native_interval_minutes"]=60.
        return df

    def test_zero_ghi_nighttime_is_undefined_but_not_a_missing_day(self):
        df=self.sample()
        for method in ("Mean","Minimum","Maximum"):
            table=diffuse_fraction_daily_occurrence(df,(25.,50.,75.),daily_stat=method)
            self.assertEqual(table.attrs["classified_days"],2)
            self.assertEqual(table.attrs["excluded_missing_days"],0)
            self.assertEqual(float(table.sum().sum()),2.)
            self.assertEqual(float(table["0 < x < 25"].sum()),1.)
            self.assertEqual(float(table["≥ 75"].sum()),1.)

    def test_missing_sunlit_dhi_excludes_day_not_synthesizes_zero(self):
        df=self.sample()
        df.loc[df.index[10],DHI]=np.nan
        result=diffuse_fraction_daily_occurrence(df,(25.,50.,75.))
        self.assertEqual(result.attrs["classified_days"],1)
        self.assertEqual(result.attrs["excluded_missing_days"],1)
        self.assertEqual(float(result.sum().sum()),1.)

    def test_missing_ghi_at_night_invalidates_complete_real_day(self):
        df=self.sample()
        df.loc[df.index[0],GHI]=np.nan
        result=diffuse_fraction_daily_occurrence(df,(25.,50.,75.))
        self.assertEqual(result.attrs["classified_days"],1)

    def test_invalid_edges_rejected(self):
        for edges in ((0.,25.),(50.,25.),(20.,101.)):
            with self.assertRaises(ValueError):
                diffuse_fraction_daily_occurrence(self.sample(),edges)

    def test_no_sunlit_hours_is_not_an_artificial_zero_fraction(self):
        df=self.sample()
        df[GHI]=0.
        result=diffuse_fraction_daily_occurrence(df,(25.,50.,75.))
        self.assertTrue(result.empty)


if __name__=="__main__":
    unittest.main()
