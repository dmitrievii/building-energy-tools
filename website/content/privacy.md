# Privacy information — public beta draft

**Status:** live-deployment draft. A Streamlit Community Cloud deployment exists, but controller contact fields, legal-basis/consent review and final publication clearance remain unresolved. Do not represent this document as a completed legal privacy notice.

## Controller

Project operator: **Ivan Dmitriev**.

Public geographic/contact address and public electronic contact address: **to be approved before public promotion**.

These fields must not be replaced with the TU Graz address merely because an academic affiliation is stated. Final controller/contact information and the applicable Austrian/GDPR disclosure basis require a deployment-specific review.

## Current deployment

Climate Analyzer is currently deployed at:

```text
https://building-climate-analyzer.streamlit.app/
```

The host is **Streamlit Community Cloud**. Streamlit's current Community Cloud documentation states that Community Cloud applications are hosted in the United States and that this location is not configurable.

Streamlit also documents that Community Cloud overrides contrary application configuration and sets:

```toml
[browser]
gatherUsageStats = true
```

Therefore the repository's local/self-hosted `gatherUsageStats = false` setting must **not** be interpreted as disabling Community Cloud platform analytics or telemetry.

Provider references:

- https://docs.streamlit.io/deploy/streamlit-community-cloud
- https://docs.streamlit.io/deploy/streamlit-community-cloud/status
- https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app/app-analytics
- https://streamlit.io/privacy-policy

## What Building Energy Tools intentionally processes

### EPW uploads

If you upload an EnergyPlus Weather (EPW) file to Climate Analyzer, the file is transmitted from your browser to the Streamlit application backend so the application can parse and analyze it.

The Building Energy Tools application code keeps the active EPW payload in the current Streamlit session. It does not intentionally write uploaded EPW files to a project database or persistent project storage.

Do not upload EPW files containing confidential or personal information in custom metadata fields.

### Climate.OneBuilding selections

If you select an online station, Climate Analyzer uses the reviewed station metadata stored with the application and requests the selected EPW archive from Climate.OneBuilding on demand. The weather payload is processed by the application for the active analysis session; Climate.OneBuilding EPW files are not committed to the Building Energy Tools repository.

## Uploaded-file lifecycle

Streamlit documents `st.file_uploader` uploads as being transferred to the backend and held in memory rather than automatically written to disk. Climate Analyzer additionally stores the selected payload in Streamlit session state so it remains available while the user works with the application.

The application does not promise a precise platform-level deletion time beyond the behavior controlled by its own code. Users should clear/change the active climate or close their session when finished and should avoid uploading confidential data.

## Live provider analytics and telemetry evidence

A reproducible anonymous-browser audit of the live Community Cloud deployment on **2026-09-10** observed provider-controlled requests before any Climate Analyzer map interaction to domains including:

```text
building-climate-analyzer.streamlit.app
share.streamlit.io
data.streamlit.io
www.googletagmanager.com
www.google-analytics.com
stats.g.doubleclick.net
cdn.segment.com
heapanalytics.com
cdn.heapanalytics.com
webhooks.fivetran.com
www.streamlitstatus.com
qjmnz4vd2y07.statuspage.io
```

The application source does not add Google Analytics, Google Tag Manager, Segment, Heap or advertising code itself. These requests were observed in the **Community Cloud hosting/wrapper layer** and must nevertheless be considered part of the user's actual deployed experience.

The project has not yet completed a legal-basis/consent assessment for these provider-controlled analytics/storage mechanisms. Their presence is therefore a publication blocker, not something this draft declares compliant.

Detailed engineering evidence is recorded in `deployment/LIVE_AUDIT_2026-09-10.md`.

## Cookies and browser storage observed live

No cookie values are retained in the project audit evidence. The anonymous live audit observed cookie names including:

```text
_streamlit_csrf
streamlit_session
proxy-tracking-id
_ga
_gid
_dc_gtm_UA-122023594-8
_hp2_id.269788835
_hp2_ses_props.269788835
_dd_s
ajs_anonymous_id
```

Browser `localStorage` contained keys including:

```text
ajs_anonymous_id
appSessionId-<generated-id>
appSessionId-undefined
machineId
stMetricsConfig
```

No `sessionStorage` keys were observed in the audited sessions.

The names above are an observed technical inventory. This draft does not assign a legal classification, retention basis or consent exemption to each item. That assessment must be completed before publication clearance.

## Streamlit public-session bootstrap

An unauthenticated request to the custom Streamlit subdomain first redirects through `share.streamlit.io` and the app's `/-/login` bootstrap before returning to the public app. The audit observed Streamlit session and CSRF cookies during this process.

This bootstrap occurs for an anonymous public app session and must not be described as the application having no platform-level session identifiers.

## External map resources

The station-selection interface uses an OpenStreetMap-based interactive map through Folium/Leaflet. When the user opens the map, browser requests can be made to external map/component infrastructure including `tile.openstreetmap.org` and supporting JavaScript/CDN resources. Ordinary connection metadata such as IP address, timestamp, requested resource and user-agent information may therefore be transmitted to those providers.

The first live audit also identified that the pre-remediation `st.tabs()` implementation could instantiate the map before explicit `Find climate` selection. `WEB-0.8.1` replaces those eager tabs with conditional rendering so the OpenStreetMap path is not executed until the user actively chooses `Find climate`. This change requires post-merge live verification before the finding is considered closed.

The live map displayed a visible `OpenStreetMap` attribution link to the OpenStreetMap copyright page.

## Server logs and provider processing

Hosting and infrastructure providers may process technical connection/log data needed to operate, secure and analyze their services. Streamlit Community Cloud provides app analytics; public app viewers are represented in its analytics system according to Streamlit's documented behavior.

Building Energy Tools does not control all platform-level logging or telemetry performed by Streamlit/Snowflake. A future static-site host will require a separate inventory of its own logging, cookies and data transfers.

## Your data-protection rights

Where the GDPR applies to processing for which the project operator is the controller, data subjects may have rights including access, rectification, erasure, restriction, objection and data portability, subject to the conditions and exceptions in applicable law. They may also have the right to lodge a complaint with a competent supervisory authority.

Final controller contact details must be present before this section can function as a usable Article 13 transparency notice.

## Publication gate

The current live deployment evidence does **not** clear the project for public promotion. At minimum, the following remain open:

- approve and publish appropriate controller contact information;
- determine the applicable legal basis and, where required, consent mechanism for provider analytics/cookies/storage;
- review international-transfer/provider information for the actual Community Cloud deployment;
- repeat browser/network/accessibility checks after the `WEB-0.8.1` remediation is live;
- ensure the final privacy/legal notice is directly accessible to users of the public project.

## Revision

Live-audit draft: **2026-09-10 / Climate Analyzer 0.1.0-beta.1 candidate**.

This notice must be reviewed whenever hosting, analytics, authentication, external resources, file persistence, contact forms or other data-processing behavior changes.
