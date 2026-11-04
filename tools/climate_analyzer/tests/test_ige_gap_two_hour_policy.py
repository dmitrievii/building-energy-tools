"""Operational admission boundaries; all weather here is synthetic."""
import gzip
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from epw_climate_analyzer.climate_model import ClimateLocation
from epw_climate_analyzer.engine.point_interpolation import T, RH, P, E, PointDonor, saturation_buck_hpa
from epw_climate_analyzer.station_gap_recovery import GAP_POLICY, MAX_GAP_HOURS, recover_station_gaps


def synthetic_donors(missing):
    clock = pd.date_range('2021-01-01', periods=8760, freq='h', tz='UTC')
    h = np.arange(len(clock))
    donors = []
    for j in range(4):
        frame = pd.DataFrame({T: 10+np.sin(h/24)+j*.1, RH: np.full(len(h), 50.),
            P: 98000+10*np.sin(h/12)-j*100}, index=clock)
        frame[E] = frame[RH]/100*saturation_buck_hpa(frame[T])
        rows, blockers = [], []
        if j == 0:
            for field, positions in missing.items():
                frame.loc[clock[positions], field] = np.nan
                if field in (T, RH): frame.loc[clock[positions], E] = np.nan
                blockers.append('H1_CORE_NOT_ADMITTED_'+field)
                for group in np.split(np.asarray(positions), np.flatnonzero(np.diff(positions)!=1)+1):
                    rows.append({'field': field, 'reason': 'MISSING_VALUE', 'hours': len(group),
                        'first_interval_start_utc': clock[group[0]].isoformat(),
                        'last_interval_start_utc': clock[group[-1]].isoformat()})
        ledger = pd.DataFrame(rows, columns=['field', 'reason', 'hours', 'first_interval_start_utc', 'last_interval_start_utc'])
        donors.append(PointDonor(str(j), ClimateLocation(47+j*.01, 15, 375), frame, 2021, 375, 375,
            'SYNTHETIC', True, str(j)*64, 'GEOSPHERE_H1_ENDPOINTS_BUCK_RH_ASSUMPTION', tuple(blockers),
            source_admission={'global_blockers': []}, source_gaps_csv_gz=gzip.compress(ledger.to_csv(index=False).encode())))
    return donors


class TwoHourPolicyTests(unittest.TestCase):
    def test_one_and_two_hour_episodes_pass_with_every_estimate_logged(self):
        self.assertEqual(MAX_GAP_HOURS, 2)
        self.assertIn('2H_V2', GAP_POLICY)
        for n in (1, 2):
            with self.subTest(n=n):
                donors = synthetic_donors({k: list(range(4000,4000+n)) for k in (T,RH,P)})
                updated, audit = recover_station_gaps(donors)
                self.assertFalse(updated[0].blockers)
                self.assertEqual(audit['max_gap_hours'], 2)
                episode, = audit['stations'][0]['episodes']
                self.assertTrue(episode['accepted'])
                self.assertEqual(episode['hours'], n)
                self.assertTrue(all(len(v)==n for v in episode['estimated_values'].values()))
                self.assertEqual(donors[0].data[T].isna().sum(),n)

    def test_three_hours_are_rejected_before_estimation_without_chunking(self):
        donors = synthetic_donors({T: [4000,4001,4002]})
        with patch('epw_climate_analyzer.station_gap_recovery._episode',side_effect=AssertionError('NO_LONG_GAP_ESTIMATE')):
            updated, audit = recover_station_gaps(donors)
        self.assertIs(updated[0],donors[0])
        self.assertIn('GAP_DURATION_LIMIT: 3', audit['stations'][0]['reason'])

    def test_staggered_fields_form_one_three_hour_episode(self):
        donors = synthetic_donors({T: [4000,4001], RH: [4001,4002]})
        updated, audit = recover_station_gaps(donors)
        self.assertIs(updated[0],donors[0])
        self.assertIn('GAP_DURATION_LIMIT: 3', audit['stations'][0]['reason'])

    def test_annual_one_percent_budget_still_blocks_many_short_gaps(self):
        missing = [i for first in range(500,500+44*24,24) for i in (first,first+1)]
        donors = synthetic_donors({T: missing})
        updated, audit = recover_station_gaps(donors)
        self.assertIs(updated[0],donors[0])
        self.assertEqual(audit['stations'][0]['reason'],'ANNUAL_MISSING_HOUR_BUDGET')

    def test_year_boundaries_require_both_original_anchors(self):
        for positions in ([0,1],[8758,8759]):
            with self.subTest(positions=positions):
                donors = synthetic_donors({T: positions})
                updated, audit = recover_station_gaps(donors)
                self.assertIs(updated[0],donors[0])
                self.assertEqual(audit['stations'][0]['reason'],'GAP_UNBRACKETED_BY_ORIGINAL_OBSERVATIONS')

    def test_later_long_gap_cannot_publish_a_partially_recovered_donor(self):
        donors = synthetic_donors({T: [4000,4001,4100,4101,4102]})
        updated, audit = recover_station_gaps(donors)
        self.assertIs(updated[0],donors[0])
        self.assertEqual(updated[0].data[T].isna().sum(),5)
        self.assertEqual(audit['stations'][0]['status'],'BLOCKED')

    def test_nonphysical_short_gap_still_fails_without_clipping(self):
        donors = synthetic_donors({RH: [4000,4001]})
        for peer in donors[1:]:
            peer.data.loc[peer.data.index[4000:4002], E] = 100.
        updated, audit = recover_station_gaps(donors)
        self.assertIs(updated[0],donors[0])
        self.assertIn('RECONSTRUCTION_OUTSIDE_PHYSICAL_BOUNDS',audit['stations'][0]['reason'])
