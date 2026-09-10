# SITE-0.2 — Visual + Responsive Browser Audit

Date: 2026-09-10

Scope: first static Building Energy Tools website under `website/site/`.

## Final audited branch state

```text
branch: site-0.2-visual-responsive-audit
audited head: 5f2fc610799d9c0e423f79b7c3e2c3e7575385fa
browser audit run: 34532359387
artifact id: 10174033972
artifact SHA-256: 8442a23111c72af5abfce78b28b853c16c3c09ec8c60ec48db0068c76ca3e54d
Chrome: Google Chrome 152.0.7977.82
```

The artifact contains `report.json`, `report.md` and 28 full-page PNG screenshots.

## Matrix

Automated Chromium rendering covers all nine public routes at:

- desktop: 1440 × 1000 CSS px;
- tablet: 820 × 1180 CSS px;
- mobile: 390 × 844 CSS px;
- a separate home-page 200%-layout proxy: 720 × 500 CSS px with `deviceScaleFactor=2`.

The 200%-layout proxy is an automated stress test of the responsive layout. It is **not** represented as a substitute for the remaining manual browser 200% zoom/focus review in the publication checklist.

## Final measured result

Final browser audit result: **PASS**.

Across the 28 route/viewport scenarios:

```text
HTTP/navigation failures       0
horizontal overflow            0 px on every scenario
navigation overlaps            0
clipped in-flow elements       0
axe WCAG A/AA violation groups 0
external runtime requests      0
failed browser requests        0
HTTP 4xx/5xx responses         0
console errors                 0
uncaught page errors           0
```

Keyboard-entry checks on desktop, tablet and mobile also passed: the first `Tab` target is the visible `Skip to content` link.

## Visual review and remediation

The first screenshot set confirmed that desktop and mobile layouts were readable and free of clipping, but the original `max-width: 880px` responsive breakpoint forced the 820 px tablet viewport into the full compact/mobile layout. This created an unnecessarily long single-column page and a stacked header despite sufficient tablet width.

SITE-0.2 therefore changed the principal compact-layout breakpoint from 880 px to 800 px. In the final 820 px rendering:

- primary navigation remains in one horizontal header row;
- the home hero retains the two-column composition;
- the three-role cards remain a three-column group;
- two-column content cards remain two-column;
- the Tools page retains its two-column beta-information layout;
- the 390 px mobile and 720 px layout-proxy views still use the compact layout.

For the home page, the measured 820 px full-page body height changed from 2415 px to 1880 px, a reduction of about 22.2%, without introducing horizontal overflow or axe findings.

The final desktop, tablet and mobile screenshots were manually inspected from the generated audit artifact. No additional layout defect requiring SITE-0.2 remediation was identified.

## First-run audit correction

The initial browser-audit run was:

```text
run: 34531203525
artifact id: 10173578843
artifact SHA-256: 56fede46aa97893bc1e678fb3ffbd5ef29488b81075627816a6d7b07ec266178
```

It returned FAIL for two audit-harness/browser-loading reasons rather than accessibility/layout failures:

1. repeated page requests returned valid HTTP `304 Not Modified`, but the first harness version accepted only status `200`;
2. the browser automatically requested `/favicon.ico`, which did not yet exist and produced the sole 404/console resource error.

Even that first run already measured zero horizontal overflow, zero axe violations and zero external runtime requests on every scenario. The harness was then made cache-safe, 304 was accepted defensively, and a local favicon was added. The final run above passed cleanly.

## Boundary of this evidence

This audit establishes repeatable rendering, responsive-layout, basic keyboard-entry and automated WCAG A/AA evidence for the static source served locally in Chromium. It does **not** establish:

- formal WCAG conformance;
- complete assistive-technology compatibility;
- the still-required manual full keyboard/focus/real-browser-200%-zoom review;
- production-host network/privacy behavior, because the static site has not yet been deployed to its final host.

Those remain separate publication/deployment gates.
