from __future__ import annotations

from types import SimpleNamespace
import unittest

from epw_climate_analyzer.epw_download_surface import install_epw_download_surface


class _FakeStreamlit:
    def __init__(self) -> None:
        self.downloads: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def download_button(self, label: object, *args: object, **kwargs: object) -> bool:
        self.downloads.append((label, args, dict(kwargs)))
        return False


class EpwDownloadSurfaceTests(unittest.TestCase):
    def _app(self, active_file: object | None):
        st = _FakeStreamlit()
        app = SimpleNamespace()
        app.st = st
        app.get_active_climate_file = lambda: active_file

        def render_calculated_epw_statistics(df: object) -> str:
            app.st.download_button(
                "Download dataset statistics as CSV",
                data=b"metric,value\nrows,8760\n",
                file_name="epw_dataset_statistics.csv",
                mime="text/csv",
            )
            return "rendered"

        app.render_calculated_epw_statistics = render_calculated_epw_statistics
        return app, st

    def test_exact_active_epw_payload_is_downloaded_next_to_dataset_csv(self) -> None:
        active = SimpleNamespace(name="AUT_Vienna.epw", payload=b"LOCATION,VIENNA\nDATA\n")
        app, real_st = self._app(active)
        install_epw_download_surface(app)

        result = app.render_calculated_epw_statistics(object())

        self.assertEqual(result, "rendered")
        self.assertIs(app.st, real_st)
        self.assertEqual([call[0] for call in real_st.downloads], [
            "Download dataset statistics as CSV",
            "Download active EPW file",
        ])
        epw_kwargs = real_st.downloads[1][2]
        self.assertEqual(epw_kwargs["data"], active.payload)
        self.assertEqual(epw_kwargs["file_name"], "AUT_Vienna.epw")
        self.assertEqual(epw_kwargs["mime"], "application/octet-stream")
        self.assertEqual(epw_kwargs["key"], "calculated_statistics_active_epw_download")

    def test_missing_epw_extension_is_added(self) -> None:
        active = SimpleNamespace(name="Vienna_weather", payload=b"EPW")
        app, real_st = self._app(active)
        install_epw_download_surface(app)
        app.render_calculated_epw_statistics(object())
        self.assertEqual(real_st.downloads[1][2]["file_name"], "Vienna_weather.epw")

    def test_no_active_epw_does_not_add_download(self) -> None:
        app, real_st = self._app(None)
        install_epw_download_surface(app)
        app.render_calculated_epw_statistics(object())
        self.assertEqual(len(real_st.downloads), 1)
        self.assertEqual(real_st.downloads[0][0], "Download dataset statistics as CSV")


if __name__ == "__main__":
    unittest.main()
