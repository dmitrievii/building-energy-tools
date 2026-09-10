# Climate Analyzer attribution register

This file separates attribution and external-service obligations from Building Energy Tools project identity.

## Climate.OneBuilding

Climate Analyzer uses a reviewed station catalog derived from public Climate.OneBuilding catalog resources and downloads selected EPW payloads from Climate.OneBuilding on demand.

The repository does not bundle Climate.OneBuilding EPW payloads and does not assert one blanket redistribution licence over the provider's heterogeneous source datasets.

Provider/source information is versioned in:

```text
epw_climate_analyzer/data/station_catalog.meta.json
DATA_SOURCES.md
```

Current provider reference:

- Climate.OneBuilding: https://climate.onebuilding.org/
- Weather Data Sources: https://climate.onebuilding.org/sources/default.html

Dataset-specific provenance should remain visible because TMYx and other packages can originate from different underlying data sources and construction methods.

## OpenStreetMap

The station-selection map uses OpenStreetMap-derived mapping through Folium/Leaflet.

OpenStreetMap requires visible attribution and identification of the Open Database License for OSM data. The deployed interactive map must keep the required map attribution visible and legible; it must not be hidden by application chrome or styling.

Reference:

- OpenStreetMap copyright/licence: https://www.openstreetmap.org/copyright
- OSMF attribution guidelines: https://osmfoundation.org/wiki/Licence/Attribution_Guidelines
- OSMF tile usage policy: https://operations.osmfoundation.org/policies/tiles/

The standard OSM tile service is best-effort and has no SLA. If public usage grows materially, map-tile infrastructure must be reviewed rather than assuming the community tile service is an unlimited production CDN.

## Streamlit / Streamlit Community Cloud

Climate Analyzer currently targets Streamlit Community Cloud for the beta deployment.

Streamlit is application/runtime infrastructure, not a scientific data source. Hosting/privacy behavior is documented separately in `website/content/privacy.md` and must be verified against the actual deployment.

References:

- https://docs.streamlit.io/
- https://streamlit.io/privacy-policy

## Scientific/software dependencies

Pinned direct dependencies are declared in `requirements.txt`. Major calculation dependencies include PsychroLib and pvlib; data/visualization/runtime dependencies include pandas, NumPy, Plotly, Streamlit, Folium and related packages.

Dependency inclusion in this project does not change the licences of those packages. A later software-release step should generate/review a dependency-licence inventory before a formal public software distribution is declared.

## Building Energy Tools source-code licence

No repository-wide open-source licence has been selected in `WEB-0.7`.

Until an explicit licence is added, do not describe public source availability as permission for unrestricted copying, modification or redistribution. Selecting a project code licence is an explicit pre-release decision recorded in `website/PUBLICATION_CHECKLIST.md`.
