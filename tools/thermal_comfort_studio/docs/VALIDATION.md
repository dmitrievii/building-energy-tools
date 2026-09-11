# Validation

The JavaScript PMV/PPD port is regression-tested against the retained validation corpus and supporting unit tests. The publication package also tests avatar-state routing, category criteria, psychrometrics, SVG chart generation, asset alignment and public deployment-path behaviour.

The publication preparation does not alter the scientific PMV/PPD implementation from source lineage `thermal_comfort_studio_web 1.0.20`; it changes the public shell, asset format and deployment architecture only.

Run:

```bash
npm test
```

The GitHub workflow additionally builds the exact Pages payload and performs an HTTP smoke test against the generated static site.
