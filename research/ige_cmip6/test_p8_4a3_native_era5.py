"""IGE P8.4A3 original-source separation, vector, time and spatial contracts."""
import datetime as dt
import math
import unittest

from p8_4a3_native_era5 import (
    ARCO_COMPONENTS,ARCO_UTC_HOURS,ARCO_URL,SWISS,MODES,
    meteorological_from_uv,uv_from_wind,endpoint_proxies,
    gateway_params,paired_gateway_metrics,angular_longitude,
    same_regular_grid_cell,MIN_HOURS,
)
from p8_4a1_source_semantics import january_hours


def wind(speed=2.,direction=90.):
    return {"speed":float(speed),"direction":direction}


def obs_and_gateway():
    hours=january_hours()
    observed={t:wind(2.,180.) for t in hours}
    predictions={
        m:{t:wind(2.+(.2 if m=="default_terrain" else .1),180.) for t in hours}
        for m in MODES
    }
    return observed,predictions


class TestNativeERA5Wind(unittest.TestCase):
    def test_era5_components_are_the_frozen_official_vectors(self):
        self.assertEqual(ARCO_COMPONENTS,
            ("10m_u_component_of_wind","10m_v_component_of_wind"))
        self.assertIn("full_37-1h-0p25deg",ARCO_URL)
        self.assertEqual(len(ARCO_UTC_HOURS),4)
        self.assertEqual(SWISS,("BAS","GRA","MUB"))

    def test_cardinal_meteorological_from_direction(self):
        vectors=((0.,-3.,0.),(-3.,0.,90.),(0.,3.,180.),(3.,0.,270.))
        for u,v,expected in vectors:
            result=meteorological_from_uv(u,v)
            self.assertAlmostEqual(result["speed"],3.)
            self.assertAlmostEqual(result["direction"],expected)

    def test_direction_wraparound_and_halfwind(self):
        for az in (0.,1.,45.,90.,179.,180.,270.,359.,359.99999):
            row=wind(3.,az)
            u,v=uv_from_wind(row)
            result=meteorological_from_uv(u,v)
            self.assertAlmostEqual(result["speed"],3.,places=7)
            self.assertLess(abs(((result["direction"]-az+180)%360)-180),1e-7)

    def test_unresolved_calm_has_no_azimuth(self):
        self.assertIsNone(meteorological_from_uv(0.,0.)["direction"])
        self.assertEqual(uv_from_wind(wind(0.,None)),(0.,0.))
        self.assertIsNone(uv_from_wind(wind(2.,None)))

    def test_invalid_uv_are_rejected(self):
        with self.assertRaisesRegex(ValueError,"INVALID_VECTOR"):
            meteorological_from_uv(float("nan"),2.)

    def test_proxy_identical_direction(self):
        x=endpoint_proxies(wind(1.,90.),wind(3.,90.))
        self.assertAlmostEqual(x["endpoint_scalar"],2.)
        self.assertAlmostEqual(x["endpoint_vector"],2.)
        self.assertAlmostEqual(x["endpoint_vector_direction"],90.)

    def test_proxy_opposite_direction_jensen(self):
        x=endpoint_proxies(wind(2.,0.),wind(2.,180.))
        self.assertAlmostEqual(x["endpoint_scalar"],2.)
        self.assertAlmostEqual(x["endpoint_vector"],0.)
        self.assertIsNone(x["endpoint_vector_direction"])

    def test_no_subhourly_equivalence_can_follow_from_two_endpoints(self):
        # Same two endpoint speeds allow arbitrarily different interior
        # speeds: there is no proof of 1h scalar mean from two samples.
        endpoints=(wind(2.,90.),wind(2.,90.))
        a=endpoint_proxies(*endpoints)
        timeline_flat=[2.]*5
        timeline_peak=[2.,8.,8.,8.,2.]
        self.assertEqual(a["endpoint_scalar"],2.)
        self.assertNotEqual(sum(timeline_flat)/5,sum(timeline_peak)/5)

    def test_missing_direction_in_noncaml_blocks_vector(self):
        self.assertIsNone(endpoint_proxies(wind(2.,None),wind(2.,90.)))

    def test_gateway_two_frozen_modes(self):
        station={"lat":47.5,"lon":8.5}
        default=gateway_params(station,"default_terrain")
        nearest=gateway_params(station,"nearest_no_downscaling")
        for row in (default,nearest):
            self.assertEqual(row["models"],"era5")
            self.assertEqual(row["wind_speed_unit"],"ms")
            self.assertEqual(row["timezone"],"GMT")
            self.assertEqual(row["hourly"],"wind_speed_10m,wind_direction_10m")
        self.assertNotIn("cell_selection",default)
        self.assertNotIn("elevation",default)
        self.assertEqual(nearest["cell_selection"],"nearest")
        self.assertEqual(nearest["elevation"],"nan")

    def test_reject_unsupported_gateway_mode(self):
        with self.assertRaisesRegex(ValueError,"UNKNOWN_GATEWAY_MODE"):
            gateway_params({"lat":47.,"lon":8.},"best_match")

    def test_same_744_hour_denominators(self):
        obs,pred=obs_and_gateway()
        info=paired_gateway_metrics(obs,pred)
        self.assertEqual(info["n_common_744h_baseline"],744)
        self.assertEqual(info["gateway_modes_same_reference_hours"]["default_terrain"]["n_speed_pairs"],744)
        self.assertEqual(info["gateway_modes_same_reference_hours"]["nearest_no_downscaling"]["n_speed_pairs"],744)
        self.assertEqual(info["two_endpoint_quadrature_sensitivity"]["default_terrain"]["n_strict_same_interior_UTC_hours"],743)
        self.assertEqual(info["two_endpoint_quadrature_sensitivity"]["nearest_no_downscaling"]["n_strict_same_interior_UTC_hours"],743)
        self.assertTrue(info["no_clock_shift_selected"])

    def test_missing_provider_hour_has_pairwise_equal_denominator(self):
        obs,pred=obs_and_gateway()
        pred["default_terrain"].pop(january_hours()[100])
        info=paired_gateway_metrics(obs,pred)
        self.assertEqual(info["n_common_744h_baseline"],743)
        self.assertEqual(info["gateway_modes_same_reference_hours"]["nearest_no_downscaling"]["n_speed_pairs"],743)
        self.assertEqual(info["gateway_modes_same_reference_hours"]["default_terrain"]["n_speed_pairs"],743)
        self.assertEqual(info["two_endpoint_quadrature_sensitivity"]["nearest_no_downscaling"]["n_strict_same_interior_UTC_hours"],741)

    def test_fail_closed_empty_hourly_sources(self):
        with self.assertRaisesRegex(ValueError,"INSUFFICIENT_GATEWAY_COMMON_HOURS"):
            paired_gateway_metrics({},obs_and_gateway()[1])

    def test_native_grid_matching_requires_actual_grid_center(self):
        a={"latitude":47.25,"longitude":8.5}
        b={"latitude":47.25,"longitude":8.5}
        self.assertTrue(same_regular_grid_cell(a,b))
        self.assertFalse(same_regular_grid_cell(a,{"latitude":47.5,"longitude":8.5}))
        self.assertFalse(same_regular_grid_cell(a,{"latitude":47.25,"longitude":8.75}))

    def test_lon_angular_360_wrap(self):
        self.assertAlmostEqual(angular_longitude(359.99,-.01),0.)
        self.assertAlmostEqual(angular_longitude(0.,180.),180.)

    def test_native_original_samples_fixed_and_utc(self):
        self.assertEqual(ARCO_UTC_HOURS,
            ("2024-01-15T00:00:00","2024-01-15T06:00:00",
             "2024-01-15T12:00:00","2024-01-15T18:00:00"))
        self.assertTrue(all(dt.datetime.fromisoformat(x).year==2024 for x in ARCO_UTC_HOURS))

    def test_meteorological_from_components_does_not_invent_from_nonfinite(self):
        with self.assertRaisesRegex(ValueError,"INVALID_VECTOR"):
            meteorological_from_uv(3.,float("inf"))


if __name__=="__main__":
    unittest.main()
