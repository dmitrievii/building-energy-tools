# Website

Public website layer for **Building Energy Tools**.

## Static website foundation

The website implementation lives in:

```text
website/site/
```

It is deliberately plain static HTML/CSS:

- no Node/React/Next.js build;
- no JavaScript requirement;
- no external fonts, CDN assets or project-added analytics;
- portable to an ordinary free static host;
- Climate Analyzer remains a separate Streamlit application.

Current information architecture:

```text
Home
Tools
Teaching
Research
Documentation
About

Support pages:
Privacy
Accessibility
Legal / disclosure
```

The static-layer machine-readable contract is:

```text
website/site/site-manifest.json
```

## Validation layers

Structural/static validation:

```text
python website/scripts/check_static_site.py
python -m unittest discover -s website/tests -p 'test_*.py' -v
```

GitHub Actions workflow:

```text
.github/workflows/website-ci.yml
```

The static CI checks required pages, semantic page basics, internal links, allowed external-link hosts, absence of external runtime assets, zero-JavaScript contract and a local HTTP route smoke test.

SITE-0.2 adds a second, browser-level layer:

```text
website/scripts/browser_audit.mjs
.github/workflows/website-browser-audit.yml
```

It renders every public route in headless Chromium at desktop, tablet and mobile viewports, captures full-page screenshots, checks horizontal overflow/navigation collisions/browser errors/external requests, runs axe WCAG A/AA rules, and verifies the initial keyboard focus path. A separate 720 px layout stress view approximates the layout pressure associated with 200% zoom; it is not a substitute for the remaining manual real-browser zoom review.

Durable SITE-0.2 evidence is recorded in:

```text
website/audits/SITE_0_2_BROWSER_AUDIT_2026-09-10.md
```

The responsive compact-layout breakpoint is 800 px after screenshot review showed that the original 880 px breakpoint collapsed an 820 px tablet viewport unnecessarily early.

## Interactive tool integration

Climate Analyzer remains independently deployed at:

```text
https://building-climate-analyzer.streamlit.app/
```

The static website links to it but does not embed it, so the static landing page does not inherit Streamlit Community Cloud requests merely by being opened.

## Reusable publication content

Maintained source material remains under `website/content/` and `docs/`:

- `website/content/about.md`
- `website/content/privacy.md`
- `website/content/accessibility.md`
- `docs/PUBLICATION_POLICY.md`
- `website/PUBLICATION_CHECKLIST.md`

The rendered privacy/legal pages intentionally retain the fail-closed publication state and do not invent owner address/contact data.

## Publication status

```text
BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

SITE-0.2 closes the automated source-level visual/responsive browser audit for the declared viewport matrix. It does not declare the complete Building Energy Tools publication gate closed. Hosting-specific privacy/network behavior still requires audit after an actual static deployment is selected, and the manual keyboard/focus/real-browser-200%-zoom publication check remains separate.
