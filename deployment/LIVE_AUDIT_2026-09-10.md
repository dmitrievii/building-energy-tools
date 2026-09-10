# Climate Analyzer live deployment audit — 2026-09-10

Target: `https://building-climate-analyzer.streamlit.app/`

This document records the first reproducible live-deployment audit of Climate Analyzer on Streamlit Community Cloud. It is engineering evidence, not legal advice and not a declaration of publication clearance.

> **Follow-up correction:** the first audit correctly detected a desktop `color-contrast` violation group but initially described it too broadly as landing-page caption text. A later exact production DOM probe identified the violating node as Streamlit's generated file-uploader hint `10MB per file • EPW`, with computed foreground `rgba(49, 51, 63, 0.6)`. The measured first-audit result is retained; only the attribution is corrected. WEB-0.9.1 subsequently closed this finding in production. See `deployment/LIVE_AUDIT_WEB_0_9_1_2026-09-10.md`.

## Deployment under test

The live application was deployed from the `main` branch after `WEB-0.8` deployment-readiness work. The first audited production baseline was commit:

```text
daa6b577e19a817be18b1e56d8c72b53fc9858f7
```

The operator separately observed the Streamlit Community Cloud notice:

```text
Your app has been throttled
Your app is still running, but we've temporarily reduced its CPU...
```

with a platform-reported expiry on 2026-09-10 at 23:07:28 local time. The anonymous automated browser did not see this developer-facing throttle notice.

## Availability / session bootstrap

A first unauthenticated request to the custom Streamlit subdomain returned HTTP `303` to Streamlit's `share.streamlit.io/-/auth/app` session bootstrap. This is part of the Community Cloud front-door/session flow.

When redirects were followed with a cookie jar, the root application URL returned HTTP `200` after three redirects. Two independent probes measured approximately:

- 1.14 s total for the first successful session-aware root request;
- 1.53 s total for a later successful session-aware root request.

The external `/_stcore/health` path must **not** be treated as equivalent to the local CI health endpoint. Through the Community Cloud front door it participates in the same session/bootstrap routing and, after session creation, can return the Community Cloud HTML shell rather than the local plain `ok` response. Live availability is therefore evidenced primarily by browser navigation and successful rendering of the app frame.

## Browser rendering

A frame-aware headless Chrome audit used Chrome 152 and tested:

- desktop: 1440 × 1000;
- mobile: 390 × 844.

Results against the live deployment:

| Check | Desktop | Mobile |
|---|---:|---:|
| Final browser navigation HTTP | 200 | 200 |
| Climate Analyzer app frame detected | PASS | PASS |
| Time to detect app text | 3.027 s | 2.621 s |
| Horizontal page overflow | 0 px | 0 px |
| Uncaught page errors | 0 | 0 |
| `Find climate` interaction | PASS | PASS |
| OSM attribution after opening map | PASS | PASS |

The actual Streamlit app content was rendered inside:

```text
https://building-climate-analyzer.streamlit.app/~/+/
```

The outer Community Cloud page and Streamlit application frame are therefore distinct audit layers.

## Network findings

Before any Climate Analyzer map selection, the Community Cloud platform caused browser requests to several Streamlit/analytics/status domains. Observed domains included:

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
avatars.githubusercontent.com
```

After `Find climate` was opened, the map additionally used third-party map/component resources including:

```text
tile.openstreetmap.org
cdn.jsdelivr.net
cdnjs.cloudflare.com
code.jquery.com
netdna.bootstrapcdn.com
```

The OpenStreetMap component displayed a visible `OpenStreetMap` attribution link to `https://www.openstreetmap.org/copyright`.

Two HTTP `404` responses were observed for:

```text
/api/v2/user/details
```

The Climate Analyzer code defines no such API endpoint; these requests belong to the Community Cloud wrapper/session UI. They did not prevent the app from rendering and produced no uncaught page error.

A later post-WEB-0.9.1 replay additionally observed a platform `403` on `/api/v1/app/event/open`; all three wrapper responses remained non-fatal with zero failed browser requests and zero uncaught page errors. See the closure audit for the final classification.

## Cookies and browser storage

The audit stores no cookie values. The following cookie names were observed during an anonymous public session:

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

Observed local-storage keys included:

```text
ajs_anonymous_id
appSessionId-<generated-id>
appSessionId-undefined
machineId
stMetricsConfig
```

No `sessionStorage` keys were observed in the audited sessions.

This evidence confirms that a public Community Cloud deployment has provider-controlled session, analytics and telemetry behavior beyond the application code. Repository setting `[browser] gatherUsageStats = false` must not be represented as disabling Community Cloud telemetry because Community Cloud overrides that setting.

## OpenStreetMap eager-load finding

The pre-remediation source page used:

```python
st.tabs(["Upload EPW", "Find climate"])
```

Streamlit executes both tab bodies. The first live browser audit consequently observed an OpenStreetMap tile request before explicit `Find climate` selection in the mobile run; desktop timing did not catch the same request before its sampling point, although the inactive map component was already created.

`WEB-0.8.1` remediated this by replacing the eager tabs with a conditional source selector. Subsequent production audits confirm that no OpenStreetMap request occurs before explicit `Find climate` selection on either desktop or mobile.

## Accessibility findings

Axe WCAG A/AA testing was run in the actual Streamlit app frame, not only in the outer Community Cloud shell.

The first audit reported three desktop violation groups:

1. `aria-allowed-attr` on `.stSidebar` — Streamlit-generated framework markup;
2. `button-name` on a Streamlit toolbar action button — Streamlit-generated framework/platform control;
3. `color-contrast` — application-visible landing content requiring remediation.

**Corrected attribution for item 3:** a later exact DOM probe showed that the violating text was the Streamlit-generated file-uploader hint `10MB per file • EPW`, not the project's sidebar/release caption. Its computed foreground used 0.6 alpha while the surrounding uploader instruction container used the full theme text color.

WEB-0.9.1 applies a stable test-id-based, theme-safe `color: inherit` override. The post-merge production replay reports 2 groups on desktop and 2 on mobile; the `color-contrast` group is gone. The application-owned automated contrast finding is closed.

The remaining two findings are retained as Streamlit framework/platform limitations. Manual keyboard, focus and 200% zoom review remains open.

## Throttling interpretation

The operator-visible throttle notice is a Streamlit Community Cloud resource-control state, not a scientific calculation failure. During the first throttle-period audit the anonymous browser still reached and rendered Climate Analyzer in roughly three seconds.

This did **not** by itself prove optimal resource efficiency. WEB-0.9 therefore performed a separate repeated CPU/memory startup review. Its controlled AppTest measurements reduced median first landing render from 1.323783 s to 0.429831 s (−67.5%) and median maximum RSS from 188446 kB to 71280 kB (−62.2%). See `deployment/RUNTIME_PERFORMANCE_2026-09-10.md`.

## Historical gate status after the first live audit

The following block records the state **at the time of the first audit**, before WEB-0.8.1/0.9/0.9.1 live closure:

```text
LIVE_APP_REACHABLE                         PASS
DESKTOP_INITIAL_RENDER                    PASS
MOBILE_INITIAL_RENDER                     PASS
HORIZONTAL_OVERFLOW                       PASS (0 px)
FIND_CLIMATE_INTERACTION                  PASS
OSM_VISIBLE_ATTRIBUTION                   PASS
UNCAUGHT_PAGE_ERRORS                      PASS (0)
PROVIDER_ANALYTICS/STORAGE_INVENTORY      CAPTURED
OSM_PRIVACY_BY_DEFAULT                    REMEDIATION_PENDING_LIVE_REPLAY
APP_CONTRAST_FINDING                      REMEDIATION_PENDING_LIVE_REPLAY
STREAMLIT_FRAMEWORK_ARIA                  OPEN_UPSTREAM_LIMITATION
RESOURCE_THROTTLE                         OBSERVED_BY_OPERATOR / PERFORMANCE_REVIEW_REQUIRED
PUBLICATION_CLEARANCE                     BLOCKED
```

## Current follow-up status

After WEB-0.8.1, WEB-0.9 and WEB-0.9.1 production replay:

```text
OSM_PRIVACY_BY_DEFAULT                    PASS
APP_UPLOADER_HINT_CONTRAST                PASS / CLOSED_LIVE
WEB_0_9_RUNTIME_PERFORMANCE               PASS
STREAMLIT_FRAMEWORK_ACCESSIBILITY         OPEN_UPSTREAM_LIMITATIONS
MANUAL_KEYBOARD_FOCUS_ZOOM                OPEN
PROVIDER_ANALYTICS_CONSENT_CONTROL        OPEN / PUBLICATION_BLOCKER
OWNER_DISCLOSURE_CLASSIFICATION           OPEN / PUBLICATION_BLOCKER
PUBLICATION_CLEARANCE                     BLOCKED
```

The project remains `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED` until the remaining disclosure, privacy/hosting, manual accessibility, licensing and final-host gates are resolved.
