import { calculatePmvFromStandardInputs, predictedPercentageDissatisfied } from '../iso7730/pmv.js';
import { rhCurve, psychrometricPoint, relativeHumidityFromHumidityRatio } from '../psychrometric/psychrometric.js';

const NS = 'http://www.w3.org/2000/svg';

function svgEl(tag, attrs = {}, children = []) {
  const el = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v !== undefined && v !== null) el.setAttribute(k, String(v));
  }
  for (const child of children) el.append(child);
  return el;
}

function text(x, y, value, attrs = {}) {
  const el = svgEl('text', { x, y, ...attrs });
  el.textContent = value;
  return el;
}

function clear(node) {
  node.replaceChildren();
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, Number(value)));
}

function clampPmv(value) {
  return clamp(value, -3, 3);
}

function pathFrom(points, xScale, yScale) {
  return points.map((p, idx) => `${idx ? 'L' : 'M'} ${xScale(p.x).toFixed(1)} ${yScale(p.y).toFixed(1)}`).join(' ');
}

function axisFormat(value, decimals = 0) {
  const n = Number(value);
  return n.toFixed(decimals);
}

function axes(svg, { width, height, pad, xMin, xMax, yMin, yMax, xLabel, yLabel, xTicks = 7, yTicks = 5, xDecimals = 0, yDecimals = 0 }) {
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;
  const x = v => pad.left + ((v - xMin) / (xMax - xMin)) * plotW;
  const y = v => pad.top + plotH - ((v - yMin) / (yMax - yMin)) * plotH;
  svg.append(svgEl('rect', { x: pad.left, y: pad.top, width: plotW, height: plotH, fill: 'white', rx: 14 }));
  for (let i = 0; i <= xTicks; i += 1) {
    const v = xMin + (i / xTicks) * (xMax - xMin);
    svg.append(svgEl('line', { x1: x(v), y1: pad.top, x2: x(v), y2: pad.top + plotH, class: 'grid-line' }));
    svg.append(text(x(v), height - 24, axisFormat(v, xDecimals), { class: 'axis-tick', 'text-anchor': 'middle' }));
  }
  for (let i = 0; i <= yTicks; i += 1) {
    const v = yMin + (i / yTicks) * (yMax - yMin);
    svg.append(svgEl('line', { x1: pad.left, y1: y(v), x2: pad.left + plotW, y2: y(v), class: 'grid-line' }));
    svg.append(text(pad.left - 10, y(v) + 4, axisFormat(v, yDecimals), { class: 'axis-tick', 'text-anchor': 'end' }));
  }
  svg.append(svgEl('line', { x1: pad.left, y1: pad.top + plotH, x2: pad.left + plotW, y2: pad.top + plotH, class: 'axis-line' }));
  svg.append(svgEl('line', { x1: pad.left, y1: pad.top, x2: pad.left, y2: pad.top + plotH, class: 'axis-line' }));
  svg.append(text(pad.left + plotW / 2, height - 8, xLabel, { class: 'axis-label', 'text-anchor': 'middle' }));
  svg.append(text(15, pad.top + plotH / 2, yLabel, { class: 'axis-label vertical-label', transform: `rotate(-90 15 ${pad.top + plotH / 2})`, 'text-anchor': 'middle' }));
  return { x, y, plotW, plotH, pad, xMin, xMax, yMin, yMax };
}

function ppdColor(ppd) {
  const p = clamp(ppd, 5, 95);
  const stops = [
    [5, [18, 52, 134]],
    [15, [29, 78, 216]],
    [30, [6, 182, 212]],
    [45, [20, 184, 166]],
    [60, [132, 204, 22]],
    [75, [245, 158, 11]],
    [90, [249, 115, 22]],
    [95, [220, 38, 38]]
  ];
  let left = stops[0], right = stops[stops.length - 1];
  for (let i = 0; i < stops.length - 1; i += 1) {
    if (p >= stops[i][0] && p <= stops[i + 1][0]) {
      left = stops[i];
      right = stops[i + 1];
      break;
    }
  }
  const t = (p - left[0]) / (right[0] - left[0] || 1);
  const rgb = left[1].map((c, i) => Math.round(c + (right[1][i] - c) * t));
  return `rgb(${rgb.join(',')})`;
}

function drawHeatLegend(svg, x, y, h, idPrefix = 'ppd') {
  const gradId = `${idPrefix}-grad`;
  const defs = svgEl('defs');
  const grad = svgEl('linearGradient', { id: gradId, x1: '0%', y1: '100%', x2: '0%', y2: '0%' });
  [
    [0, 5], [18, 15], [36, 30], [52, 45], [68, 60], [82, 75], [94, 90], [100, 95]
  ].forEach(([offset, v]) => grad.append(svgEl('stop', { offset: `${offset}%`, 'stop-color': ppdColor(v) })));
  defs.append(grad);
  svg.append(defs);
  svg.append(svgEl('rect', { x, y, width: 16, height: h, rx: 8, fill: `url(#${gradId})`, stroke: '#d7e1ef' }));
  [5, 20, 40, 60, 80, 95].forEach(v => {
    const yy = y + h - ((v - 5) / 90) * h;
    svg.append(svgEl('line', { x1: x + 18, y1: yy, x2: x + 24, y2: yy, class: 'legend-tick-line' }));
    svg.append(text(x + 28, yy + 4, `${v}`, { class: 'legend-tick' }));
  });
  svg.append(text(x + 8, y - 8, 'PPD', { class: 'legend-title', 'text-anchor': 'middle' }));
  svg.append(text(x + 8, y + h + 15, '%', { class: 'legend-title', 'text-anchor': 'middle' }));
}

function calculateSafe(input) {
  return calculatePmvFromStandardInputs(input, { checkApplicability: false });
}

function searchBest(targetFn, values) {
  let best = null;
  for (const candidate of values) {
    const score = targetFn(candidate);
    if (!Number.isFinite(score.metric)) continue;
    if (!best || score.metric < best.metric) best = score;
  }
  return best;
}

export function renderPpdCurve(container, pmv, ppd) {
  clear(container);
  const visualPmv = clampPmv(pmv);
  const visualPpd = Math.max(0, Math.min(100, Number(ppd)));
  const width = 560, height = 260, pad = { left: 48, right: 24, top: 20, bottom: 46 };
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart-svg' });
  const ax = axes(svg, { width, height, pad, xMin: -3, xMax: 3, yMin: 0, yMax: 100, xLabel: 'PMV', yLabel: 'PPD (%)' });
  const pts = [];
  for (let p = -3; p <= 3.001; p += 0.05) pts.push({ x: p, y: predictedPercentageDissatisfied(p) });
  svg.append(svgEl('path', { d: pathFrom(pts, ax.x, ax.y), fill: 'none', class: 'line-primary' }));
  svg.append(svgEl('line', { x1: ax.x(visualPmv), y1: pad.top, x2: ax.x(visualPmv), y2: ax.y(visualPpd), class: 'line-accent dashed' }));
  svg.append(svgEl('line', { x1: pad.left, y1: ax.y(visualPpd), x2: ax.x(visualPmv), y2: ax.y(visualPpd), class: 'line-accent dashed' }));
  svg.append(svgEl('circle', { cx: ax.x(visualPmv), cy: ax.y(visualPpd), r: 5.5, class: 'marker-accent' }));
  svg.append(text(ax.x(visualPmv) + 12, ax.y(visualPpd) - 12, `PMV ${visualPmv.toFixed(2)} / PPD ${visualPpd.toFixed(0)}%`, { class: 'callout-label' }));
  container.append(svg);
}

export function renderThermalComfortArea(container, input) {
  clear(container);
  const width = 560, height = 320, pad = { left: 56, right: 72, top: 18, bottom: 48 };
  const xMin = 16, xMax = 32, yMin = 11, yMax = 31;
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart-svg' });
  const ax = axes(svg, { width, height, pad, xMin, xMax, yMin, yMax, xLabel: 'Room air temperature (°C)', yLabel: 'Surface / mean radiant temperature (°C)', xTicks: 8, yTicks: 5 });

  const taStep = 1, trStep = 1;
  const cellW = ax.x(xMin + taStep) - ax.x(xMin);
  const cellH = ax.y(yMin) - ax.y(yMin + trStep);

  for (let ta = xMin; ta < xMax; ta += taStep) {
    for (let tr = yMin; tr < yMax; tr += trStep) {
      let ppd = 95;
      try {
        ppd = calculateSafe({ ...input, airTemperatureC: ta + taStep / 2, meanRadiantTemperatureC: tr + trStep / 2 }).ppdPercent;
      } catch {}
      svg.append(svgEl('rect', {
        x: ax.x(ta), y: ax.y(tr + trStep), width: cellW + 0.7, height: cellH + 0.7,
        fill: ppdColor(ppd), opacity: 0.92, stroke: 'rgba(255,255,255,0.16)', 'stroke-width': 0.6
      }));
    }
  }

  const ridge = [];
  for (let ta = xMin; ta <= xMax; ta += 0.5) {
    const best = searchBest(candidate => {
      try {
        const r = calculateSafe({ ...input, airTemperatureC: ta, meanRadiantTemperatureC: candidate });
        return { metric: Math.abs(r.pmv), x: ta, y: candidate, pmv: r.pmv };
      } catch {
        return { metric: Number.POSITIVE_INFINITY };
      }
    }, Array.from({ length: Math.round((yMax - yMin) / 0.1) + 1 }, (_, i) => yMin + i * 0.1));
    if (best && Number.isFinite(best.metric)) ridge.push({ x: best.x, y: best.y });
  }
  if (ridge.length > 2) {
    svg.append(svgEl('path', { d: pathFrom(ridge, ax.x, ax.y), fill: 'none', class: 'comfort-contour' }));
    const mid = ridge[Math.floor(ridge.length * 0.58)];
    svg.append(text(ax.x(mid.x) - 12, ax.y(mid.y) - 10, 'PMV ≈ 0 · PPD ≈ 5%', { class: 'contour-label', transform: `rotate(-28 ${ax.x(mid.x) - 12} ${ax.y(mid.y) - 10})` }));
  }

  const current = calculateSafe(input);
  const currentX = clamp(input.airTemperatureC, xMin, xMax);
  const currentY = clamp(input.meanRadiantTemperatureC, yMin, yMax);
  svg.append(svgEl('circle', { cx: ax.x(currentX), cy: ax.y(currentY), r: 6, class: 'marker-red' }));
  svg.append(text(ax.x(currentX) + 10, ax.y(currentY) - 8, `${input.airTemperatureC.toFixed(1)} °C / ${input.meanRadiantTemperatureC.toFixed(1)} °C`, { class: 'callout-label' }));

  drawHeatLegend(svg, width - 45, pad.top + 10, 210, 'thermal-area');
  container.append(svg);
}

export function renderPpdVelocityCloMap(container, input) {
  clear(container);
  const width = 560, height = 320, pad = { left: 56, right: 72, top: 18, bottom: 48 };
  const xMin = 0, xMax = 1.2, yMin = 0, yMax = 2.0;
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart-svg' });
  const ax = axes(svg, { width, height, pad, xMin, xMax, yMin, yMax, xLabel: 'Relative air speed (m/s)', yLabel: 'Clothing insulation (clo)', xTicks: 6, yTicks: 5, xDecimals: 1, yDecimals: 1 });

  const vStep = 0.06, cloStep = 0.1;
  const cellW = ax.x(xMin + vStep) - ax.x(xMin);
  const cellH = ax.y(yMin) - ax.y(yMin + cloStep);

  for (let v = xMin; v < xMax; v += vStep) {
    for (let clo = yMin; clo < yMax; clo += cloStep) {
      let ppd = 95;
      try {
        ppd = calculateSafe({ ...input, relativeAirVelocityMS: v + vStep / 2, clothingInsulationClo: clo + cloStep / 2 }).ppdPercent;
      } catch {}
      svg.append(svgEl('rect', {
        x: ax.x(v), y: ax.y(clo + cloStep), width: cellW + 0.8, height: cellH + 0.8,
        fill: ppdColor(ppd), opacity: 0.92, stroke: 'rgba(255,255,255,0.16)', 'stroke-width': 0.6
      }));
    }
  }

  const ridge = [];
  for (let v = xMin; v <= xMax; v += 0.03) {
    const best = searchBest(candidate => {
      try {
        const r = calculateSafe({ ...input, relativeAirVelocityMS: v, clothingInsulationClo: candidate });
        return { metric: Math.abs(r.pmv), x: v, y: candidate, pmv: r.pmv };
      } catch {
        return { metric: Number.POSITIVE_INFINITY };
      }
    }, Array.from({ length: Math.round((yMax - yMin) / 0.02) + 1 }, (_, i) => yMin + i * 0.02));
    if (best && Number.isFinite(best.metric)) ridge.push({ x: best.x, y: best.y });
  }
  if (ridge.length > 2) {
    svg.append(svgEl('path', { d: pathFrom(ridge, ax.x, ax.y), fill: 'none', class: 'comfort-contour' }));
    const mid = ridge[Math.floor(ridge.length * 0.34)];
    svg.append(text(ax.x(mid.x) + 10, ax.y(mid.y) - 12, 'neutral ridge', { class: 'contour-label' }));
  }

  const currentX = clamp(input.relativeAirVelocityMS, xMin, xMax);
  const currentY = clamp(input.clothingInsulationClo, yMin, yMax);
  const current = calculateSafe(input);
  svg.append(svgEl('circle', { cx: ax.x(currentX), cy: ax.y(currentY), r: 6, class: 'marker-red' }));
  svg.append(text(ax.x(currentX) + 10, ax.y(currentY) - 8, `v ${input.relativeAirVelocityMS.toFixed(2)} m/s · clo ${input.clothingInsulationClo.toFixed(2)}`, { class: 'callout-label' }));

  drawHeatLegend(svg, width - 45, pad.top + 10, 210, 'v-clo');
  container.append(svg);
}

export function pmvComfortCategory(pmv, ppd) {
  const abs = Math.abs(Number(pmv));
  const p = Number(ppd);
  if (abs <= 0.2 && p <= 6) return 1;
  if (abs <= 0.5 && p <= 10) return 2;
  if (abs <= 0.7 && p <= 15) return 3;
  if (abs <= 1.0 && p <= 25) return 4;
  return 0;
}

function psychCategoryClass(category) {
  if (category === 1) return 'psych-cat psych-cat-1';
  if (category === 2) return 'psych-cat psych-cat-2';
  if (category === 3) return 'psych-cat psych-cat-3';
  if (category === 4) return 'psych-cat psych-cat-4';
  return '';
}

function renderPsychCategoryLegend(svg, x, y) {
  const rows = [
    ['I', 'PMV ±0.2 / PPD ≤6%', 'psych-cat-1'],
    ['II', 'PMV ±0.5 / PPD ≤10%', 'psych-cat-2'],
    ['III', 'PMV ±0.7 / PPD ≤15%', 'psych-cat-3'],
    ['IV', 'PMV ±1.0 / PPD ≤25%', 'psych-cat-4']
  ];
  rows.forEach(([label, txt, cls], idx) => {
    const yy = y + idx * 18;
    svg.append(svgEl('rect', { x, y: yy - 10, width: 12, height: 12, rx: 3, class: `psych-cat ${cls}` }));
    svg.append(text(x + 18, yy, `${label}: ${txt}`, { class: 'psych-zone-key' }));
  });
}

export function renderPsychrometric(container, input) {
  clear(container);
  const width = 560, height = 306, pad = { left: 54, right: 30, top: 18, bottom: 54 };
  const tMin = 0, tMax = 45, wMin = 0, wMax = 30;
  const pressurePa = input.pressurePa || 101325;
  const svg = svgEl('svg', { viewBox: `0 0 ${width} ${height}`, class: 'chart-svg psychrometric-svg' });
  const ax = axes(svg, { width, height, pad, xMin: tMin, xMax: tMax, yMin: wMin, yMax: wMax, xLabel: 'Dry-bulb temperature (°C)', yLabel: 'Humidity ratio (g/kg)', yTicks: 5 });

  // 1) Psychrometric base: curves of constant relative humidity.
  [20, 40, 60, 80, 100].forEach(rh => {
    const pts = rhCurve(rh, tMin, tMax, 0.5, pressurePa).filter(p => p.humidityRatioGKg <= wMax).map(p => ({ x: p.temperatureC, y: p.humidityRatioGKg }));
    svg.append(svgEl('path', { d: pathFrom(pts, ax.x, ax.y), fill: 'none', class: rh === 100 ? 'rh-curve saturation' : 'rh-curve' }));
    const labelIndex = rh === 100 ? Math.max(0, pts.length - 8) : Math.max(0, pts.length - 5);
    const last = pts[labelIndex];
    if (last) svg.append(text(ax.x(last.x) + 2, ax.y(last.y) - 2, `${rh}%`, { class: 'rh-label' }));
  });

  // 2) Comfort zone: PMV/PPD classification on a Tdb/W grid.
  // The red point is the air state. The green cells are NOT air properties;
  // they are the PMV/PPD comfort result for fixed MRT, air speed, met and clo.
  const t0 = 10, t1 = 36, dt = 0.5;
  const w0 = 0, w1 = 26, dw = 0.5;
  const cellW = ax.x(t0 + dt) - ax.x(t0);
  const cellH = ax.y(w0) - ax.y(w0 + dw);
  const cells = [];
  for (let t = t0; t < t1; t += dt) {
    for (let wg = w0; wg < w1; wg += dw) {
      const tc = t + dt / 2;
      const wcG = wg + dw / 2;
      const wc = wcG / 1000;
      const rh = relativeHumidityFromHumidityRatio(tc, wc, pressurePa);
      if (rh > 100 || rh < 0 || wcG > wMax) continue;
      try {
        const r = calculatePmvFromStandardInputs({
          ...input,
          airTemperatureC: tc,
          relativeHumidityPercent: rh
        }, { checkApplicability: false });
        const category = pmvComfortCategory(r.pmv, r.ppdPercent);
        if (category > 0) cells.push({ t, wg, category });
      } catch {
        // skip invalid points
      }
    }
  }

  // Draw outer categories first, Category I last.
  [4, 3, 2, 1].forEach(category => {
    cells.filter(c => c.category === category).forEach(c => {
      svg.append(svgEl('rect', {
        x: ax.x(c.t),
        y: ax.y(c.wg + dw),
        width: cellW + 0.35,
        height: cellH + 0.35,
        class: psychCategoryClass(category)
      }));
    });
  });

  // 3) Current indoor air state: Tdb/RH -> humidity ratio.
  const current = psychrometricPoint(input.airTemperatureC, input.relativeHumidityPercent, pressurePa);
  const currentX = Math.max(tMin, Math.min(tMax, current.temperatureC));
  const currentY = Math.max(wMin, Math.min(wMax, current.humidityRatioGKg));
  svg.append(svgEl('circle', { cx: ax.x(currentX), cy: ax.y(currentY), r: 6, class: 'marker-red' }));
  svg.append(text(ax.x(currentX) + 10, ax.y(currentY) - 8, `${current.temperatureC.toFixed(1)} °C / ${input.relativeHumidityPercent.toFixed(0)}% RH`, { class: 'callout-label' }));

  renderPsychCategoryLegend(svg, pad.left + 10, pad.top + 20);
  svg.append(text(pad.left + 12, pad.top + ax.plotH - 10, 'green zone = PMV/PPD comfort for current MRT, v, met, clo', { class: 'psych-note-label' }));
  container.append(svg);
}
