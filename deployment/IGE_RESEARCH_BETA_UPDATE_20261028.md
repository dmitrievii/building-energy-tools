# Proposed update of the existing Streamlit technical beta

This branch is prepared from main `2a82a77d0fe8cc87a2324b820d6c6843b6598548`.
It backports the exact application and five required data/protocol packets plus one CPU regression fixture from
the verified IGE I2 implementation. It does not merge the full research archive.

## Visible changes

- Existing Upload EPW, Find climate and GeoSphere routes remain available.
- Generate climate offers the saved Graz historical2023 and CanESM5/SSP245/
  2040–2059 representative future pilot.
- Saved Basel/Binningen and Altdorf2025 research years are available with their
  existing psychrometrics, provenance and downloads.
- Scientific status and limitations remain visible; R1 is not promoted as a
  generally qualified interpolation method.

## Deployment path

The existing Community Cloud contract uses branch main, Python3.12 and
`tools/climate_analyzer/app.py`. The entrypoint and root Streamlit configuration
are preserved. Its adjacent requirements file uses the I2 transitive constraints;
Community Cloud does not run `ige.py setup`.

The candidate runs the full included application suite and actual saved-product
exports using that requirements file, plus a real root-launched Streamlit health
check. This is Cloud-parity preflight, not evidence of a new live deployment.
After an approved merge, review the actual Cloud build and test the four routes,
downloads, ordinary EPW workflow and visible research labels at the existing URL.
Record the deployed SHA and keep the previous main SHA as the rollback anchor.

## Scope and authorization

This updates an existing technical research beta. The publication identity and
`website/PUBLICATION_CHECKLIST.md` remain unchanged; no declaration of full public
promotion, legal clearance or scientific/production qualification is made.
Main and the live application are not changed by preparing this branch or PR.
The earlier user instruction prohibiting main changes and merge requires a final
decision on this concrete candidate before performing that last action.
