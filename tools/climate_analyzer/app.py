"""Climate Analyzer Streamlit entrypoint.

The mature visual/UI shell lives in :mod:`app_legacy` during the source-parity
migration.  Scientific/data-source behavior is installed through canonical,
provider-neutral engines before ``main`` is executed.  This keeps the existing
visual contract stable while EPW and GeoSphere routes converge on abstract
DataFrames.

Stable public concepts retained by this entrypoint include:
``render_geosphere_source``, ``render_canonical_climate_analysis``,
``render_compare_climates``, ``render_temperature``, ``render_humidity``,
``render_solar``, ``render_sky_daylight``, ``render_wind``,
``render_precipitation``, ``render_time_series_overlay``,
``render_natural_ventilation``, ``render_hvac_passive`` and Data Quality.
"""

from __future__ import annotations

# Re-export the established application surface so tests, integrations and local
# launch scripts importing ``app`` do not have to know about the migration shell.
from app_legacy import *  # noqa: F401,F403
import app_legacy as _legacy

from epw_climate_analyzer import source_parity_ui as _parity
from epw_climate_analyzer.source_parity_fixes import apply_source_parity_fixes


_parity.install_source_parity_ui(_legacy)
apply_source_parity_fixes(_legacy, _parity)

# Refresh public exports after patch installation. ``from app_legacy import *``
# above preserves the broad compatibility surface; this loop ensures names whose
# implementation was replaced by the parity layer resolve to the active version.
for _name in dir(_legacy):
    if not _name.startswith("_"):
        globals()[_name] = getattr(_legacy, _name)


def main() -> None:
    """Run the Climate Analyzer with canonical source-parity routing enabled."""
    _legacy.main()


if __name__ == "__main__":
    main()
