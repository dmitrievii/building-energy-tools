export const MET_TO_W_M2 = 58.15;
export const CLO_TO_M2K_W = 0.155;

export function metToWM2(met) {
  return Number(met) * MET_TO_W_M2;
}

export function cloToM2KW(clo) {
  return Number(clo) * CLO_TO_M2K_W;
}

export function saturatedVapourPressureIso7730KPa(airTemperatureC) {
  const ta = Number(airTemperatureC);
  if (!Number.isFinite(ta)) throw new Error('airTemperatureC must be finite');
  return Math.exp(16.6536 - 4030.183 / (ta + 235.0));
}

export function waterVapourPressureFromRelativeHumidity(airTemperatureC, relativeHumidityPercent) {
  const rh = Number(relativeHumidityPercent);
  if (rh < 0 || rh > 100) throw new Error('relativeHumidityPercent must be between 0 and 100');
  return rh * 10.0 * saturatedVapourPressureIso7730KPa(Number(airTemperatureC));
}

export function clothingAreaFactor(clothingInsulationM2KW) {
  const icl = Number(clothingInsulationM2KW);
  if (icl < 0) throw new Error('clothing insulation must be non-negative');
  return icl <= 0.078 ? 1.0 + 1.29 * icl : 1.05 + 0.645 * icl;
}

export function convectiveHeatTransferCoefficient(tClothingC, airTemperatureC, relativeAirVelocityMS) {
  const v = Number(relativeAirVelocityMS);
  if (v < 0) throw new Error('relative air velocity must be non-negative');
  const natural = 2.38 * Math.abs(Number(tClothingC) - Number(airTemperatureC)) ** 0.25;
  const forced = 12.1 * Math.sqrt(v);
  return Math.max(natural, forced);
}

export function solveClothingSurfaceTemperature({ metabolicRateWM2, externalWorkWM2, clothingInsulationM2KW, airTemperatureC, meanRadiantTemperatureC, relativeAirVelocityMS, tolerance = 0.00015, maxIterations = 150 }) {
  const m = Number(metabolicRateWM2);
  const w = Number(externalWorkWM2);
  const icl = Number(clothingInsulationM2KW);
  const ta = Number(airTemperatureC);
  const tr = Number(meanRadiantTemperatureC);
  const v = Number(relativeAirVelocityMS);
  if (![m, w, icl, ta, tr, v, tolerance].every(Number.isFinite)) throw new Error('all numeric inputs must be finite');
  if (w > m) throw new Error('externalWork must not exceed metabolic rate');
  if (icl < 0 || v < 0) throw new Error('clothing insulation and air velocity must be non-negative');

  const mw = m - w;
  const fcl = clothingAreaFactor(icl);
  const hcf = 12.1 * Math.sqrt(v);
  const taa = ta + 273.0;
  const tra = tr + 273.0;
  const tcla = taa + (35.5 - ta) / (3.5 * (6.45 * icl + 0.1));
  const p1 = icl * fcl;
  const p2 = p1 * 3.96;
  const p3 = p1 * 100.0;
  const p4 = p1 * taa;
  const p5 = 308.7 - 0.028 * mw + p2 * (tra / 100.0) ** 4;

  let xn = tcla / 100.0;
  let xf = xn;
  let hc = hcf;
  for (let iteration = 1; iteration <= maxIterations; iteration += 1) {
    xf = (xf + xn) / 2.0;
    const hcn = 2.38 * Math.abs(100.0 * xf - taa) ** 0.25;
    hc = Math.max(hcf, hcn);
    xn = (p5 + p4 * hc - p2 * xf ** 4) / (100.0 + p3 * hc);
    if (Math.abs(xn - xf) <= tolerance) {
      return {
        clothingSurfaceTemperatureC: 100.0 * xn - 273.0,
        convectiveHeatTransferCoefficientWM2K: hc,
        iterationCount: iteration,
        xN: xn
      };
    }
  }
  throw new Error('clothing surface temperature iteration did not converge');
}

export function predictedPercentageDissatisfied(pmv) {
  const value = Number(pmv);
  if (!Number.isFinite(value)) throw new Error('pmv must be finite');
  return 100.0 - 95.0 * Math.exp(-0.03353 * value ** 4 - 0.2179 * value ** 2);
}

export function calculatePmvSI({ metabolicRateWM2, externalWorkWM2 = 0, clothingInsulationM2KW, airTemperatureC, meanRadiantTemperatureC, relativeAirVelocityMS, waterVapourPressurePa }) {
  const m = Number(metabolicRateWM2);
  const w = Number(externalWorkWM2);
  const icl = Number(clothingInsulationM2KW);
  const ta = Number(airTemperatureC);
  const tr = Number(meanRadiantTemperatureC);
  const v = Number(relativeAirVelocityMS);
  const pa = Number(waterVapourPressurePa);
  if (![m, w, icl, ta, tr, v, pa].every(Number.isFinite)) throw new Error('all PMV inputs must be finite');
  if (pa < 0) throw new Error('water vapour pressure must be non-negative');

  const surface = solveClothingSurfaceTemperature({
    metabolicRateWM2: m,
    externalWorkWM2: w,
    clothingInsulationM2KW: icl,
    airTemperatureC: ta,
    meanRadiantTemperatureC: tr,
    relativeAirVelocityMS: v
  });
  const fcl = clothingAreaFactor(icl);
  const mw = m - w;
  const tra = tr + 273.0;

  const heatLossDiffusionSkinWM2 = 3.05e-3 * (5733.0 - 6.99 * mw - pa);
  const heatLossSweatingWM2 = mw > 58.15 ? 0.42 * (mw - 58.15) : 0.0;
  const heatLossLatentRespirationWM2 = 1.7e-5 * m * (5867.0 - pa);
  const heatLossDryRespirationWM2 = 0.0014 * m * (34.0 - ta);
  const heatLossRadiationWM2 = 3.96 * fcl * (surface.xN ** 4 - (tra / 100.0) ** 4);
  const heatLossConvectionWM2 = fcl * surface.convectiveHeatTransferCoefficientWM2K * (surface.clothingSurfaceTemperatureC - ta);
  const thermalSensationTransferCoefficient = 0.303 * Math.exp(-0.036 * m) + 0.028;
  const thermalLoadWM2 = mw - heatLossDiffusionSkinWM2 - heatLossSweatingWM2 - heatLossLatentRespirationWM2 - heatLossDryRespirationWM2 - heatLossRadiationWM2 - heatLossConvectionWM2;
  const pmv = thermalSensationTransferCoefficient * thermalLoadWM2;
  const ppdPercent = predictedPercentageDissatisfied(pmv);

  return {
    pmv,
    ppdPercent,
    clothingSurfaceTemperatureC: surface.clothingSurfaceTemperatureC,
    convectiveHeatTransferCoefficientWM2K: surface.convectiveHeatTransferCoefficientWM2K,
    clothingAreaFactor: fcl,
    waterVapourPressurePa: pa,
    iterationCount: surface.iterationCount,
    heatBalance: {
      metabolicRateWM2: m,
      externalWorkWM2: w,
      internalHeatProductionWM2: mw,
      diffusionSkinWM2: heatLossDiffusionSkinWM2,
      sweatingWM2: heatLossSweatingWM2,
      latentRespirationWM2: heatLossLatentRespirationWM2,
      dryRespirationWM2: heatLossDryRespirationWM2,
      radiationWM2: heatLossRadiationWM2,
      convectionWM2: heatLossConvectionWM2,
      skinEvaporationWM2: heatLossDiffusionSkinWM2 + heatLossSweatingWM2,
      respirationWM2: heatLossLatentRespirationWM2 + heatLossDryRespirationWM2,
      conductionWM2: 0,
      totalModelLossWM2: heatLossDiffusionSkinWM2 + heatLossSweatingWM2 + heatLossLatentRespirationWM2 + heatLossDryRespirationWM2 + heatLossRadiationWM2 + heatLossConvectionWM2,
      thermalLoadWM2
    }
  };
}

export function calculatePmvFromStandardInputs(input, { checkApplicability = false } = {}) {
  if (checkApplicability) validateApplicability(input);
  const metabolicRateWM2 = metToWM2(input.metabolicRateMet);
  const externalWorkWM2 = metToWM2(input.externalWorkMet || 0);
  const clothingInsulationM2KW = cloToM2KW(input.clothingInsulationClo);
  const waterVapourPressurePa = input.waterVapourPressurePa ?? waterVapourPressureFromRelativeHumidity(input.airTemperatureC, input.relativeHumidityPercent);
  return calculatePmvSI({
    metabolicRateWM2,
    externalWorkWM2,
    clothingInsulationM2KW,
    airTemperatureC: input.airTemperatureC,
    meanRadiantTemperatureC: input.meanRadiantTemperatureC,
    relativeAirVelocityMS: input.relativeAirVelocityMS,
    waterVapourPressurePa
  });
}

export function validateApplicability(input) {
  const errors = [];
  if (!(input.metabolicRateMet >= 0.8 && input.metabolicRateMet <= 4.0)) errors.push('metabolic rate outside ISO 7730 PMV applicability range 0.8 to 4.0 met');
  if (!(input.clothingInsulationClo >= 0.0 && input.clothingInsulationClo <= 2.0)) errors.push('clothing insulation outside ISO 7730 PMV applicability range 0 to 2 clo');
  if (!(input.airTemperatureC >= 10.0 && input.airTemperatureC <= 30.0)) errors.push('air temperature outside ISO 7730 PMV applicability range 10 °C to 30 °C');
  if (!(input.meanRadiantTemperatureC >= 10.0 && input.meanRadiantTemperatureC <= 40.0)) errors.push('mean radiant temperature outside ISO 7730 PMV applicability range 10 °C to 40 °C');
  if (!(input.relativeAirVelocityMS >= 0.0 && input.relativeAirVelocityMS <= 1.0)) errors.push('relative air velocity outside ISO 7730 PMV applicability range 0 to 1 m/s');
  if (!(input.relativeHumidityPercent >= 0.0 && input.relativeHumidityPercent <= 100.0)) errors.push('relative humidity must be between 0 and 100 %');
  if ((input.externalWorkMet || 0) < 0) errors.push('external work must be non-negative');
  if ((input.externalWorkMet || 0) > input.metabolicRateMet) errors.push('external work must not exceed metabolic rate');
  return errors;
}

export const CATEGORY_LIMITS = {
  I: { ppdMax: 6, pmvMin: -0.2, pmvMax: 0.2 },
  II: { ppdMax: 10, pmvMin: -0.5, pmvMax: 0.5 },
  III: { ppdMax: 15, pmvMin: -0.7, pmvMax: 0.7 },
  IV: { ppdMax: 25, pmvMin: -1.0, pmvMax: 1.0 }
};

export function comfortCategory(pmv, ppd) {
  for (const cat of ['I', 'II', 'III', 'IV']) {
    const lim = CATEGORY_LIMITS[cat];
    if (pmv >= lim.pmvMin && pmv <= lim.pmvMax && ppd <= lim.ppdMax) return cat;
  }
  return 'outside';
}

export function sensationLabel(pmv) {
  if (pmv <= -2.5) return 'Freezing';
  if (pmv <= -1.5) return 'Cold';
  if (pmv <= -0.5) return 'Slightly Cool';
  if (pmv < 0.5) return 'Comfortable';
  if (pmv < 1.5) return 'Slightly Warm';
  if (pmv < 2.5) return 'Warm';
  return 'Overheated';
}

export function nearestPmvStateKey(pmv) {
  if (pmv <= -2.5) return 'pmv_-3_freezing';
  if (pmv <= -1.5) return 'pmv_-2_cold';
  if (pmv <= -0.5) return 'pmv_-1_slightly_cool';
  if (pmv < 0.5) return 'pmv_0_comfortable';
  if (pmv < 1.5) return 'pmv_+1_slightly_warm';
  if (pmv < 2.5) return 'pmv_+2_warm';
  return 'pmv_+3_overheated';
}

export function operativeTemperature(ta, tr, hc = null, hr = 4.7) {
  const hConv = Number.isFinite(hc) && hc > 0 ? hc : 4.0;
  return (hConv * Number(ta) + hr * Number(tr)) / (hConv + hr);
}
