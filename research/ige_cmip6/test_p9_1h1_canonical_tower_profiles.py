"""P9.1H1 synthetic contract tests. These tests are NOT original-source qualification."""
import datetime as dt
import io
import unittest

from p9_1h1_canonical_tower_profiles import (
    load_canonical_csv, synchronous_vertical_pairs, hourly_paired_observations,
    strict_utc, INVERSION_EPS_K
)

HEADER="timestamp_utc,height_agl_m,air_temperature_c,source_qc\n"
def source_rows(n=6, *, qc="documented_provider_good", upper=2.0, lower=1.0):
    rows=[]
    for i in range(n):
        stamp=f"2021-01-10T00:{i*10:02d}:00Z"
        rows.append(f"{stamp},2,{lower},{qc}\n")
        rows.append(f"{stamp},10,{upper},{qc}\n")
    return (HEADER+"".join(rows)).encode()

def prepared(blob):
    return load_canonical_csv(blob,provider_id="FIXTURE_ONLY",
                              permitted_heights_m=(2.,10.))

class P9H1SourceContracts(unittest.TestCase):
    def test_exact_six_real_synchronous_pairs_not_interpolated(self):
        rec,meta=prepared(source_rows())
        self.assertEqual(meta["n_source_records"],12)
        self.assertEqual(meta["n_accepted_records"],12)
        self.assertFalse(meta["original_native_provider_file_authenticated"])
        p=synchronous_vertical_pairs(rec,z_low=2.,z_high=10.)
        self.assertEqual(len(p),6)
        self.assertAlmostEqual(p[0]["temperature_gradient_K_km"],125.)
        self.assertTrue(p[0]["observed_positive_inversion"])
        hours=hourly_paired_observations(p,cadence_minutes=10)
        self.assertEqual(len(hours),1)
        self.assertEqual(hours[0]["n_original_simultaneous_pairs"],6)
        self.assertAlmostEqual(hours[0]["mean_delta_T_K"],1.0)

    def test_missing_high_level_never_imputed(self):
        blob=source_rows(6).replace(
            b"2021-01-10T00:20:00Z,10,2.0,documented_provider_good",
            b"2021-01-10T00:20:00Z,10,-999,provider_missing")
        p=synchronous_vertical_pairs(prepared(blob)[0],z_low=2.,z_high=10.)
        self.assertEqual(len(p),5)
        self.assertEqual(len(hourly_paired_observations(p,cadence_minutes=10)),1)

    def test_sparse_original_pairs_do_not_create_hour(self):
        p=synchronous_vertical_pairs(prepared(source_rows(3))[0],z_low=2.,z_high=10.)
        self.assertEqual(len(p),3)
        self.assertEqual(hourly_paired_observations(p,cadence_minutes=10),[])

    def test_duplicate_source_height_time_is_hard_failure(self):
        blob=source_rows(1)
        row=blob.splitlines(keepends=True)[1]
        with self.assertRaisesRegex(ValueError,"DUPLICATE"):
            prepared(blob+row)

    def test_local_time_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError,"EXPLICIT_UTC"):
            strict_utc("2021-01-10T00:00:00+02:00")
        with self.assertRaisesRegex(ValueError,"EXPLICIT_UTC"):
            strict_utc("2021-01-10T00:00:00")
        self.assertEqual(strict_utc("2021-01-10T00:00:00Z").utcoffset(),dt.timedelta())

    def test_physical_inversion_not_same_as_statically_stable(self):
        p=synchronous_vertical_pairs(prepared(source_rows(1,upper=0.99,lower=1.0))[0],
                                     z_low=2.,z_high=10.)
        self.assertFalse(p[0]["observed_positive_inversion"])
        self.assertTrue(p[0]["observed_neutral_band"])
        self.assertGreater(p[0]["approx_dry_theta_gradient_K_km_NOT_OBSERVED_THETA"],0)

    def test_sensor_height_must_be_in_provider_registry(self):
        with self.assertRaisesRegex(ValueError,"UNREGISTERED_NATIVE_SENSOR_HEIGHT"):
            prepared(source_rows(1).replace(b",10,",b",11,"))

    def test_canonical_qc_unknown_does_not_become_observation(self):
        rec,meta=prepared(source_rows(1,qc="unknown"))
        self.assertEqual(rec,[])
        self.assertEqual(meta["n_rejected_records"],2)

    def test_bad_goodflag_temperature_rejected_not_sanitized(self):
        with self.assertRaisesRegex(ValueError,"GOOD_QC_T_OUTSIDE_SANITY_RANGE"):
            prepared(source_rows(1,upper=-999))

    def test_mismatched_cadence_is_hard_failure(self):
        p=synchronous_vertical_pairs(prepared(source_rows(1))[0],z_low=2.,z_high=10.)
        with self.assertRaisesRegex(ValueError,"CADENCE_ALIGNMENT"):
            p[0]["time_utc"]=p[0]["time_utc"].replace(minute=1)
            hourly_paired_observations(p,cadence_minutes=10)

    def test_registry_cannot_accept_only_one_sensor(self):
        with self.assertRaisesRegex(ValueError,"PROVIDER_OR_HEIGHT_REGISTRY_MISSING"):
            load_canonical_csv(source_rows(),provider_id="FIXTURE_ONLY",
                               permitted_heights_m=(2.,))


if __name__=="__main__":
    unittest.main()
