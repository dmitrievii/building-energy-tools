import {vapourPressurePa, saturationPressurePa} from './psychrometrics.js';
import {interfaceState} from './thermal.js';

const EPS = 1e-10;

function slope(a, b) {
  return (b.p - a.p) / (b.x - a.x);
}

// Greatest convex minorant of discrete upper-bound points, with endpoints fixed.
export function lowerConvexHull(points) {
  const hull = [];
  for (const p of points) {
    while (hull.length >= 2) {
      const s1 = slope(hull[hull.length - 2], hull[hull.length - 1]);
      const s2 = slope(hull[hull.length - 1], p);
      if (s1 < s2 - EPS) break;
      hull.pop();
    }
    hull.push(p);
  }
  return hull;
}

function interpolateSegment(a, b, x) {
  if (Math.abs(b.x - a.x) < EPS) return a.p;
  const f = (x - a.x) / (b.x - a.x);
  return a.p + f * (b.p - a.p);
}

function solveInterval(allNodes, leftIndex, rightIndex, leftP, rightP) {
  const pts = [{x: allNodes[leftIndex].sd_m, p: leftP, nodeIndex: leftIndex, mandatory: true}];
  for (let i = leftIndex + 1; i < rightIndex; i += 1) {
    pts.push({x: allNodes[i].sd_m, p: allNodes[i].psat_Pa, nodeIndex: i, saturation: true});
  }
  pts.push({x: allNodes[rightIndex].sd_m, p: rightP, nodeIndex: rightIndex, mandatory: true});
  return lowerConvexHull(pts);
}

function uniqueSorted(values) {
  return [...new Set(values)].sort((a, b) => a - b);
}

export function solveSteadyProfile(nodes, pi_Pa, pe_Pa, wetNodeIndices = []) {
  const n = nodes.length;
  const mandatory = uniqueSorted([0, ...wetNodeIndices.filter(i => i > 0 && i < n - 1), n - 1]);
  const contactMap = new Map();
  const segments = [];
  for (let k = 0; k < mandatory.length - 1; k += 1) {
    const li = mandatory[k];
    const ri = mandatory[k + 1];
    const lp = li === 0 ? pi_Pa : nodes[li].psat_Pa;
    const rp = ri === n - 1 ? pe_Pa : nodes[ri].psat_Pa;
    const hull = solveInterval(nodes, li, ri, lp, rp);
    for (const h of hull) contactMap.set(h.nodeIndex, h);
    for (let j = 0; j < hull.length - 1; j += 1) segments.push([hull[j], hull[j + 1]]);
  }

  const p = new Array(n).fill(null);
  for (const [a, b] of segments) {
    for (let i = a.nodeIndex; i <= b.nodeIndex; i += 1) {
      if (p[i] == null) p[i] = interpolateSegment(a, b, nodes[i].sd_m);
    }
  }
  p[0] = pi_Pa;
  p[n - 1] = pe_Pa;

  const contacts = uniqueSorted([...contactMap.keys()].filter(i => i > 0 && i < n - 1));
  return {p_Pa: p, contacts, segments};
}

function fluxBetween(nodes, p, i, j, deltaAir_kg_m_s_Pa) {
  const dsd = nodes[j].sd_m - nodes[i].sd_m;
  if (!(dsd > 0)) return 0;
  return deltaAir_kg_m_s_Pa * (p[i] - p[j]) / dsd;
}

export function stepGlaser({
  layers,
  boundary,
  storedMass_kg_m2 = {},
  duration_s,
  deltaAir_kg_m_s_Pa = 2e-10,
  rsi = 0.13,
  rse = 0.04,
}) {
  if (!(duration_s > 0)) throw new RangeError('duration_s must be > 0');
  const thermal = interfaceState(layers, {...boundary, rsi, rse});

  // Vapour-diffusion coordinates run from the indoor vapour boundary (sd=0)
  // to the outdoor vapour boundary (sd=sum(sd_layer)). Internal material
  // interfaces are the only saturation constraints. Do not add a duplicate
  // outdoor-air node at the same sd as the outer material surface.
  const diffusionNodes = [{sd_m: 0, T_C: boundary.ti_C, psat_Pa: saturationPressurePa(boundary.ti_C), label: 'inside'}];
  let sd = 0;
  thermal.layers.forEach((layer, i) => {
    sd += layer.sd_m;
    if (i < thermal.layers.length - 1) {
      const tempNode = thermal.nodes[i + 2];
      diffusionNodes.push({sd_m: sd, T_C: tempNode.T_C, psat_Pa: saturationPressurePa(tempNode.T_C), label: `interface_${i}`});
    }
  });
  diffusionNodes.push({sd_m: sd, T_C: boundary.te_C, psat_Pa: saturationPressurePa(boundary.te_C), label: 'outside'});

  const pi = vapourPressurePa(boundary.ti_C, boundary.rhi);
  const pe = vapourPressurePa(boundary.te_C, boundary.rhe);
  let masses = Object.fromEntries(Object.entries(storedMass_kg_m2).map(([k, v]) => [Number(k), Math.max(0, Number(v) || 0)]));
  let remaining = duration_s;
  let lastProfile = null;
  let guard = 0;

  while (remaining > 1e-6 && guard++ < 100) {
    const wet = Object.keys(masses).map(Number).filter(i => masses[i] > 1e-12);
    const profile = solveSteadyProfile(diffusionNodes, pi, pe, wet);
    const active = uniqueSorted([...wet, ...profile.contacts]);
    const rates = {};
    for (const i of active) {
      const leftFlux = fluxBetween(diffusionNodes, profile.p_Pa, i - 1, i, deltaAir_kg_m_s_Pa);
      const rightFlux = fluxBetween(diffusionNodes, profile.p_Pa, i, i + 1, deltaAir_kg_m_s_Pa);
      rates[i] = leftFlux - rightFlux;
    }

    let dt = remaining;
    for (const i of wet) {
      const r = rates[i] ?? 0;
      if (r < -1e-18) dt = Math.min(dt, masses[i] / (-r));
    }
    if (!(dt > 0) || !Number.isFinite(dt)) break;

    for (const i of active) {
      const old = masses[i] ?? 0;
      const next = old + (rates[i] ?? 0) * dt;
      masses[i] = Math.max(0, next);
    }
    remaining -= dt;
    for (const [k, v] of Object.entries(masses)) if (v <= 1e-12) delete masses[k];
    lastProfile = {...profile, rates_kg_m2_s: rates};
  }

  if (!lastProfile) lastProfile = solveSteadyProfile(diffusionNodes, pi, pe, []);
  const totalStored = Object.values(masses).reduce((a, b) => a + b, 0);
  return {thermal, diffusionNodes, pi_Pa: pi, pe_Pa: pe, profile: lastProfile, storedMass_kg_m2: masses, totalStored_kg_m2: totalStored};
}

export function runSeries({layers, periods, initialStoredMass_kg_m2 = {}, rsi = 0.13, rse = 0.04, deltaAir_kg_m_s_Pa = 2e-10}) {
  let stored = {...initialStoredMass_kg_m2};
  const results = [];
  for (const period of periods) {
    const result = stepGlaser({layers, boundary: period, storedMass_kg_m2: stored, duration_s: period.duration_s, rsi, rse, deltaAir_kg_m_s_Pa});
    stored = result.storedMass_kg_m2;
    results.push({...result, timestamp: period.timestamp ?? null, duration_s: period.duration_s});
  }
  return {results, finalStoredMass_kg_m2: stored};
}
