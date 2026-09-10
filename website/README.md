# Website

Public website layer for **Building Energy Tools**.

## SITE-0.1 foundation

The first real website implementation lives in:

```text
website/site/
```

It is deliberately plain static HTML/CSS:

- no Node/React/Next.js build;
- no JavaScript requirement;
- no external fonts, CDN assets or project-added analytics;
- portable to any ordinary free static host;
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

Validation is performed by:

```text
python website/scripts/check_static_site.py
python -m unittest discover -s website/tests -p 'test_*.py' -v
```

GitHub Actions workflow:

```text
.github/workflows/website-ci.yml
```

The CI checks required pages, semantic page basics, internal links, allowed external-link hosts, absence of external runtime assets, zero-JavaScript contract and a local HTTP route smoke test.

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

The rendered SITE-0.1 privacy/legal pages intentionally retain the fail-closed publication state and do not invent owner address/contact data.

## Publication status

```text
BETA_CANDIDATE_NOT_YET_PUBLICATION_CLEARED
```

SITE-0.1 is a website foundation and preview candidate, not a declaration that the complete Building Energy Tools publication gate is closed. Hosting-specific privacy/network behavior must be audited after an actual static deployment is selected.
