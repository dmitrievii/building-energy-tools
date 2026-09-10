# Publication policy

## Project identity

**Building Energy Tools** is an independent personal research and teaching project maintained by **Ivan Dmitriev**.

The first interactive application is **Climate Analyzer**, a research and teaching aid for climate-data exploration, building-physics education and early building-performance / passive-design analysis.

## Academic affiliation

The project may state the following factual biographical affiliation:

> Academic affiliation: Institute of Buildings and Energy, Graz University of Technology.

The affiliation is contextual information about the author. It does **not** make Building Energy Tools or Climate Analyzer an official TU Graz website, service, product or endorsed software package.

Unless separately approved, the project must not:

- use the TU Graz logo or imitate TU Graz corporate design;
- use a domain that implies an official TU Graz service;
- describe the application as a TU Graz product, platform or institutional service;
- use TU Graz names or marks to advertise unrelated commercial products or services.

## Public wording

Canonical independence notice:

> Independent personal research and teaching project. Academic affiliation is stated for biographical context only; this is not an official website, service or product of Graz University of Technology.

Canonical engineering disclaimer:

> Climate Analyzer is a research and teaching aid for climate-data exploration and early design support. Outputs are not a substitute for project-specific engineering judgement, regulatory verification, certification or professional design responsibility.

## Release identity

The first publication candidate is:

```text
Climate Analyzer 0.1.0-beta.1
channel: public-beta-candidate
status: BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

Machine-readable/public runtime identity is defined in:

```text
tools/climate_analyzer/epw_climate_analyzer/release_info.py
```

A beta label means only that the technical/scientific gates explicitly recorded as passed in the repository have passed for their declared scope. It does **not** mean every result has been validated for every climate file, every design use case or every jurisdiction, and it does not override open publication/privacy/legal gates.

## Licensing status

No repository-wide open-source licence is declared by this stage. Public availability of source code must not be described as granting unrestricted reuse rights.

A software licence must be selected explicitly in a later release decision. Third-party data, libraries, maps and upstream weather datasets retain their own terms and attribution requirements independently of the future code licence.

## Austrian disclosure classification

This policy does not assume that every Austrian website is automatically subject to the same set of disclosure fields.

Current official Austrian guidance distinguishes website disclosure under the Mediengesetz from other information duties and differentiates between `kleine Website` and broader disclosure cases based on the actual content. For a `kleine Website`, the government guidance identifies a reduced set including the media owner's name/company, subject/purpose and residence/seat.

The E-Commerce-Gesetz separately defines a `Dienst der Informationsgesellschaft` as a service normally provided for remuneration. Building Energy Tools is currently planned as a free independent research/teaching project without project-added advertising. Therefore the applicability of ECG § 5 must be resolved from the final facts rather than assumed merely because the project is online.

The repository must not publish a private address or TU Graz address by inference. Any public residence/seat, geographic address or electronic contact field must be deliberately approved for the applicable regime.

## Hosting and privacy control

The current technical beta runtime is hosted on Streamlit Community Cloud. Current provider documentation states that Community Cloud apps are hosted in the United States and that Community Cloud overrides application configuration with `browser.gatherUsageStats = true`.

Live production browser evidence also records provider-controlled analytics/session requests and identifiers before Building Energy Tools application code can present a consent choice. Austrian DSB guidance on § 165(3) TKG 2021 states that terminal storage/access which is not technically necessary for the requested service generally requires prior consent.

For project governance, this creates a **hosting-level publication blocker**. An in-app consent banner cannot be represented as preventive consent for processing that the outer hosting layer starts before the app UI runs.

The project therefore keeps these states separate:

```text
TECHNICAL_BETA_RUNTIME_ON_STREAMLIT     ACCEPTED
PUBLICATION_PRIVACY_CLEARANCE           OPEN
PUBLIC_PROMOTION                        BLOCKED
```

This policy does not declare Streamlit Community Cloud unlawful. It states only that Building Energy Tools does not currently have sufficient control/evidence to declare its own Austrian/EU public-promotion gate closed while the observed provider-controlled processing remains unresolved.

## Accessibility status

Automated production testing is part of the release evidence but is not a substitute for manual accessibility review.

The post-WEB-0.9.1 live audit closes the application-visible file-uploader contrast finding. Two retained axe groups belong to Streamlit framework/platform markup and are documented rather than hidden with brittle generated-class overrides.

A manual keyboard, focus-order and 200% zoom review remains required before public-promotion clearance. The current status is documented in `website/content/accessibility.md`.

## Publication legal status

This document is a project publication policy, not a legal opinion and not an Impressum/Offenlegung substitute.

Before public promotion, the actual deployment must pass `website/PUBLICATION_CHECKLIST.md`. Required owner/contact/address information must come from an intentionally approved public identity; it must not be invented or inferred from academic affiliation or private project metadata.

The publication gate remains fail-closed until the actual hosting, disclosure, consent/privacy, manual accessibility and licensing decisions are resolved.

## Source references reviewed for this policy

Reference baseline rechecked 2026-09-10:

- Austrian Mediengesetz, §§ 24–25 (RIS);
- Austrian E-Commerce-Gesetz, §§ 3 and 5 (RIS);
- Austrian Telekommunikationsgesetz 2021, § 165(3) (RIS);
- Austrian government guidance, `Die eigene Website`;
- Austrian Datenschutzbehörde guidance on cookies and terminal storage;
- GDPR Article 13 transparency requirements;
- Streamlit Community Cloud status, trust/security, analytics and privacy documentation;
- Snowflake Privacy Notice and Data Privacy Framework information;
- TU Graz homepage / corporate-design and name/branding guidance;
- reproducible live-browser evidence in `deployment/`.

These references are review inputs. The repository does not claim that this policy or checklist alone establishes legal compliance for a particular deployment.
