import { CLOTHING_PRESETS, PMV_STATE_ORDER } from './data/clothingPresets.js';
import { ACTIVITY_PRESETS } from './data/activityPresets.js';
import { AVATAR_LAYOUTS } from './data/avatarLayout.js';
import { calculatePmvFromStandardInputs, comfortCategory, nearestPmvStateKey, operativeTemperature, sensationLabel, validateApplicability, cloToM2KW } from './iso7730/pmv.js';
import { psychrometricPoint } from './psychrometric/psychrometric.js';
import { renderPpdCurve, renderThermalComfortArea, renderPsychrometric, renderPpdVelocityCloMap } from './charts/charts.js';
import { ASSET_VERSION, ENGINEERING_DISCLAIMER, INDEPENDENCE_NOTICE, TOOL_NAME, TOOL_VERSION } from './releaseInfo.js';

const initialState = {
  airTemperatureC: 22,
  meanRadiantTemperatureC: 22,
  relativeAirVelocityMS: 0.1,
  relativeHumidityPercent: 60,
  metabolicRateMet: 1.2,
  clothingInsulationClo: 0.5,
  externalWorkMet: 0,
  clothingPresetId: 'preset_02_light_indoor',
  activityPresetId: 'sedentary_activity',
  manualCloOverride: false,
  showAdvanced: false,
  showTotalWatts: false,
  bodySurfaceAreaM2: 1.8
};

function qs(root, selector) { return root.querySelector(selector); }
function qsa(root, selector) { return Array.from(root.querySelectorAll(selector)); }
function fmt(value, digits = 1) { return Number(value).toFixed(digits); }
function clamp(value, min, max) { return Math.max(min, Math.min(max, Number(value))); }
function boundedPmv(value) { return clamp(value, -3, 3); }
function signedPmv(value, digits = 2) { return signed(boundedPmv(value), digits); }
function avatarStateKeyForPmv(pmv) {
  const value = boundedPmv(pmv);
  if (value <= -2.5) return 'pmv_-3_freezing';
  if (value <= -1.5) return 'pmv_-2_cold';
  if (value <= -0.5) return 'pmv_-1_slightly_cool';
  if (value < 0.5) return 'pmv_0_comfortable';
  if (value < 1.5) return 'pmv_+1_slightly_warm';
  if (value < 2.5) return 'pmv_+2_warm';
  return 'pmv_+3_overheated';
}

function presetById(id) { return CLOTHING_PRESETS.find(p => p.id === id) || CLOTHING_PRESETS[0]; }
function activityById(id) { return ACTIVITY_PRESETS.find(a => a.id === id) || ACTIVITY_PRESETS[2]; }

function signed(value, digits = 2) {
  const n = Number(value);
  return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}`;
}

function lossShare(value, total) {
  if (Math.abs(total) < 1e-9) return 0;
  return Math.round((Math.abs(value) / Math.abs(total)) * 100);
}

function visualFlowTotal(h) {
  return [h.radiationWM2, h.convectionWM2, h.skinEvaporationWM2, h.respirationWM2]
    .reduce((sum, value) => sum + Math.abs(Number(value) || 0), 0);
}

function flowStrokeWidth(value) {
  const magnitude = Math.abs(Number(value) || 0);
  return Math.max(1.35, Math.min(4.85, 1.35 + Math.sqrt(magnitude) * 0.39));
}

function flowOpacity(value) {
  const magnitude = Math.abs(Number(value) || 0);
  return Math.max(0.50, Math.min(0.92, 0.50 + magnitude / 95));
}

function itemLabel(item) {
  return item.source_label || item.description || item.item_key.replaceAll('_', ' ');
}

function stepRange(start, end, step) {
  const out = [];
  for (let value = start; value <= end + step * 0.5; value += step) out.push(Number(value.toFixed(4)));
  return out;
}

function bestCandidate(values, evaluator) {
  let best = null;
  for (const value of values) {
    try {
      const result = evaluator(value);
      const metric = Math.abs(Number(result.pmv)) + Number(result.ppdPercent || 0) * 0.001;
      if (!best || metric < best.metric) best = { value, result, metric };
    } catch {
      // skip invalid point
    }
  }
  return best;
}

function directionVerb(delta, positiveVerb, negativeVerb) {
  return delta >= 0 ? positiveVerb : negativeVerb;
}

export class ThermalComfortApp {
  constructor(root) {
    this.root = root;
    this.state = { ...initialState };
    this.renderShell();
    this.bindEvents();
    this.updateAll();
  }

  inputPayload() {
    return {
      airTemperatureC: Number(this.state.airTemperatureC),
      meanRadiantTemperatureC: Number(this.state.meanRadiantTemperatureC),
      relativeAirVelocityMS: Number(this.state.relativeAirVelocityMS),
      relativeHumidityPercent: Number(this.state.relativeHumidityPercent),
      metabolicRateMet: Number(this.state.metabolicRateMet),
      clothingInsulationClo: Number(this.state.clothingInsulationClo),
      externalWorkMet: Number(this.state.externalWorkMet || 0)
    };
  }

  calculate() {
    return calculatePmvFromStandardInputs(this.inputPayload(), { checkApplicability: false });
  }

  renderShell() {
    this.root.innerHTML = `
      <header class="app-header">
        <div class="brand"><div class="brand-icon" aria-hidden="true">♨</div><div><a class="project-kicker" href="../../">Building Energy Tools</a><h1>${TOOL_NAME}</h1><p>Thermal comfort and human heat-balance analysis</p></div></div>
        <div class="header-actions"><span class="badge">ISO 7730 · PMV / PPD</span><span class="version">${TOOL_VERSION}</span></div>
      </header>
      <main class="dashboard-grid">
        <section class="panel input-panel">
          <div class="panel-title"><h2>Inputs</h2><span>compact engineering controls</span></div>
          <div id="inputControls"></div>
          <div class="preset-note" id="presetNote"></div>
        </section>
        <section class="panel avatar-panel">
          <div class="avatar-stage">
            <div class="heat-label heat-radiation"><b>Radiation</b><span id="radiationLabel">—</span></div>
            <div class="heat-label heat-convection"><b>Convection</b><span id="convectionLabel">—</span></div>
            <div class="heat-label heat-evap"><b>Skin evaporation</b><span id="evapLabel">—</span></div>
            <div class="heat-label heat-resp"><b>Respiration</b><span id="respLabel">—</span></div>
            <div class="heat-label heat-met"><b>M − W</b><span id="metLabel">—</span></div>
            <div class="heat-label heat-cond"><b>Conduction</b><span>0 W/m² · not in ISO 7730 PMV</span></div>
            <svg class="heat-arrows" viewBox="0 0 1000 560" preserveAspectRatio="none" aria-hidden="true">
              <g class="flow radiation-flow" data-flow="radiation">
                <path class="heat-wave strong" d="M404 190 C358 184 322 185 284 192 C242 200 208 196 178 186" />
                <path class="head-loss" d="M132 181 L162 165 L162 197 Z" />
                <path class="head-gain" d="M406 184 L373 169 L374 201 Z" />
                <path class="heat-wave" d="M404 222 C358 216 322 217 284 225 C242 232 208 229 178 219" />
                <path class="head-loss" d="M132 214 L162 198 L162 230 Z" />
                <path class="head-gain" d="M406 216 L373 201 L374 233 Z" />
                <path class="heat-wave soft" d="M404 254 C360 248 324 249 286 256 C245 264 210 262 181 252" />
                <path class="head-loss soft" d="M138 245 L166 231 L166 259 Z" />
                <path class="head-gain soft" d="M403 248 L375 234 L376 262 Z" />
              </g>

              <g class="flow convection-flow" data-flow="convection">
                <path class="heat-wave strong" d="M404 352 C358 360 322 360 286 354 C244 347 208 354 176 370" />
                <path class="head-loss" d="M128 368 L158 345 L162 382 Z" />
                <path class="head-gain" d="M410 337 L377 323 L383 360 Z" />
                <path class="heat-wave" d="M404 388 C358 396 322 396 286 390 C244 383 208 390 176 406" />
                <path class="head-loss" d="M128 405 L158 382 L162 419 Z" />
                <path class="head-gain" d="M410 372 L377 359 L383 395 Z" />
                <path class="heat-wave soft" d="M404 424 C360 432 324 432 288 426 C247 419 212 426 180 441" />
                <path class="head-loss soft" d="M134 439 L160 419 L164 451 Z" />
                <path class="head-gain soft" d="M407 408 L378 396 L384 426 Z" />
              </g>

              <g class="flow evaporation-flow" data-flow="evaporation">
                <g class="loss-stream">
                  <path class="heat-curve strong" d="M664 184 C702 166 728 138 760 106 C792 77 819 57 852 46" />
                  <path class="head-loss" d="M888 44 L856 29 L864 67 Z" />
                  <path class="heat-curve soft" d="M694 232 C734 216 760 191 789 164 C818 138 846 121 880 112" />
                  <path class="head-loss soft" d="M916 111 L885 97 L892 133 Z" />
                  <circle cx="722" cy="149" r="2.6"/><circle cx="748" cy="120" r="2.2"/><circle cx="780" cy="92" r="2.5"/><circle cx="814" cy="73" r="2.1"/>
                </g>
                <g class="gain-stream">
                  <path class="heat-curve strong" d="M854 45 C818 57 790 77 760 106 C728 139 703 169 662 186" />
                  <path class="head-gain" d="M620 211 L650 190 L656 226 Z" />
                  <path class="heat-curve soft" d="M882 112 C846 122 818 138 790 163 C761 190 736 214 695 232" />
                  <path class="head-gain soft" d="M654 248 L686 226 L688 260 Z" />
                  <circle cx="812" cy="73" r="2.1"/><circle cx="780" cy="92" r="2.5"/><circle cx="748" cy="120" r="2.2"/><circle cx="722" cy="149" r="2.6"/>
                </g>
              </g>

              <g class="flow respiration-flow" data-flow="respiration">
                <path class="heat-curve strong" d="M640 286 C674 302 706 312 736 320 C765 327 793 327 822 320" />
                <path class="head-loss" d="M858 318 L828 303 L832 339 Z" />
                <path class="head-gain" d="M616 266 L648 252 L642 287 Z" />
                <path class="heat-curve soft" d="M652 307 C688 323 718 333 748 341 C776 347 800 347 826 340" />
                <path class="head-loss soft" d="M858 334 L831 321 L835 354 Z" />
                <path class="head-gain soft" d="M628 289 L659 277 L652 309 Z" />
                <circle cx="696" cy="307" r="2.6"/><circle cx="731" cy="321" r="2.3"/><circle cx="768" cy="332" r="2.1"/>
              </g>
            </svg>
            <img id="avatarImage" class="avatar-image" alt="thermal comfort avatar" />
          </div>
          <div class="state-strip" id="stateStrip"></div>
        </section>
        <section class="results-column">
          <div class="kpi-grid">
            <div class="kpi"><span>PMV</span><strong id="pmvValue">—</strong><em id="sensationValue">—</em></div>
            <div class="kpi"><span>PPD</span><strong id="ppdValue">—</strong><em id="ppdLevel">—</em></div>
            <div class="kpi"><span>Operative temperature</span><strong id="operativeValue">—</strong><em>weighted ta/tr</em></div>
            <div class="kpi"><span>Category</span><strong id="categoryValue">—</strong><em>ISO 7730 Annex A</em></div>
          </div>
          <div class="panel mini-chart"><div class="chart-head"><h3>PMV–PPD relationship</h3></div><div id="ppdChart"></div></div>
          <div class="panel mini-chart"><div class="chart-head"><h3>Psychrometric comfort</h3></div><div id="psychChart"></div></div>
        </section>
      </main>
      <section class="lower-grid">
        <div class="panel"><div class="chart-head"><h3>Thermal Comfort Area · Air & Surface Temperature</h3></div><div id="tempChart"></div><div id="tempAdvice" class="chart-advice"></div></div>
        <div class="panel"><div class="chart-head"><h3>PPD map · Relative air speed & clothing</h3></div><div id="sensitivityChart"></div><div id="sensitivityAdvice" class="chart-advice"></div></div>
        <div class="panel heat-table-panel"><div class="chart-head"><h3>Heat balance terms</h3><button id="advancedToggle" class="text-button">Advanced trace</button></div><div id="heatTerms"></div></div>
      </section>
      <section class="diagnosis panel"><div class="diagnosis-icon">⌁</div><div><h2>Diagnosis</h2><p id="diagnosisText">—</p><div id="warnings" class="warnings"></div></div></section>
      <footer class="app-footer"><div><strong>Building Energy Tools</strong><span>${ENGINEERING_DISCLAIMER}</span><span>${INDEPENDENCE_NOTICE}</span></div><nav aria-label="Product links"><a href="../../tools/">Tools</a><a href="../../documentation/">Documentation</a><a href="../../about/">About</a></nav></footer>
    `;
    this.renderControls();
    this.renderStateStrip();
  }

  renderControls() {
    const controls = qs(this.root, '#inputControls');
    const activityOptions = ACTIVITY_PRESETS.map(a => `<option value="${a.id}">${a.label}</option>`).join('');
    const clothingOptions = CLOTHING_PRESETS.map(p => `<option value="${p.id}">${p.name} · ${p.clo.toFixed(2)} clo</option>`).join('');
    controls.innerHTML = `
      ${this.numberControl('airTemperatureC', 'Air temperature', '°C', 10, 32, 0.1)}
      ${this.numberControl('meanRadiantTemperatureC', 'Mean radiant temperature', '°C', 10, 40, 0.1)}
      ${this.numberControl('relativeAirVelocityMS', 'Relative air speed', 'm/s', 0, 1.5, 0.01)}
      ${this.numberControl('relativeHumidityPercent', 'Relative humidity', '%', 0, 100, 1)}
      ${this.numberControl('metabolicRateMet', 'Metabolic rate', 'met', 0.8, 4, 0.1)}
      ${this.numberControl('clothingInsulationClo', 'Clothing insulation', 'clo', 0, 2, 0.01)}
      ${this.numberControl('externalWorkMet', 'External work W', 'met', 0, 2, 0.01)}
      <label class="control-row checkbox-row"><span>Heat-flow display</span><label class="check-control"><input type="checkbox" data-key="showTotalWatts"> Total W instead of W/m²</label><em>Adu 1.8 m²</em></label>
      <label class="control-row"><span>Activity preset</span><select data-key="activityPresetId">${activityOptions}</select></label>
      <label class="control-row"><span>Clothing preset</span><select data-key="clothingPresetId">${clothingOptions}</select></label>
    `;
    for (const [key, value] of Object.entries(this.state)) {
      const el = qs(controls, `[data-key="${key}"]`);
      if (!el) continue;
      if (el.type === 'checkbox') el.checked = Boolean(value);
      else el.value = value;
    }
  }

  numberControl(key, label, unit, min, max, step) {
    return `<label class="control-row"><span>${label}</span><input type="number" data-key="${key}" min="${min}" max="${max}" step="${step}" value="${this.state[key]}"><em>${unit}</em></label>`;
  }

  renderStateStrip() {
    const labels = {
      'pmv_-3_freezing': 'Freezing', 'pmv_-2_cold': 'Cold', 'pmv_-1_slightly_cool': 'Slightly Cool', 'pmv_0_comfortable': 'Comfortable', 'pmv_+1_slightly_warm': 'Slightly Warm', 'pmv_+2_warm': 'Warm', 'pmv_+3_overheated': 'Overheated'
    };
    const icons = {
      'pmv_-3_freezing': '❄',
      'pmv_-2_cold': '🧊',
      'pmv_-1_slightly_cool': '🌬',
      'pmv_0_comfortable': '☺',
      'pmv_+1_slightly_warm': '🌤',
      'pmv_+2_warm': '☀',
      'pmv_+3_overheated': '🔥'
    };
    const values = {
      'pmv_-3_freezing': '−3', 'pmv_-2_cold': '−2', 'pmv_-1_slightly_cool': '−1', 'pmv_0_comfortable': '0', 'pmv_+1_slightly_warm': '+1', 'pmv_+2_warm': '+2', 'pmv_+3_overheated': '+3'
    };
    qs(this.root, '#stateStrip').innerHTML = PMV_STATE_ORDER.map(k => `<div class="state-dot" data-state="${k}"><i>${icons[k]}</i><span></span><em>${values[k]}</em><b>${labels[k]}</b></div>`).join('');
  }

  bindEvents() {
    this.root.addEventListener('input', e => {
      const key = e.target?.dataset?.key;
      if (!key) return;
      const numeric = e.target.type === 'number';
      if (e.target.type === 'checkbox') this.state[key] = e.target.checked;
      else this.state[key] = numeric ? Number(e.target.value) : e.target.value;
      if (key === 'clothingInsulationClo') this.state.manualCloOverride = true;
      this.updateAll();
    });
    this.root.addEventListener('change', e => {
      const key = e.target?.dataset?.key;
      if (!key) return;
      if (e.target.type === 'checkbox') this.state[key] = e.target.checked;
      else this.state[key] = e.target.value;
      if (key === 'showTotalWatts') {
        this.updateAll();
        return;
      }
      if (key === 'clothingPresetId') {
        const p = presetById(e.target.value);
        this.state.manualCloOverride = false;
        this.state.clothingInsulationClo = p.clo;
        const cloInput = qs(this.root, '[data-key="clothingInsulationClo"]');
        if (cloInput) cloInput.value = p.clo;
      }
      if (key === 'activityPresetId') {
        const a = activityById(e.target.value);
        this.state.metabolicRateMet = a.met;
        const metInput = qs(this.root, '[data-key="metabolicRateMet"]');
        if (metInput) metInput.value = a.met;
      }
      this.updateAll();
    });
    qs(this.root, '#advancedToggle')?.addEventListener('click', () => {
      this.state.showAdvanced = !this.state.showAdvanced;
      this.updateHeatTerms(this.calculate());
    });
    window.addEventListener('resize', () => {
      clearTimeout(this._avatarResizeTimer);
      this._avatarResizeTimer = setTimeout(() => {
        if (this.currentAvatarPresetId && this.currentAvatarStateKey) {
          this.applyAvatarLayout(this.currentAvatarPresetId, this.currentAvatarStateKey);
        }
      }, 80);
    });
  }

  updateAll() {
    let result;
    const input = this.inputPayload();
    try {
      result = calculatePmvFromStandardInputs(input, { checkApplicability: false });
    } catch (err) {
      this.showError(err);
      return;
    }
    this.updateKpis(result);
    this.updateAvatar(result);
    this.updateHeatLabels(result);
    this.updateHeatTerms(result);
    this.updateDiagnosis(result);
    renderPpdCurve(qs(this.root, '#ppdChart'), boundedPmv(result.pmv), result.ppdPercent);
    renderPsychrometric(qs(this.root, '#psychChart'), input);
    renderThermalComfortArea(qs(this.root, '#tempChart'), input);
    renderPpdVelocityCloMap(qs(this.root, '#sensitivityChart'), input);
    this.updateChartAdvice(result);
    this.syncSelects();
  }


  updateChartAdvice(result) {
    const input = this.inputPayload();
    const tempAdvice = this.temperatureChartAdvice(result, input);
    const velocityAdvice = this.velocityCloAdvice(result, input);
    qs(this.root, '#tempAdvice').innerHTML = `<p><strong>Advice.</strong> ${tempAdvice.message}</p><p class="chart-meta">${tempAdvice.meta}</p>`;
    qs(this.root, '#sensitivityAdvice').innerHTML = `<p><strong>Advice.</strong> ${velocityAdvice.message}</p><p class="chart-meta">${velocityAdvice.meta}</p>`;
  }

  temperatureChartAdvice(result, input) {
    const bestTa = bestCandidate(stepRange(10, 32, 0.1), airTemperatureC => calculatePmvFromStandardInputs({ ...input, airTemperatureC }, { checkApplicability: false }));
    const bestTr = bestCandidate(stepRange(10, 40, 0.1), meanRadiantTemperatureC => calculatePmvFromStandardInputs({ ...input, meanRadiantTemperatureC }, { checkApplicability: false }));
    const meta = `Map recalculated for RH ${fmt(input.relativeHumidityPercent, 0)} %, v ${fmt(input.relativeAirVelocityMS, 2)} m/s, met ${fmt(input.metabolicRateMet, 1)}, clo ${fmt(input.clothingInsulationClo, 2)}.`;
    if (!bestTa || !bestTr) return { message: 'No stable guidance could be computed for the current input range.', meta };
    const dTa = Number((bestTa.value - input.airTemperatureC).toFixed(1));
    const dTr = Number((bestTr.value - input.meanRadiantTemperatureC).toFixed(1));
    if (Math.abs(result.pmv) <= 0.2 && result.ppdPercent <= 10) {
      return {
        message: `The current point is already close to neutral. Keep air temperature near ${fmt(input.airTemperatureC, 1)} °C and mean radiant temperature near ${fmt(input.meanRadiantTemperatureC, 1)} °C; only fine adjustment within about ±0.5 K is needed.`,
        meta
      };
    }
    if (result.pmv < 0) {
      return {
        message: `The room is on the cool side. Raise air temperature by about ${fmt(Math.abs(dTa), 1)} K to ${fmt(bestTa.value, 1)} °C, or raise mean radiant temperature by about ${fmt(Math.abs(dTr), 1)} K to ${fmt(bestTr.value, 1)} °C to move toward PMV 0.`,
        meta
      };
    }
    return {
      message: `The room is on the warm side. Reduce air temperature by about ${fmt(Math.abs(dTa), 1)} K to ${fmt(bestTa.value, 1)} °C, or reduce mean radiant temperature by about ${fmt(Math.abs(dTr), 1)} K to ${fmt(bestTr.value, 1)} °C to move toward PMV 0.`,
      meta
    };
  }

  velocityCloAdvice(result, input) {
    const bestV = bestCandidate(stepRange(0, 1.2, 0.01), relativeAirVelocityMS => calculatePmvFromStandardInputs({ ...input, relativeAirVelocityMS }, { checkApplicability: false }));
    const bestClo = bestCandidate(stepRange(0, 2.0, 0.01), clothingInsulationClo => calculatePmvFromStandardInputs({ ...input, clothingInsulationClo }, { checkApplicability: false }));
    const meta = `Map recalculated for ta ${fmt(input.airTemperatureC, 1)} °C, tr ${fmt(input.meanRadiantTemperatureC, 1)} °C, RH ${fmt(input.relativeHumidityPercent, 0)} %, met ${fmt(input.metabolicRateMet, 1)}.`;
    if (!bestV || !bestClo) return { message: 'No stable clothing / air-speed guidance could be computed for the current input range.', meta };
    const dV = Number((bestV.value - input.relativeAirVelocityMS).toFixed(2));
    const dClo = Number((bestClo.value - input.clothingInsulationClo).toFixed(2));
    if (Math.abs(result.pmv) <= 0.2 && result.ppdPercent <= 10) {
      return {
        message: `The current clothing and air-speed pair already lies close to the low-PPD ridge. Keep air speed around ${fmt(input.relativeAirVelocityMS, 2)} m/s and clothing near ${fmt(input.clothingInsulationClo, 2)} clo; only small local adjustment of about ±0.05 m/s or ±0.10 clo would noticeably shift sensation.`,
        meta
      };
    }
    if (result.pmv < 0) {
      const airPart = bestV.value < input.relativeAirVelocityMS - 0.01 ? `reduce air speed by about ${fmt(Math.abs(dV), 2)} m/s to ${fmt(bestV.value, 2)} m/s` : 'air-speed reduction alone has only limited effect from the current point';
      return {
        message: `The condition is cool. ${airPart}, or increase clothing by about ${fmt(Math.abs(dClo), 2)} clo to ${fmt(bestClo.value, 2)} clo to move toward PMV 0.`,
        meta
      };
    }
    const airPart = bestV.value > input.relativeAirVelocityMS + 0.01 ? `increase air speed by about ${fmt(Math.abs(dV), 2)} m/s to ${fmt(bestV.value, 2)} m/s` : 'air-speed increase alone has only limited effect from the current point';
    return {
      message: `The condition is warm. ${airPart}, or reduce clothing by about ${fmt(Math.abs(dClo), 2)} clo to ${fmt(bestClo.value, 2)} clo to move toward PMV 0.`,
      meta
    };
  }

  syncSelects() {
    const presetSelect = qs(this.root, '[data-key="clothingPresetId"]');
    if (presetSelect) presetSelect.value = this.state.clothingPresetId;
    const activitySelect = qs(this.root, '[data-key="activityPresetId"]');
    if (activitySelect) activitySelect.value = this.state.activityPresetId;
    const note = qs(this.root, '#presetNote');
    const p = presetById(this.state.clothingPresetId);
    if (this.state.manualCloOverride) {
      note.textContent = `${p.name} visual preset with manual clo override: ${this.state.clothingInsulationClo.toFixed(2)} clo (${cloToM2KW(this.state.clothingInsulationClo).toFixed(3)} m²K/W).`;
    } else {
      note.textContent = `${p.name}: ${p.clo.toFixed(2)} clo · ${p.sourceTable}${p.note ? ' · ' + p.note : ''}`;
    }
  }

  updateKpis(result) {
    const op = operativeTemperature(this.state.airTemperatureC, this.state.meanRadiantTemperatureC, result.convectiveHeatTransferCoefficientWM2K);
    const cat = comfortCategory(result.pmv, result.ppdPercent);
    qs(this.root, '#pmvValue').textContent = signedPmv(result.pmv, 2);
    qs(this.root, '#sensationValue').textContent = sensationLabel(result.pmv);
    qs(this.root, '#ppdValue').textContent = `${fmt(result.ppdPercent, 0)}%`;
    qs(this.root, '#ppdLevel').textContent = result.ppdPercent <= 10 ? 'Low' : result.ppdPercent <= 25 ? 'Moderate' : 'High';
    qs(this.root, '#operativeValue').textContent = `${fmt(op, 1)} °C`;
    qs(this.root, '#categoryValue').textContent = cat === 'outside' ? '—' : cat;
  }

  updateAvatar(result) {
    const stateKey = avatarStateKeyForPmv(result.pmv);
    const preset = presetById(this.state.clothingPresetId);
    const img = qs(this.root, '#avatarImage');
    this.currentAvatarPresetId = preset.id;
    this.currentAvatarStateKey = stateKey;
    img.onload = () => this.applyAvatarLayout(preset.id, stateKey, { afterLoad: true });
    img.src = `${preset.states[stateKey].src}?v=${encodeURIComponent(ASSET_VERSION)}`;
    img.alt = `${preset.name}, ${preset.states[stateKey].label}`;
    this.applyAvatarLayout(preset.id, stateKey);
    requestAnimationFrame(() => this.applyAvatarLayout(preset.id, stateKey));
    qsa(this.root, '.state-dot').forEach(el => el.classList.toggle('active', el.dataset.state === stateKey));
  }

  applyAvatarLayout(presetId, stateKey, options = {}) {
    const img = qs(this.root, '#avatarImage');
    const stage = qs(this.root, '.avatar-stage');
    const layout = AVATAR_LAYOUTS[`${presetId}:${stateKey}`];
    if (!img || !stage || !layout) return;

    const [x0, y0, x1, y1] = layout.bbox;
    const sourceWidth = layout.imageWidth || img.naturalWidth || 1024;
    const sourceHeight = layout.imageHeight || img.naturalHeight || 1536;
    const bboxHeight = Math.max(1, y1 - y0 + 1);
    const bboxCenterX = (x0 + x1) / 2;
    const stageHeight = Math.max(stage.clientHeight || 680, 680);

    /*
      Hard alignment pass:
      - all presets/states are scaled by the audited visible-person bbox, not by raw PNG size;
      - feet are locked to the same floor line;
      - the visual body centre is locked to the same stage centre.
      This fixes state images with different transparent margins and generated figure height.
    */
    const targetBBoxHeight = Math.min(stageHeight * 0.94, 650);
    const floorMargin = Math.max(16, stageHeight * 0.028);
    const scaleCorrection = Number(layout.scaleCorrection ?? 1);
    const manualX = Number(layout.xOffsetPx ?? 0);
    const manualY = Number(layout.yOffsetPx ?? 0);
    const scale = (targetBBoxHeight / bboxHeight) * scaleCorrection;
    const displayHeight = sourceHeight * scale;
    const translateX = ((sourceWidth / 2) - bboxCenterX) * scale + manualX;
    const bottom = floorMargin - ((sourceHeight - y1) * scale) + manualY;

    img.style.height = `${displayHeight.toFixed(2)}px`;
    img.style.maxWidth = 'none';
    img.style.width = 'auto';
    img.style.left = '50%';
    img.style.bottom = `${bottom.toFixed(2)}px`;
    img.style.transform = `translateX(calc(-50% + ${translateX.toFixed(2)}px))`;
    img.dataset.alignment = `${presetId}:${stateKey}`;
    img.dataset.afterLoad = options.afterLoad ? '1' : '0';
  }

  heatUnitLabel() {
    return this.state.showTotalWatts ? 'W' : 'W/m²';
  }

  heatDisplayValue(value, digits = 1) {
    const scaled = this.state.showTotalWatts ? Number(value) * this.state.bodySurfaceAreaM2 : Number(value);
    return `${fmt(scaled, digits)} ${this.heatUnitLabel()}`;
  }

  heatFlowLabel(value, denominator) {
    const suffix = value < 0 ? ' · gain' : '';
    return `${this.heatDisplayValue(value, 1)} (${lossShare(value, denominator)}%)${suffix}`;
  }

  updateHeatLabels(result) {
    const h = result.heatBalance;
    const total = visualFlowTotal(h);
    qs(this.root, '#radiationLabel').textContent = this.heatFlowLabel(h.radiationWM2, total);
    qs(this.root, '#convectionLabel').textContent = this.heatFlowLabel(h.convectionWM2, total);
    qs(this.root, '#evapLabel').textContent = this.heatFlowLabel(h.skinEvaporationWM2, total);
    qs(this.root, '#respLabel').textContent = this.heatFlowLabel(h.respirationWM2, total);
    qs(this.root, '#metLabel').textContent = this.heatDisplayValue(h.internalHeatProductionWM2, 1);
    qs(this.root, '.heat-cond span').textContent = this.state.showTotalWatts ? '0 W · not in ISO 7730 PMV' : '0 W/m² · not in ISO 7730 PMV';
    this.updateHeatFlowVisuals(h);
  }

  updateHeatFlowVisuals(h) {
    const values = {
      radiation: h.radiationWM2,
      convection: h.convectionWM2,
      evaporation: h.skinEvaporationWM2,
      respiration: h.respirationWM2
    };
    for (const [name, value] of Object.entries(values)) {
      const group = qs(this.root, `.${name}-flow`);
      if (!group) continue;
      const width = flowStrokeWidth(value);
      group.classList.toggle('is-gain', value < 0);
      group.style.setProperty('--flow-width', `${width.toFixed(2)}px`);
      group.style.setProperty('--flow-soft-width', `${Math.max(1.05, width * 0.62).toFixed(2)}px`);
      group.style.setProperty('--flow-opacity', flowOpacity(value).toFixed(2));
    }
  }


  heatTermNote(name, value, result) {
    if (name === 'Conduction') return 'Set to constant zero in this whole-body ISO 7730 PMV model. Direct conductive contact would require an additional model outside the standard PMV balance.';
    if (name === 'Metabolic rate M') return 'Total metabolic heat generated by the body from activity. Higher M generally shifts the thermal state warmer.';
    if (name === 'External work W') return 'Mechanical work exported from the body. In typical indoor comfort analysis it is usually zero or very small.';
    if (name === 'Internal heat production M − W') return 'Net heat that remains available for exchange with the environment after subtracting external mechanical work from metabolism.';
    if (name === 'Radiation R') return value < 0 ? 'Net radiative heat gain from warmer surrounding surfaces to the clothed body. The arrow reverses toward the body.' : 'Net long-wave radiative heat loss from the clothed body to cooler surrounding surfaces.';
    if (name === 'Convection C') return value < 0 ? 'The air is effectively warming the body; convective flow is directed toward the body.' : 'Sensible heat loss to the room air. It increases when the air is cooler or air speed is higher.';
    if (name === 'Skin diffusion Ed') return 'Insensible latent heat loss by water diffusion through the skin. It exists even without visible sweating.';
    if (name === 'Sweating Esw') return 'Regulatory sweating heat loss. Near neutral or cool conditions it is often close to zero; it rises when the body needs stronger evaporative cooling.';
    if (name === 'Latent respiration Eres') return 'Latent heat loss carried by moisture in exhaled air.';
    if (name === 'Sensible respiration Cres') return 'Sensible heat loss needed to warm inhaled air to body-related temperature before exhalation.';
    if (name === 'Thermal load L') return value > 0 ? 'Positive thermal load means the body retains excess heat relative to neutrality, so PMV moves to the warm side.' : 'Negative thermal load means the body is losing more heat than neutral, so PMV moves to the cool side.';
    return value < 0 ? 'Net heat gain to the body under current conditions.' : 'Net heat loss from the body under current conditions.';
  }

  updateHeatTerms(result) {
    const h = result.heatBalance;
    const rows = [
      ['Metabolic rate M', h.metabolicRateWM2], ['External work W', h.externalWorkWM2], ['Internal heat production M − W', h.internalHeatProductionWM2],
      ['Radiation R', h.radiationWM2], ['Convection C', h.convectionWM2], ['Skin diffusion Ed', h.diffusionSkinWM2], ['Sweating Esw', h.sweatingWM2],
      ['Latent respiration Eres', h.latentRespirationWM2], ['Sensible respiration Cres', h.dryRespirationWM2], ['Conduction', 0], ['Thermal load L', h.thermalLoadWM2]
    ];
    const compactRows = rows.filter(([name]) => ['Internal heat production M − W', 'Radiation R', 'Convection C', 'Skin diffusion Ed', 'Sweating Esw', 'Latent respiration Eres', 'Sensible respiration Cres', 'Conduction', 'Thermal load L'].includes(name));
    const selected = this.state.showAdvanced ? rows : compactRows;
    qs(this.root, '#heatTerms').innerHTML = `<div class="heat-summary">Sign convention: positive exchange terms mean heat leaves the body; negative values mean heat enters the body. Conduction is fixed to zero in the ISO 7730 PMV formulation used here.</div><table class="heat-table"><thead><tr><th>Term</th><th>Value</th><th>Note</th></tr></thead><tbody>${selected.map(([name, value]) => `<tr><td>${name}</td><td>${this.heatDisplayValue(value, 2)}</td><td class="note-cell">${this.heatTermNote(name, value, result)}</td></tr>`).join('')}</tbody></table><p class="trace">tcl ${fmt(result.clothingSurfaceTemperatureC, 2)} °C · fcl ${fmt(result.clothingAreaFactor, 3)} · hc ${fmt(result.convectiveHeatTransferCoefficientWM2K, 2)} W/(m²K) · vapour pressure ${fmt(result.waterVapourPressurePa, 0)} Pa · iterations ${result.iterationCount} · heat-flow display ${this.heatUnitLabel()}${this.state.showTotalWatts ? ` using Adu ${fmt(this.state.bodySurfaceAreaM2, 1)} m²` : ''}</p>`;
  }

  updateDiagnosis(result) {
    const input = this.inputPayload();
    const warnings = validateApplicability(input);
    const cat = comfortCategory(result.pmv, result.ppdPercent);
    const p = psychrometricPoint(input.airTemperatureC, input.relativeHumidityPercent);
    const direction = result.pmv < -0.5 ? 'increase operative temperature, reduce air movement, or increase clothing insulation' : result.pmv > 0.5 ? 'reduce operative temperature, increase air movement, or reduce clothing insulation' : 'maintain current conditions';
    qs(this.root, '#diagnosisText').textContent = `The calculated sensation is ${sensationLabel(result.pmv).toLowerCase()} (PMV ${signedPmv(result.pmv, 2)}, PPD ${fmt(result.ppdPercent, 0)}%). Category ${cat === 'outside' ? 'criteria are not met' : cat + ' is met by whole-body PMV/PPD criteria'}. Current humidity ratio is ${fmt(p.humidityRatioGKg, 1)} g/kg. To move toward PMV 0, ${direction}.`;
    qs(this.root, '#warnings').innerHTML = warnings.length ? warnings.map(w => `<span>${w}</span>`).join('') : '<span class="ok">No physical input-range warning. Clothing choice is evaluated by PMV/PPD, not flagged as wrong.</span>';
  }

  showError(error) {
    qs(this.root, '#warnings').innerHTML = `<span>${error.message || error}</span>`;
  }
}
