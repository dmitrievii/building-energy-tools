# Climate Analyzer browser / deployment audit

Stage: `WEB-0.8`

Status: **NOT EXECUTABLE UNTIL A LIVE DEPLOYMENT URL EXISTS**

This checklist is for evidence from the deployed application. Local Streamlit health checks do not substitute for these checks.

## A. Release identity

- [ ] Live page shows `Climate Analyzer`.
- [ ] Version `0.1.0-beta.1` is visible.
- [ ] Independent-project notice is visible/reachable.
- [ ] Engineering disclaimer is visible/reachable.
- [ ] No wording implies an official TU Graz service or certification.

## B. Responsive layout

Test at minimum:

- [ ] 360 × 800 px mobile portrait.
- [ ] 412 × 915 px larger mobile portrait.
- [ ] 768 × 1024 px tablet portrait.
- [ ] 1024 × 768 px tablet/compact landscape.
- [ ] 1440 × 900 px desktop.

For every viewport check:

- [ ] no horizontal page overflow;
- [ ] no clipped navigation labels;
- [ ] charts remain legible or intentionally scroll/zoom;
- [ ] tables remain usable;
- [ ] map controls do not cover station interactions;
- [ ] primary actions are visible without ambiguous wrapping;
- [ ] dialogs/expanders remain operable.

## C. Keyboard and basic accessibility

- [ ] All primary controls are reachable with keyboard only.
- [ ] Focus order follows reading/interaction order.
- [ ] Visible focus indication is not lost.
- [ ] Interactive controls have meaningful accessible names.
- [ ] Headings follow a coherent hierarchy.
- [ ] Information is not conveyed by colour alone where the app controls this.
- [ ] Text and essential chart annotations have adequate contrast where the app controls styling.
- [ ] Zoom to 200% does not make core workflows unusable.

This is a practical WCAG-oriented audit, not a claim of formal WCAG conformance or certification.

## D. Network / privacy evidence

Using browser developer tools, record all observed request domains while performing:

1. initial page load;
2. local EPW upload;
3. station-map interaction;
4. Climate.OneBuilding EPW download;
5. several analysis pages.

- [ ] Streamlit-host domains recorded.
- [ ] OpenStreetMap/tile domains recorded.
- [ ] Climate.OneBuilding requests recorded.
- [ ] Any unexpected third-party domains investigated.
- [ ] Cookies recorded with name, domain, purpose if determinable, expiry/session status and SameSite/Secure flags.
- [ ] localStorage/sessionStorage keys recorded.
- [ ] No project-added analytics/tracking request appears unexpectedly.
- [ ] Privacy notice reconciled against observed behaviour.

## E. Data source / attribution

- [ ] OpenStreetMap attribution is visible on every rendered OSM map.
- [ ] OSM attribution links remain functional.
- [ ] Climate.OneBuilding source/provenance is visible for provider-selected climate files.
- [ ] Current catalog version is exposed where designed.
- [ ] No claim implies that Building Energy Tools authored or owns third-party weather data.

## F. Functional smoke

- [ ] Upload a valid EPW.
- [ ] Reject an invalid/non-EPW upload.
- [ ] Load a provider climate.
- [ ] Overview renders.
- [ ] Temperature renders.
- [ ] Moisture/psychrometrics renders.
- [ ] Solar renders.
- [ ] Wind renders.
- [ ] Natural ventilation renders.
- [ ] Passive/HVAC page renders.
- [ ] Compare Climates renders.
- [ ] Data Quality renders.
- [ ] Changing climate returns to a stable navigation state.

## G. Performance / operational observations

- [ ] Cold-start behaviour recorded.
- [ ] Map loading behaviour recorded.
- [ ] Large but valid EPW near the configured upload bound tested.
- [ ] No unhandled exception appears in normal navigation.
- [ ] Streamlit build/runtime logs reviewed for warnings relevant to users or security.

## Closure

`WEB-0.8` browser audit can be marked complete only when the live URL, deployed SHA, screenshots/notes and all unresolved findings are recorded. Publication promotion additionally requires the separate legal/privacy gates in `website/PUBLICATION_CHECKLIST.md`.
