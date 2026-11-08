"""Regression guard: published visualizer must display the ZIP contract it enforces."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_visible_deployment_version_and_upload_limits():
    application = (ROOT / 'app.py').read_text(encoding='utf-8')
    importer = (ROOT / 'epb_results_visualizer' / 'multi_compare.py').read_text(encoding='utf-8')
    configuration = (ROOT / '.streamlit' / 'config.toml').read_text(encoding='utf-8')

    assert "VISUALIZER_RELEASE = 'V3.4.1" in application
    assert "selective hourly/trace" in application
    assert "ZIP limits: 512 MiB per archive · 800 MiB combined" in application
    assert "Combined ZIP upload exceeds 240 MiB" not in importer
    assert "Combined ZIP upload exceeds 800 MiB" in importer
    assert "maxUploadSize = 512" in configuration
    assert "maxMessageSize = 512" in configuration
    assert "max_upload_size=512" in application


def test_selective_large_zip_importer_is_used():
    importer = (ROOT / 'epb_results_visualizer' / 'multi_compare.py').read_text(encoding='utf-8')
    assert "read_bundle(payload, metadata_only=large)" in importer
    assert "800 * 1024 * 1024" in importer
