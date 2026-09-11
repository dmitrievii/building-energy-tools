import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { calculatePmvFromStandardInputs, nearestPmvStateKey, comfortCategory, cloToM2KW } from '../src/iso7730/pmv.js';
import { CLOTHING_PRESETS } from '../src/data/clothingPresets.js';
import { psychrometricPoint } from '../src/psychrometric/psychrometric.js';

const validationCases = JSON.parse(readFileSync(new URL('../src/data/iso7730/annex_d_table_d1_validation_cases.json', import.meta.url), 'utf8'));

test('Annex D PMV/PPD validation cases match rounded ISO references', () => {
  assert.equal(validationCases.length, 13);
  for (const c of validationCases) {
    const r = calculatePmvFromStandardInputs({
      airTemperatureC: c.air_temperature_c,
      meanRadiantTemperatureC: c.mean_radiant_temperature_c,
      relativeAirVelocityMS: c.relative_air_velocity_m_s,
      relativeHumidityPercent: c.relative_humidity_percent,
      metabolicRateMet: c.metabolic_rate_met,
      clothingInsulationClo: c.clothing_insulation_clo,
      externalWorkMet: c.external_work_met
    });
    assert.ok(Math.abs(r.pmv - c.reference_pmv) < 0.015, `${c.validation_case_id} PMV ${r.pmv} vs ${c.reference_pmv}`);
    assert.ok(Math.abs(Math.round(r.ppdPercent) - c.reference_ppd_percent) <= 1, `${c.validation_case_id} PPD ${r.ppdPercent} vs ${c.reference_ppd_percent}`);
  }
});

test('avatar PMV state mapping follows specified thresholds', () => {
  assert.equal(nearestPmvStateKey(-3.0), 'pmv_-3_freezing');
  assert.equal(nearestPmvStateKey(-2.5), 'pmv_-3_freezing');
  assert.equal(nearestPmvStateKey(-2.49), 'pmv_-2_cold');
  assert.equal(nearestPmvStateKey(-0.5), 'pmv_-1_slightly_cool');
  assert.equal(nearestPmvStateKey(-0.49), 'pmv_0_comfortable');
  assert.equal(nearestPmvStateKey(0.5), 'pmv_+1_slightly_warm');
  assert.equal(nearestPmvStateKey(2.5), 'pmv_+3_overheated');
});

test('clothing presets include corrected parka and extreme winter metadata', () => {
  const winter = CLOTHING_PRESETS.find(p => p.id === 'preset_07_winter_outdoor');
  assert.ok(winter);
  assert.equal(winter.clo, 1.71);
  assert.ok(winter.items.some(item => item.item_key === 'parka' && item.clo === 0.70));
  const extreme = CLOTHING_PRESETS.find(p => p.id === 'preset_08_extreme_winter_outdoor');
  assert.ok(extreme.items.some(item => item.item_key === 'thick_sweater' && item.clo === 0.35));
  assert.ok(extreme.items.some(item => item.item_key === 'parka' && item.clo === 0.70));
  assert.equal(Number(cloToM2KW(1).toFixed(3)), 0.155);
});

test('comfort category whole-body criteria select Annex A categories', () => {
  assert.equal(comfortCategory(0.0, 5.0), 'I');
  assert.equal(comfortCategory(0.45, 9.0), 'II');
  assert.equal(comfortCategory(0.65, 13.0), 'III');
  assert.equal(comfortCategory(0.9, 23.0), 'IV');
  assert.equal(comfortCategory(1.2, 35.0), 'outside');
});

test('psychrometric point is finite and chart-ready', () => {
  const p = psychrometricPoint(22, 60);
  assert.ok(p.humidityRatioGKg > 9 && p.humidityRatioGKg < 11);
  assert.ok(p.enthalpyKJkg > 45 && p.enthalpyKJkg < 50);
});
