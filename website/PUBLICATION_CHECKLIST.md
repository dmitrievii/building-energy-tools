# Public beta publication checklist

Status: **PUBLICATION BLOCKED — LIVE DEPLOYMENT EXISTS, PUBLIC PROMOTION NOT CLEARED**

This is an engineering release gate, not legal advice. A publicly reachable Streamlit deployment now exists, so unresolved publication/privacy items must not be treated as theoretical pre-deployment tasks.

## Gate A — owner / disclosure information

- [x] Project owner name: **Ivan Dmitriev**.
- [x] Project purpose: independent research and teaching tools for building physics, climate analysis and building performance.
- [ ] Approve the geographic address / public establishment address to be used where legally required.
- [ ] Approve a public electronic contact address.
- [ ] Confirm the applicable Austrian disclosure/legal classification for the actual publication facts.
- [ ] Produce and publish the final deployment-specific Impressum / Offenlegung after the previous items are resolved.

**Do not substitute the TU Graz postal address for the project owner's address unless that use has a valid basis and has been approved.**

## Gate B — academic affiliation and branding

- [x] Affiliation is factual text only: `Institute of Buildings and Energy, Graz University of Technology`.
- [x] Independence notice states that the project is not an official TU Graz website/service/product.
- [x] No TU Graz logo is required by the project identity.
- [ ] If TU Graz logo, corporate design, institutional domain or stronger institutional claims are introduced later, obtain the required institutional approval before publication.

## Gate C — privacy and hosting

- [x] Application source does not add advertising, Google Analytics, Google Tag Manager, Segment or Heap code itself.
- [x] User EPW uploads are processed in the Streamlit application session and are not intentionally written by Building Energy Tools to persistent project storage.
- [x] Climate.OneBuilding EPW files are downloaded on demand and are not bundled in the repository.
- [x] Actual beta host confirmed: **Streamlit Community Cloud** at `https://building-climate-analyzer.streamlit.app/`.
- [x] Streamlit Community Cloud US hosting and `gatherUsageStats = true` platform override recorded from current provider documentation.
- [x] Live anonymous-browser inventory captured for cookies, local storage, network domains and third-party resources; no cookie values retained.
- [x] Privacy draft reconciled with the observed Streamlit platform analytics/session behavior.
- [ ] Add final controller contact details to the privacy notice.
- [ ] Determine the applicable legal basis and, where required, consent mechanism for provider-controlled analytics/cookies/storage observed on the live deployment.
- [ ] Review international-transfer/provider transparency information for the actual US-hosted deployment.
- [ ] Repeat privacy/network inventory after `WEB-0.8.1` lazy map remediation is deployed to `main`.
- [ ] If the static website is deployed separately, add that host's actual logging/cookie/data-transfer behavior to the website privacy notice.

## Gate D — methodology, UX and accessibility

- [x] Tool methodology and limitations are documented.
- [x] Data-source provenance is documented separately from scientific validation.
- [x] Beta status does not imply regulatory approval, certification or universal validation.
- [x] Engineering disclaimer is defined centrally.
- [x] Automated live desktop viewport audit completed at 1440 × 1000 with no horizontal overflow and no uncaught page error.
- [x] Automated live mobile viewport audit completed at 390 × 844 with no horizontal overflow and no uncaught page error.
- [x] Axe WCAG A/AA scan executed in the actual Streamlit app frame; findings classified into application-remediable and Streamlit-framework items.
- [ ] Re-run axe/browser audit after `WEB-0.8.1` contrast/toolbar remediation is live and confirm the application-owned contrast finding is closed.
- [ ] Perform a manual keyboard/focus/zoom review before public promotion; automated axe evidence does not replace this check.
- [ ] Record any retained Streamlit-framework accessibility limitations in the final public limitations/accessibility note if they remain reproducible.

## Gate E — licensing and attribution

- [x] No blanket redistribution licence is claimed for Climate.OneBuilding weather datasets.
- [x] Station-catalog provenance is versioned and integrity checked.
- [x] No repository-wide open-source licence is implied merely because the repository is public.
- [x] Live OpenStreetMap attribution was detected after opening `Find climate`, including a link to the OSM copyright page.
- [x] Pre-remediation eager OSM loading was identified and a conditional-rendering remediation prepared in `WEB-0.8.1`.
- [ ] Verify after deployment that OSM/map resources are not requested before explicit `Find climate` selection.
- [ ] Select and approve a software licence before describing the project as open-source software.

## Gate F — release metadata and operations

- [x] Candidate version: `0.1.0-beta.1`.
- [x] Candidate channel: `public-beta-candidate`.
- [x] Machine-readable release identity exists.
- [x] First live availability/browser evidence recorded in `deployment/LIVE_AUDIT_2026-09-10.md`.
- [x] Streamlit CPU-throttle state observed by the operator and classified as an infrastructure/resource event rather than a scientific calculation failure.
- [ ] Complete a CPU/memory/resource-efficiency review before deciding whether higher Community Cloud limits are necessary.
- [ ] Change publication status from `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED` only after the remaining Gates A–E are resolved for the actual deployment.

## Legal/reference baseline reviewed 2026-09-10

The checklist was prepared against the then-current Austrian Mediengesetz §§ 24–25, E-Commerce-Gesetz § 5, Austrian government website guidance, GDPR transparency requirements, TU Graz website/corporate-design guidance, current Streamlit Community Cloud documentation, and actual live-browser evidence from the deployed application.

Applicable duties depend on the facts of the final publication. Recheck the sources if the commercial status, operator, host, domain, analytics, authentication, advertising or institutional relationship changes.
