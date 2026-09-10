# Privacy information — public beta draft

**Status:** live-deployment draft. A Streamlit Community Cloud deployment exists, but controller/disclosure fields and the provider-controlled analytics/consent issue remain unresolved. Do not represent this document as a completed legal privacy notice or publication clearance.

## Controller

Project operator: **Ivan Dmitriev**.

Public residence/establishment/contact fields: **to be approved before public promotion**.

These fields must not be populated from private project metadata or replaced with the TU Graz address merely because an academic affiliation is stated. The final public disclosure set depends on the actual Austrian MedienG/ECG classification and must use facts the operator has explicitly approved for publication.

## Current deployment

Climate Analyzer is currently deployed at:

```text
https://building-climate-analyzer.streamlit.app/
```

The host is **Streamlit Community Cloud**. Current Streamlit documentation states that Community Cloud applications are hosted in the United States and that this location is not configurable.

Streamlit also documents that Community Cloud overrides contrary application configuration and sets:

```toml
[browser]
gatherUsageStats = true
```

Therefore the repository's local/self-hosted `gatherUsageStats = false` setting must **not** be interpreted as disabling Community Cloud platform analytics or telemetry.

Provider references reviewed on 2026-09-10 include Streamlit Community Cloud status/trust/privacy documentation and Snowflake's current Privacy Notice / Data Privacy Framework material.

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

Reproducible anonymous-browser audits of the live Community Cloud deployment on **2026-09-10**, including the post-`WEB-0.9.1` replay, observed provider-controlled requests before any Climate Analyzer map interaction to domains including:

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

The application source does not add Google Analytics, Google Tag Manager, Segment, Heap or advertising code itself. These requests occur in the **Community Cloud hosting/wrapper layer**, but they remain part of the actual experience of a visitor to the deployed URL.

The post-`WEB-0.9.1` audit also observed the following Streamlit-platform HTTP responses on both desktop and mobile:

```text
403  /api/v1/app/event/open
404  /api/v2/user/details
404  /api/v2/user/details
```

Climate Analyzer defines none of these endpoints. There were no failed browser requests, no uncaught page errors and the UI rendered successfully, so these responses are classified as Community Cloud wrapper/session/telemetry behavior rather than application API failures.

## Cookies and browser storage observed live

No cookie values are retained in the project audit evidence. Anonymous production sessions observed cookie names including:

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

This is an engineering inventory, not a legal classification of each identifier. However, Austrian Datenschutzbehörde guidance on § 165(3) TKG 2021 states that terminal storage/access which is not technically necessary for a service requested by the user generally requires prior consent. The current Community Cloud wrapper initiates analytics-associated storage/network activity before Building Energy Tools application code can present or process a project-level consent choice.

Accordingly, **an in-app consent banner would not by itself close this hosting-level issue**, because it executes after the outer Community Cloud layer has already started.

## Current hosting/privacy gate

For engineering release governance, the present decision is:

```text
STREAMLIT_COMMUNITY_CLOUD_TECHNICAL_BETA_RUNTIME       ACCEPTED
STREAMLIT_COMMUNITY_CLOUD_PUBLICATION_PRIVACY_GATE     OPEN
PUBLIC_PROMOTION_CLEARANCE                             BLOCKED
```

The blocker can be resolved only after one of the following is established for the final deployment:

1. a defensible legal/provider-control basis for the provider-controlled analytics/storage behavior, including any consent requirements; or
2. a promoted production runtime/hosting architecture in which Building Energy Tools can control non-essential storage/analytics before they occur.

This is deliberately fail-closed. It is not a conclusion that Streamlit Community Cloud itself is unlawful; it is a conclusion that the project does not currently possess enough control/evidence to declare its own Austrian/EU publication gate closed.

## Streamlit public-session bootstrap

An unauthenticated request to the custom Streamlit subdomain redirects through Streamlit's Community Cloud session/bootstrap layer before the application frame is rendered. The live audit observes Streamlit session and CSRF cookies during this process.

This occurs for an anonymous public app session and must not be described as the application having no platform-level session identifiers.

## External map resources

The station-selection interface uses an OpenStreetMap-based interactive map through Folium/Leaflet. When the user explicitly chooses `Find climate`, browser requests can be made to external map/component infrastructure including `tile.openstreetmap.org` and supporting JavaScript/CDN resources. Ordinary connection metadata such as IP address, timestamp, requested resource and user-agent information may therefore be transmitted to those providers.

`WEB-0.8.1` replaced the previous eager `st.tabs()` implementation with conditional rendering. **Post-merge production browser audits now confirm that no OpenStreetMap request occurs before explicit `Find climate` selection on either desktop or mobile.** This remediation is closed.

The live map displays visible OpenStreetMap attribution linking to the OSM copyright page.

## International transfers / provider transparency

Community Cloud documentation states that all Community Cloud apps are hosted in the United States. Streamlit's privacy policy points to Snowflake's privacy framework. Snowflake's current privacy material states that personal information may be processed outside the user's country, including primarily in the United States, and describes safeguards including the EU-U.S. Data Privacy Framework and, where applicable, Standard Contractual Clauses or other recognized mechanisms.

This completes the **engineering transparency inventory** for the provider transfer mechanism. It does **not** by itself determine the correct legal basis for Building Energy Tools' use of the provider or eliminate the separate consent/storage question described above.

## Server logs and provider processing

Hosting and infrastructure providers may process technical connection/log data needed to operate, secure and analyze their services. Streamlit Community Cloud also provides app analytics; public app viewers are represented in its analytics system according to Streamlit's documented behavior.

Building Energy Tools does not control all platform-level logging or telemetry performed by Streamlit/Snowflake. A future static-site or replacement runtime host requires a separate inventory of its own logging, cookies and data transfers.

## Your data-protection rights

Where the GDPR applies to processing for which the project operator is the controller, data subjects may have rights including access, rectification, erasure, restriction, objection and data portability, subject to the conditions and exceptions in applicable law. They may also have the right to lodge a complaint with a competent supervisory authority.

GDPR Article 13 requires, among other information depending on the processing, the controller's identity/contact details, processing purposes and legal basis. Final approved contact/disclosure details are therefore still required before this draft can function as a complete public transparency notice.

## Publication gate

The current live deployment evidence does **not** clear the project for public promotion. The remaining privacy/publication tasks are now narrower than in the first beta audit:

- approve only the controller/disclosure information that is intended and legally required for publication;
- confirm the applicable Austrian MedienG/ECG classification for the final project facts;
- resolve the Community Cloud pre-consent analytics/storage control issue or migrate the promoted runtime;
- perform the remaining manual keyboard/focus/zoom accessibility review;
- select a software licence before describing the project as open-source;
- audit the static website host when it is deployed.

The earlier post-remediation network, OSM, automated accessibility and CPU/memory gates are now closed and must not be listed as outstanding blockers.

## Revision

WEB-1.0 publication-readiness reconciliation: **2026-09-10 / Climate Analyzer 0.1.0-beta.1 candidate**.

This notice must be reviewed whenever hosting, analytics, authentication, external resources, file persistence, contact forms or other data-processing behavior changes.
