"""IV1 source registration guards prevent known pressure/time substitutions."""
import copy
import unittest

from p9_3b3_iv1_preflight import guard, cohort, observation_field_guard, preflight


class SourceAdmission(unittest.TestCase):
    def test_registered_cohort_has_no_training_year_and_exact_denominator(self):
        p = guard(); c = cohort(p)
        self.assertEqual(len(c), 84)
        self.assertEqual(sum(len(r['hours_UTC']) for r in c), 2016)
        self.assertEqual({r['date'][:4] for r in c}, {'2022'})
        self.assertEqual({r['date'][5:7] for r in c}, {'02', '08'})
        self.assertEqual({r['station_id'] for r in c if r['country'] == 'AT'}, {'16412'})

    def test_reduced_DWD_pressure_is_rejected(self):
        fields = copy.deepcopy(guard()['observation_fields'])
        fields['DE']['p'] = 'PP_ST_10'
        with self.assertRaisesRegex(ValueError, 'ABSOLUTE_DWD'):
            observation_field_guard(fields)

    def test_hourly_CH_means_cannot_replace_current_values(self):
        for key, value in [('T', 'tre200h0'), ('RH', 'ure200h0'), ('p', 'prestah0')]:
            fields = copy.deepcopy(guard()['observation_fields'])
            fields['CH'][key] = value
            with self.assertRaisesRegex(ValueError, 'CURRENT_CH'):
                observation_field_guard(fields)

    def test_2022_metadata_are_admitted_without_double_adding_AGL(self):
        r = preflight()
        self.assertEqual(r['dated_sensor_countries_confirmed'], 3)
        self.assertEqual(r['instrument_heights_MSL_m']['AT']['temperature'], 368.7)
        self.assertEqual(r['instrument_heights_MSL_m']['DE']['pressure'], 82.5)
        self.assertEqual(r['instrument_heights_MSL_m']['CH']['RH_water'], 1593.93)

    def test_metadata_success_never_opens_observations_or_qualifies_accuracy(self):
        r = preflight()
        self.assertFalse(r['ready_to_open_observations'])
        self.assertFalse(r['station_values_opened'])
        self.assertFalse(r['station_scores_computed'])
        self.assertEqual(r['independent_accuracy'], 'NOT_RUN')
        self.assertEqual(len(r['source_blockers']), 3)


if __name__ == '__main__':
    unittest.main()
