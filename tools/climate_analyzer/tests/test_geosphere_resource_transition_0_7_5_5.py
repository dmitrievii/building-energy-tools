from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace
import unittest

from epw_climate_analyzer.source_parity_contract_guidance_hotfix import (
    _RESOURCE_KEY,
    _install_guidance_safe,
)


class _FakeStreamlit:
    def __init__(self, initial_resource: str, selected_resource: str) -> None:
        self.session_state = {_RESOURCE_KEY: initial_resource}
        self.selected_resource = selected_resource
        self.resource_selectbox_calls = 0
        self.info = lambda *args, **kwargs: None
        self.caption = lambda *args, **kwargs: None
        self.write = lambda *args, **kwargs: None
        self.expander = lambda *args, **kwargs: nullcontext()
        self.radio = lambda label, options, *args, **kwargs: list(options)[0]
        self.data_editor = lambda data, *args, **kwargs: data
        self.column_config = SimpleNamespace(TextColumn=lambda *args, **kwargs: None)

    def selectbox(self, label, options, *args, **kwargs):
        values = list(options)
        if label == "GeoSphere dataset" and kwargs.get("key") == _RESOURCE_KEY:
            self.resource_selectbox_calls += 1
            if self.selected_resource not in values:
                raise AssertionError(f"Selected resource {self.selected_resource} not in {values}")
            self.session_state[_RESOURCE_KEY] = self.selected_resource
            return self.selected_resource
        return values[0]


class GeoSphereResourceTransitionTests(unittest.TestCase):
    def _exercise(self, initial_resource: str, selected_resource: str) -> None:
        st = _FakeStreamlit(initial_resource, selected_resource)
        observed_at_previous_entry: list[str] = []
        inner_dataset_returns: list[str] = []

        def previous(_legacy, _original) -> None:
            observed_at_previous_entry.append(str(st.session_state.get(_RESOURCE_KEY, "")))
            inner_dataset_returns.append(
                str(
                    st.selectbox(
                        "GeoSphere dataset",
                        ["klima-v2-10min", "klima-v2-1h", "klima-v2-1m"],
                        index=0,
                        key=_RESOURCE_KEY,
                    )
                )
            )

        parity = SimpleNamespace(
            st=st,
            _render_geosphere_resource_selector=previous,
            available_resource_specs=lambda: [
                SimpleNamespace(resource_id="klima-v2-10min"),
                SimpleNamespace(resource_id="klima-v2-1h"),
                SimpleNamespace(resource_id="klima-v2-1m"),
            ],
            resource_spec=lambda resource_id: SimpleNamespace(label=str(resource_id)),
        )

        _install_guidance_safe(parity)
        parity._render_geosphere_resource_selector(object(), lambda: None)

        self.assertEqual(observed_at_previous_entry, [selected_resource])
        self.assertEqual(inner_dataset_returns, [selected_resource])
        self.assertEqual(st.session_state[_RESOURCE_KEY], selected_resource)
        self.assertEqual(st.resource_selectbox_calls, 1)

    def test_monthly_to_hourly_commits_resource_before_legacy_wrappers_enter(self) -> None:
        self._exercise("klima-v2-1m", "klima-v2-1h")

    def test_hourly_to_monthly_commits_resource_before_legacy_wrappers_enter(self) -> None:
        self._exercise("klima-v2-1h", "klima-v2-1m")


if __name__ == "__main__":
    unittest.main()
