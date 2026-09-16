# Building Energy Tools

Independent research and teaching tools for building physics, climate analysis and building performance.

**Author:** Ivan Dmitriev

The first public application is **Climate Analyzer**, an interactive EPW climate-analysis tool for building design, building physics and early passive/HVAC decision support.

## Repository structure

- `website/` — public project website content and publication gates
- `tools/` — interactive engineering and research tools
- `deployment/` — deployment contracts and live-audit checklists
- `docs/` — architecture and project-wide publication policy
- `.github/workflows/` — automated quality and release gates

## Academic affiliation

Academic affiliation: **Institute of Buildings and Energy, Graz University of Technology**.

This affiliation is stated for biographical context only. **Building Energy Tools is an independent personal research and teaching project and is not an official website, service or product of Graz University of Technology.**

No TU Graz logo or institutional branding is part of the independent project identity.

## Climate Analyzer release candidate

Current candidate:

```text
Climate Analyzer 0.1.0-beta.1
channel: public-beta-candidate
status: BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

Scientific validation, security boundaries and runtime checks are implemented, but public publication remains deliberately fail-closed until the deployment-specific identity/contact, privacy, accessibility and attribution gates in `website/PUBLICATION_CHECKLIST.md` are resolved.

Key documentation:

- `docs/PUBLICATION_POLICY.md`
- `website/PUBLICATION_CHECKLIST.md`
- `website/content/about.md`
- `website/content/privacy.md`
- `tools/climate_analyzer/METHODOLOGY.md`
- `tools/climate_analyzer/DATA_SOURCES.md`
- `tools/climate_analyzer/ATTRIBUTION.md`
- `tools/climate_analyzer/SECURITY.md`
- `deployment/STREAMLIT_COMMUNITY_CLOUD.md`
- `deployment/BROWSER_AUDIT_CHECKLIST.md`

## Licensing status

No repository-wide open-source licence has been selected yet. Public source availability must not be interpreted as an unrestricted licence to copy, modify or redistribute the project. Third-party software, map data and climate datasets retain their own terms and attribution requirements.

## Development status

```text
WEB-0.1  Production Foundation                 CLOSED
WEB-0.2  Climate Analyzer Import               CLOSED
WEB-0.3  Runtime + Security                    CLOSED
WEB-0.4  Scientific Validation                 CLOSED
WEB-0.5  Data Catalog + Provenance             CLOSED
WEB-0.6  Public UX                             CLOSED
WEB-0.7  Identity + Legal/Methodology          CLOSED
WEB-0.8  Beta Deployment + Browser Audit       IN PROGRESS
```

`WEB-0.8` aligns repository execution with Streamlit Community Cloud and prepares the evidence checklist for the live deployment. Public promotion remains blocked until the publication checklist and deployed-browser audit are complete.
