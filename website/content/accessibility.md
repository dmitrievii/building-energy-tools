# Accessibility status — public beta candidate

Building Energy Tools is being developed with accessibility as an explicit release criterion. This page records the current tested state of **Climate Analyzer** and the limitations that remain before public-promotion clearance.

This is a technical status note, not a formal declaration of WCAG conformance.

## Automated production testing

The deployed Climate Analyzer has been tested with a frame-aware headless Chrome audit at:

- desktop: 1440 × 1000;
- mobile: 390 × 844.

The current post-`WEB-0.9.1` production replay reports:

- application frame detected on desktop and mobile;
- no horizontal overflow;
- no uncaught page errors;
- explicit `Find climate` interaction successful;
- OpenStreetMap attribution visible after map activation;
- 2 axe WCAG A/AA violation groups on desktop;
- 2 axe WCAG A/AA violation groups on mobile.

## Application-owned contrast issue — closed

An earlier desktop audit reported an additional `color-contrast` issue on Streamlit's file-uploader size/type hint. WEB-0.9.1 applies a stable, theme-safe override that inherits the surrounding instruction color. The issue no longer appears in the production axe replay.

## Retained Streamlit framework limitations

Two reproducible automated findings remain in Streamlit-generated framework/platform markup on both tested viewports:

1. `aria-allowed-attr` on the Streamlit sidebar container;
2. `button-name` on a Streamlit toolbar action button.

These are recorded rather than hidden through brittle selectors tied to generated CSS class names. They will be rechecked when the pinned Streamlit version is intentionally upgraded.

## Manual review still required

Before Building Energy Tools is promoted as a public release, a manual review is still required for at least:

- keyboard-only navigation;
- visible and logical focus order;
- operation of file upload and navigation without a pointer;
- `Find climate` controls and map activation;
- 200% browser zoom and text reflow;
- chart/table readability where automated checks cannot establish equivalent access;
- screen-reader naming of project-owned interactive controls where applicable.

Until that review is complete, Building Energy Tools does **not** claim full WCAG conformance.

## Reporting accessibility problems

A public accessibility/contact address will be added only when the project's publication contact fields have been explicitly approved. Private project metadata is not used automatically for public contact disclosure.

## Evidence

The engineering audit trail is maintained in the repository under `deployment/`, including the first live audit and the post-WEB-0.9.1 production closure audit.

Revision: **2026-09-10**.
