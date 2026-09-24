from __future__ import annotations

import unittest

import streamlit as st

from epw_climate_analyzer import source_parity_runtime
from epw_climate_analyzer.source_parity_streamlit_surface import (
    pristine_streamlit_callable,
    restore_streamlit_surface,
)


class TransactionalStreamlitSurfaceRestoreTests(unittest.TestCase):
    def test_runtime_reset_restores_transactional_form_callables(self) -> None:
        restore_streamlit_surface()
        pristine_button = pristine_streamlit_callable("button")
        pristine_submit = pristine_streamlit_callable("form_submit_button")
        pristine_warning = pristine_streamlit_callable("warning")

        leaked = lambda *args, **kwargs: None
        st.button = leaked
        st.form_submit_button = leaked
        st.warning = leaked

        source_parity_runtime._fresh_source_parity_ui()

        self.assertIs(st.button, pristine_button)
        self.assertIs(st.form_submit_button, pristine_submit)
        self.assertIs(st.warning, pristine_warning)

    def test_installed_marker_path_still_restores_transactional_form_callables(self) -> None:
        restore_streamlit_surface()
        pristine_button = pristine_streamlit_callable("button")
        pristine_submit = pristine_streamlit_callable("form_submit_button")
        pristine_warning = pristine_streamlit_callable("warning")

        leaked = lambda *args, **kwargs: None
        st.button = leaked
        st.form_submit_button = leaked
        st.warning = leaked

        namespace = {
            "VARIABLES": {},
            "load_epw_from_bytes": object(),
            "render_geosphere_source": object(),
            "render_canonical_climate_analysis": object(),
            "render_compare_climates": object(),
            "render_data_quality": object(),
            "_SOURCE_PARITY_RUNTIME_INSTALLED": True,
        }
        self.assertTrue(source_parity_runtime.install_into_app_globals(namespace))

        self.assertIs(st.button, pristine_button)
        self.assertIs(st.form_submit_button, pristine_submit)
        self.assertIs(st.warning, pristine_warning)


if __name__ == "__main__":
    unittest.main()
