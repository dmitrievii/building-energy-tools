# Privacy information — public beta draft

**Status:** deployment draft. Controller contact details and the final host/network audit must be completed before public promotion.

## Controller

Project operator: **Ivan Dmitriev**.

Public geographic/contact address and public electronic contact address: **to be approved before publication**.

Do not publish this draft as a final privacy notice until those fields and the actual deployment configuration have been verified.

## What Building Energy Tools intentionally processes

### EPW uploads

If you upload an EnergyPlus Weather (EPW) file to Climate Analyzer, the file is transmitted from your browser to the Streamlit application backend so the application can parse and analyze it.

The Building Energy Tools application code keeps the active EPW payload in the current Streamlit session. It does not intentionally write uploaded EPW files to a project database or persistent project storage.

Do not upload EPW files containing confidential or personal information in custom metadata fields.

### Climate.OneBuilding selections

If you select an online station, Climate Analyzer uses the reviewed station metadata stored with the application and requests the selected EPW archive from Climate.OneBuilding on demand. The weather payload is processed by the application for the active analysis session; Climate.OneBuilding EPW files are not committed to the Building Energy Tools repository.

## Hosting provider

The intended beta application host is **Streamlit Community Cloud**, operated within the Streamlit/Snowflake service environment.

The application code does not add Google Analytics, advertising networks or tracking pixels. This does not mean that the hosting platform performs no technical or usage processing. Streamlit Community Cloud provides platform analytics and logging and is subject to the provider's privacy notice.

At the time this draft was prepared, Streamlit documentation stated that Community Cloud apps are hosted in the United States. This fact must be rechecked when the actual beta deployment is created.

Provider information:

- Streamlit Community Cloud documentation: https://docs.streamlit.io/deploy/streamlit-community-cloud
- Streamlit privacy information: https://streamlit.io/privacy-policy

## Uploaded-file lifecycle

Streamlit documents `st.file_uploader` uploads as being transferred to the backend and held in memory rather than automatically written to disk. Climate Analyzer additionally stores the selected payload in Streamlit session state so it remains available while the user works with the application.

The application does not promise a precise platform-level deletion time beyond the behavior controlled by its own code. Users should clear/change the active climate or close their session when finished and should avoid uploading confidential data.

## External map resources

The station-selection interface uses an OpenStreetMap-based interactive map through Folium/Leaflet. Loading map tiles or related browser resources can cause the user's browser to contact external map infrastructure and transmit ordinary connection metadata such as IP address, timestamp, requested resource and user-agent information.

The exact tile provider/network calls must be confirmed in the final browser network audit before publication. Required OpenStreetMap attribution must remain visible in the deployed map.

## Server logs and platform analytics

Hosting and infrastructure providers may process technical connection/log data needed to operate, secure and analyze their services. Building Energy Tools does not control all platform-level logging performed by Streamlit/Snowflake or by a future static-site host.

The final public privacy notice must identify the actual deployment providers and data flows rather than relying only on this repository design document.

## Cookies and browser storage

Building Energy Tools application code does not intentionally add advertising or marketing cookies. Streamlit, map components and the final hosting layer may use technically necessary cookies, browser storage or other platform mechanisms.

Before public release, inspect the deployed application in a clean browser session and update this notice with the observed behavior and the applicable legal basis/consent mechanism where required.

## Your data-protection rights

Where the GDPR applies to processing for which the project operator is the controller, data subjects may have rights including access, rectification, erasure, restriction, objection and data portability, subject to the conditions and exceptions in applicable law. They may also have the right to lodge a complaint with a competent supervisory authority.

Final controller contact details must be present before this section can function as a usable Article 13 transparency notice.

## Revision

Draft baseline: **2026-09-10 / Climate Analyzer 0.1.0-beta.1 candidate**.

This notice must be reviewed whenever hosting, analytics, authentication, external resources, file persistence, contact forms or other data-processing behavior changes.
