# Public beta publication checklist

Status: **PUBLICATION BLOCKED UNTIL REQUIRED IDENTITY / CONTACT FIELDS ARE APPROVED**

This is an engineering release gate, not legal advice. It records information that must be resolved before the website and Climate Analyzer are intentionally promoted as a public beta.

## Gate A — owner / disclosure information

- [x] Project owner name: **Ivan Dmitriev**.
- [x] Project purpose: independent research and teaching tools for building physics, climate analysis and building performance.
- [ ] Approve the geographic address / public establishment address to be used where legally required.
- [ ] Approve a public electronic contact address.
- [ ] Confirm whether the final deployment is treated as a personal/non-commercial publication, an information service, or another category for the applicable Austrian disclosure duties.
- [ ] Produce the final deployment-specific Impressum / Offenlegung after the previous items are resolved.

**Do not substitute the TU Graz postal address for the project owner's address unless that use has a valid basis and has been approved.**

## Gate B — academic affiliation and branding

- [x] Affiliation is factual text only: `Institute of Buildings and Energy, Graz University of Technology`.
- [x] Independence notice states that the project is not an official TU Graz website/service/product.
- [x] No TU Graz logo is required by the project identity.
- [ ] If TU Graz logo, corporate design, institutional domain or stronger institutional claims are introduced later, obtain the required institutional approval before publication.

## Gate C — privacy and hosting

- [x] Application code does not add advertising, Google Analytics or tracking pixels.
- [x] User EPW uploads are processed in the Streamlit application session and are not intentionally written by Building Energy Tools to persistent project storage.
- [x] Climate.OneBuilding EPW files are downloaded on demand and are not bundled in the repository.
- [x] External map/data providers are identified in the privacy draft.
- [x] Streamlit Community Cloud is identified as the intended beta application host.
- [ ] Add final controller contact details to the privacy notice.
- [ ] Verify the deployed application's actual cookies, local storage, network requests and third-party resources in a browser before publication.
- [ ] Reconcile the privacy notice with the final hosting configuration and provider terms at deployment time.
- [ ] If the static website is deployed separately, add that host's actual logging/cookie/data-transfer behavior to the website privacy notice.

## Gate D — methodology and claims

- [x] Tool methodology and limitations are documented.
- [x] Data-source provenance is documented separately from scientific validation.
- [x] Beta status does not imply regulatory approval, certification or universal validation.
- [x] Engineering disclaimer is defined centrally.
- [ ] Perform browser-level responsive/accessibility review before public promotion.

## Gate E — licensing and attribution

- [x] No blanket redistribution licence is claimed for Climate.OneBuilding weather datasets.
- [x] Station-catalog provenance is versioned and integrity checked.
- [x] No repository-wide open-source licence is implied merely because the repository is public.
- [ ] Select and approve a software licence before describing the project as open-source software.
- [ ] Confirm final map attribution rendering and all third-party notices in the deployed interface.

## Gate F — release metadata

- [x] Candidate version: `0.1.0-beta.1`.
- [x] Candidate channel: `public-beta-candidate`.
- [x] Machine-readable release identity exists.
- [ ] Change publication status from `BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED` only after Gates A–E are resolved for the actual deployment.

## Legal/reference baseline reviewed 2026-09-10

The checklist was prepared against the then-current Austrian Mediengesetz §§ 24–25, E-Commerce-Gesetz § 5, Austrian government website guidance, GDPR transparency requirements, TU Graz website/corporate-design guidance, and the intended Streamlit Community Cloud deployment model.

Applicable duties depend on the facts of the final publication. Recheck the sources if the commercial status, operator, host, domain, analytics, authentication, advertising or institutional relationship changes.
