import test from 'node:test';
import assert from 'node:assert/strict';
import { renderPpdCurve, renderThermalComfortArea, renderPsychrometric, renderPpdVelocityCloMap } from '../src/charts/charts.js';

class FakeElement {
  constructor(tag) { this.tag = tag; this.children = []; this.attributes = {}; this.textContent = ''; }
  setAttribute(k, v) { this.attributes[k] = String(v); }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  queryAll(tag) { return [...this.children.flatMap(c => [c, ...(c.queryAll ? c.queryAll(tag) : [])])].filter(c => c.tag === tag); }
}

global.document = {
  createElementNS(_ns, tag) { return new FakeElement(tag); }
};

const input = {
  airTemperatureC: 22,
  meanRadiantTemperatureC: 22,
  relativeAirVelocityMS: 0.1,
  relativeHumidityPercent: 60,
  metabolicRateMet: 1.2,
  clothingInsulationClo: 0.5,
  externalWorkMet: 0
};

test('chart renderers create SVG roots', () => {
  const containers = [new FakeElement('div'), new FakeElement('div'), new FakeElement('div'), new FakeElement('div')];
  renderPpdCurve(containers[0], -0.75, 17);
  renderThermalComfortArea(containers[1], input);
  renderPsychrometric(containers[2], input);
  renderPpdVelocityCloMap(containers[3], input);
  for (const container of containers) {
    assert.equal(container.children.length, 1);
    assert.equal(container.children[0].tag, 'svg');
    assert.ok(container.children[0].children.length >= 5);
  }
});
