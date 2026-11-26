# R2.19 UI architecture and qualification

## Ownership
- Canonical internal navigation identifiers are retained. The source-neutral group renderer admits only source-supported pages.
- Sidebar: active climate, analysis navigation, Appearance, Architectural background, Export settings, compact Data filters, Report actions, Service & Diagnostics.
- Psychrometric pressure remains a physical calculation setting in the moisture analysis, with a retained source-specific session preference. Existing defaults and calculation algorithms are unchanged.
- The memory service is an explicit route. Normal reruns retain automatic cleanup and show only a short pressure warning. Detailed inventory and reset actions retain their former implementation.
- Eligible heat maps have per-chart controls at the shared Plotly rendering boundary. Contours and labels are defaults. Continuous grids are admitted by the established R2.11 rules; categorical/circular/incomplete grids retain tiles. Per-chart preferences are capped at 128 scalar records per session. The key is semantic chart identity plus duplicate occurrence, not weather data.
- Captured report figures preserve the selected rendering and interpretation; standard and Atlas figures use independent labelled-contour defaults. Appearance and underlay remain global for interactive charts. Appearance, underlay position and filter resets are independent.
- Existing HF3 mixed-worker startup protection is included. A single worker reboot may be necessary when adopting this revision in a live process.

## Evidence required before merge
Run the full regression suite, strict palette/interpretation audit, Cloud qualification and browser smoke workflows. The new state tests cover independent preferences, bounded retention, filter replay, report transformation, actual Streamlit widget reruns and explicit service admission. Browser selectors have been migrated to the grouped navigation. Production readiness requires successful CI and live container verification. No change to scientific algorithms or frozen release manifests.

## HF1 integration closure

R2.19 initial CI: 1,301 tests, 1,295 passes, one pressure-UI contract failure and five obsolete flat-navigation widget errors. Strict palette and interpretation audit passed. Browser evidence confirmed a genuine historical-route TypeError: the source-parity wrapper of the clock selector accepted only one argument after the new filter container was introduced. Both clock and observation-quality wrappers now forward the explicit container, while the Compare Climates duplicate-widget guard is retained. The browser navigation helper checks the real native details open state and scopes clicks to the chosen group. The existing public-route acceptance tests click the new widgets, retaining their scientific and download assertions. The pressure test asserts the same physical station-pressure default through the new contextual route. Four historical test-source changes are explicitly reviewed for current-tree Cloud compatibility; the frozen manifest remains unchanged.

HF1 must pass the actual CI campaign before production admission.
