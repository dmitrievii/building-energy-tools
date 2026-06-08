# Technical Brief
## Building Energy Tools — MVP

## 1. Project concept
Building Energy Tools is an English-first, multilingual-ready platform for **climate-responsive building design**.

```text
Learn → Calculate → Explore Case Studies
```

Audience: architects, engineers, energy consultants, educators, design teams, and building performance specialists.

## 2. Hero

Headline:
```text
Climate-Responsive Building Design
```

Subtitle:
```text
Learn principles, run calculations, and explore case studies for energy-conscious buildings.
```

Buttons:
```text
Start Learning
Open Tools
```

## 3. Language strategy
MVP language: English. Future language: German. Prepare routing from the beginning:

```text
/en/...
/de/...
```

## 4. Main navigation

```text
Home
Learn
Tools
Case Studies
About
```

Right side: Search, EN / DE. No login in MVP.

## 5. Homepage sections

- Hero
- Learning Areas
- How You Can Use It
- Featured Articles
- Core Tools

## 6. Learning Areas

- Climate Data
- Building Physics
- Windows & Solar Gains
- Ventilation & Comfort
- Loads & Systems
- PV & Storage
- Carbon & Life Cycle

## 7. Core Tools

Initial tool list:

- EPW Viewer
- U-value
- Degree Days
- Overheating
- Heat Load
- PV Yield
- LCC
- Carbon

MVP active tools:

- U-value Calculator
- Degree Days Calculator
- Heating Load Calculator

## 8. Visual direction

Minimal, architectural, academic, clear, technical but approachable, light, calm, not dashboard-heavy. Use thin lines, axonometric sketches, sun path diagrams, muted teal, grey, warm background, serif headline typography, and clean sans-serif UI typography.

## 9. Visualization strategy

Use a hybrid approach:

```text
Generated or custom image without embedded text + HTML/SVG labels and callouts
```

Important labels must remain editable HTML/SVG.

## 10. Technical stack

Frontend: Next.js, TypeScript, Tailwind CSS.
Backend: FastAPI, Python, Pydantic, pytest.

All calculators, including simple MVP tools, must use Python backend logic.

Architecture:

```text
Frontend form → POST request → FastAPI endpoint → Python calculator module → JSON result → Frontend result panel
```

## 11. MVP routes

```text
/en
/en/learn
/en/tools
/en/case-studies
/en/about
/en/tools/u-value
/en/tools/degree-days
/en/tools/heating-load
```

## 12. Disclaimer

The tools on this platform are intended for learning, early-stage design analysis, and preliminary calculations. They do not replace detailed engineering design, certified energy performance assessment, or manufacturer-specific system design.
