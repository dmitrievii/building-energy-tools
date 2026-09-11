# Thermal Comfort Studio

**Thermal Comfort Studio** is an interactive thermal-comfort and human heat-balance tool in the **Building Energy Tools** project. It provides PMV/PPD analysis, operative temperature, whole-body comfort-category screening, heat-balance terms, clothing/activity presets and psychrometric/parameter-space visualisations.

Public release: **0.1.0-beta.1**. Source lineage: local Thermal Comfort Studio `1.0.20`.

## Methods

The PMV/PPD implementation follows the ISO 7730 calculation chain used by the audited source package. The interface also exposes simplified diagnostic and visual layers intended for research, teaching and early design support. See `docs/METHODOLOGY.md` and `docs/VALIDATION.md`.

## Run locally

No third-party npm packages are required. With Node.js installed:

```bash
npm test
npm run dev
```

Open `http://127.0.0.1:5173/`.

To build the exact static payload used by GitHub Pages:

```bash
npm run build
```

The generated `dist/` directory is disposable and is not the canonical source.

## Publication architecture

The canonical source lives at `tools/thermal_comfort_studio/`. The main Building Energy Tools GitHub Pages workflow creates a temporary `_site` artifact, copies `website/site/`, then builds this tool into `_site/tools/thermal-comfort-studio/`. This avoids keeping two copies of the 60+ avatar assets in the repository.

## Project identity

Maintained by Ivan Dmitriev as an independent personal research and teaching project. Academic affiliation is stated for biographical context only; Building Energy Tools is not an official website, service or product of Graz University of Technology.

This repository does not currently declare a general open-source software licence. Public source availability should not be interpreted as permission for unrestricted reuse.
