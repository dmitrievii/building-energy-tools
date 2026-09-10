# Public beta publication checklist

Status: **PUBLICATION BLOCKED — LIVE DEPLOYMENT EXISTS, PUBLIC PROMOTION NOT CLEARED**

This is an engineering release gate, not legal advice. A publicly reachable Streamlit deployment exists, so unresolved publication/privacy items must not be treated as theoretical pre-deployment tasks.

## Gate A — owner / disclosure information

- [x] Project owner name: **Ivan Dmitriev**.
- [x] Project purpose: independent research and teaching tools for building physics, climate analysis and building performance.
- [x] Austrian disclosure baseline rechecked against current official sources on 2026-09-10.
- [ ] Confirm whether the final publication facts qualify as a `kleine Website` under Austrian MedienG § 25 or require the broader disclosure set.
- [ ] Approve the public `Wohnort/Sitz` disclosure required for the applicable MedienG website category.
- [ ] Determine whether the actual project model falls within the ECG definition of a `Dienst der Informationsgesellschaft`; the project is currently free and carries no project-added advertising, so ECG § 5 must not be assumed solely from the fact that a website exists.
- [ ] If ECG § 5 applies to the final facts, approve the **geographic address** of establishment and a public electronic contact address required by that regime.
- [ ] Produce and publish the final deployment-specific Offenlegung / legal notice after the previous items are resolved.

**Do not substitute the TU Graz postal address for the project owner's address unless that use has a valid basis and has been approved.**

Official Austrian guidance distinguishes website disclosure under MedienG from other legal information duties. For a `kleine Website`, the government guidance identifies the media owner's name/company, subject/purpose and residence/seat as the reduced disclosure set. Additional duties can apply depending on content and commercial facts.

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
- [x] Streamlit Community Cloud US hosting and `gatherUsageStats = true` platform override reconfirmed from current provider documentation on 2026-09-10.
- [x] Live anonymous-browser inventory captured for cookies, local storage, network domains and third-party resources; no cookie values retained.
- [x] Post-`WEB-0.8.1` network/privacy replay completed: no OpenStreetMap request occurs before explicit `Find climate` selection.
- [x] Provider international-transfer transparency reviewed at engineering level: Streamlit points to Snowflake's privacy framework; Snowflake documents US processing plus transfer safeguards including the EU-U.S. Data Privacy Framework and, where applicable, SCC/other lawful mechanisms. **This records provider transparency only and does not itself establish the project's legal basis.**
- [ ] Add final controller/contact disclosure fields to the privacy notice.
- [ ] Resolve the legal-basis/consent question for provider-controlled analytics/cookies/storage observed before the application can obtain project-level consent. Austrian DSB guidance states that technically non-essential terminal storage/access generally requires prior consent under § 165(3) TKG 2021.
- [ ] Decide the production-hosting response to the previous blocker: obtain a defensible provider/legal-control basis, or migrate the promoted public runtime to hosting where Building Energy Tools can control pre-consent analytics/storage.
- [ ] If the static website is deployed separately, inventory that host's actual logging/cookie/data-transfer behavior and reconcile the privacy notice before promotion.

### Current hosting privacy decision

`Streamlit Community Cloud` remains acceptable as a **technical beta runtime**, but the project does **not** treat the current deployment as privacy/publication-cleared for Austrian/EU public promotion. The live browser observes analytics-associated cookies/storage and Google/Heap/Segment infrastructure before any Building Energy Tools UI can collect consent. An application-level consent banner inside Streamlit would therefore not prevent the Community Cloud wrapper's earlier processing.

## Gate D — methodology, UX and accessibility

- [x] Tool methodology and limitations are documented.
- [x] Data-source provenance is documented separately from scientific validation.
- [x] Beta status does not imply regulatory approval, certification or universal validation.
- [x] Engineering disclaimer is defined centrally.
- [x] Automated live desktop viewport audit completed at 1440 × 1000 with no horizontal overflow and no uncaught page error.
- [x] Automated live mobile viewport audit completed at 390 × 844 with no horizontal overflow and no uncaught page error.
- [x] Axe WCAG A/AA scan executed in the actual Streamlit app frame; findings classified into application-remediable and Streamlit-framework items.
- [x] `WEB-0.9.1` post-merge live axe replay completed: desktop violation groups reduced from 3 to 2 and the application-visible file-uploader `color-contrast` finding is closed in production.
- [x] Remaining reproducible automated accessibility findings are recorded as Streamlit-framework limitations rather than silently claimed as application conformance.
- [ ] Perform a manual keyboard/focus/200% zoom review before public promotion; automated axe evidence does not replace this check.

Current retained framework-level axe groups on both desktop and mobile:

1. `aria-allowed-attr` on Streamlit `.stSidebar` markup;
2. `button-name` on a Streamlit toolbar action button.

No claim of full WCAG conformance is made from the automated audit.

## Gate E — licensing and attribution

- [x] No blanket redistribution licence is claimed for Climate.OneBuilding weather datasets.
- [x] Station-catalog provenance is versioned and integrity checked.
- [x] No repository-wide open-source licence is implied merely because the repository is public.
- [x] Live OpenStreetMap attribution was detected after opening `Find climate`, including a link to the OSM copyright page.
- [x] Post-remediation production replay confirms OSM/map resources are **not** requested before explicit `Find climate` selection.
- [ ] Select and approve a software licence before describing the project as open-source software.

## Gate F — release metadata and operations

- [x] Candidate version: `0.1.0-beta.1`.
- [x] Candidate channel: `public-beta-candidate`.
- [x] Machine-readable release identity exists.
- [x] First live availability/browser evidence recorded in `deployment/LIVE_AUDIT_2026-09-10.md`.
- [x] Streamlit CPU-throttle state observed by the operator and classified as an infrastructure/resource event rather than a scientific calculation failure.
- [x] `WEB-0.9` CPU/memory review completed with repeated measurements. Median default landing render improved from 1.323783 s to 0.429831 s (−67.5%); AppTest max RSS median fell from 188446 kB to 71280 kB (−62.2%). No rerun-speed improvement is claimed.
- [x] Post-`WEB-0.9.1` production browser replay completed successfully: no throttle banner for the anonymous viewer, no horizontal overflow, no uncaught page errors, no eager OSM request, and the application-owned contrast finding remains closed.
- [ ] Change publication status from `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED` only after the remaining Gates A–E are resolved for the actual deployment.

## Current blocking set after WEB-0.9.1

The engineering/runtime work is no longer the publication bottleneck. The remaining blocking set is:

1. **Owner disclosure/contact facts** — approve only the information that will actually be published; do not infer or expose a private address from project metadata.
2. **Austrian legal classification** — confirm the applicable MedienG website category and whether ECG § 5 applies to the final non-commercial/commercial facts.
3. **Provider-controlled cookies/telemetry** — resolve the § 165(3) TKG 2021 consent/control issue for the current Community Cloud wrapper or change production hosting.
4. **Manual accessibility review** — keyboard, focus and 200% zoom.
5. **Software licence** — required before marketing the repository/tool as open-source.
6. **Static website host audit** — required once that host is selected/deployed.

Until these are closed:

```text
PUBLICATION_STATUS = BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

## Legal/reference baseline reviewed 2026-09-10

The checklist is maintained against the current Austrian Mediengesetz §§ 24–25, E-Commerce-Gesetz §§ 3 and 5, Telekommunikationsgesetz 2021 § 165(3), Austrian government website guidance, Austrian Datenschutzbehörde cookie guidance, GDPR transparency requirements, TU Graz website/corporate-design constraints, current Streamlit Community Cloud documentation, Snowflake privacy/transfer documentation, and actual live-browser evidence from the deployed application.

Applicable duties depend on the facts of the final publication. Recheck the sources if the commercial status, operator, host, domain, analytics, authentication, advertising or institutional relationship changes.
