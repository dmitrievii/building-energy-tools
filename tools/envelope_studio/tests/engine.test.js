import test from 'node:test';
import assert from 'node:assert/strict';
import {saturationPressurePa} from '../src/engine/psychrometrics.js';
import {computeUValue} from '../src/engine/thermal.js';
import {lowerConvexHull, stepGlaser, runSeries} from '../src/engine/glaser.js';

const layers = [
  {name:'Innenputz', thickness_m:0.015, lambda_W_mK:0.7, mu:10},
  {name:'Mineralwolle', thickness_m:0.16, lambda_W_mK:0.038, mu:1.4},
  {name:'Mauerwerk', thickness_m:0.25, lambda_W_mK:0.35, mu:8},
  {name:'Außenputz', thickness_m:0.01, lambda_W_mK:1.0, mu:10},
];

test('saturation pressure reproduces Excel formula around 22 C', () => {
  assert.ok(Math.abs(saturationPressurePa(22) - 2642.41) < 1);
});

test('U-value is stable for reference wall', () => {
  const r = computeUValue(layers, {rsi:0.25, rse:0.04});
  assert.ok(Math.abs(r.totalR_m2K_W - 5.2462406015) < 1e-9);
  assert.ok(Math.abs(r.U_W_m2K - 0.1906126836) < 1e-9);
});

test('lower convex hull drops high non-governing points', () => {
  const h = lowerConvexHull([{x:0,p:1000},{x:1,p:1200},{x:2,p:500}]);
  assert.deepEqual(h.map(p => p.x), [0,2]);
});

test('winter reference case produces condensate and unique diffusion coordinates', () => {
  const r = stepGlaser({
    layers,
    boundary:{ti_C:22, te_C:-1.38, rhi:0.51105866735767, rhe:0.9},
    duration_s:31*86400,
    rsi:0.25,
    rse:0.04,
  });
  assert.ok(r.totalStored_kg_m2 > 0);
  assert.ok(Object.keys(r.storedMass_kg_m2).length >= 1);
  const sd = r.diffusionNodes.map(n => n.sd_m);
  assert.equal(new Set(sd).size, sd.length);
  assert.equal(r.diffusionNodes.at(-1).sd_m, r.thermal.totalSd_m);
});

test('period series carries condensate between periods and allows drying', () => {
  const out = runSeries({layers, rsi:0.25, rse:0.04, periods:[
    {ti_C:22, te_C:-5, rhi:0.55, rhe:0.9, duration_s:31*86400},
    {ti_C:24, te_C:20, rhi:0.45, rhe:0.5, duration_s:31*86400},
  ]});
  assert.equal(out.results.length, 2);
  assert.ok(out.results[0].totalStored_kg_m2 >= out.results[1].totalStored_kg_m2);
});
