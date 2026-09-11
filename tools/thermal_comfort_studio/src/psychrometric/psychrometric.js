export const DEFAULT_PRESSURE_PA = 101325;

export function saturationVapourPressurePa(tC) {
  // Buck-style equation for chart geometry; ISO PMV itself uses Annex D helper in pmv.js.
  const t = Number(tC);
  return 611.21 * Math.exp((18.678 - t / 234.5) * (t / (257.14 + t)));
}

export function humidityRatioKgKg(tC, rhPercent, pressurePa = DEFAULT_PRESSURE_PA) {
  const rh = Math.max(0, Math.min(100, Number(rhPercent))) / 100;
  const pws = saturationVapourPressurePa(tC);
  const pw = Math.min(rh * pws, pressurePa * 0.999999);
  return 0.621945 * pw / Math.max(pressurePa - pw, 1e-9);
}

export function humidityRatioGKg(tC, rhPercent, pressurePa = DEFAULT_PRESSURE_PA) {
  return humidityRatioKgKg(tC, rhPercent, pressurePa) * 1000;
}

export function moistAirEnthalpyKJkg(tC, humidityRatioKgKgValue) {
  const w = Number(humidityRatioKgKgValue);
  const t = Number(tC);
  return 1.006 * t + w * (2501 + 1.86 * t);
}

export function psychrometricPoint(tC, rhPercent, pressurePa = DEFAULT_PRESSURE_PA) {
  const w = humidityRatioKgKg(tC, rhPercent, pressurePa);
  return {
    temperatureC: Number(tC),
    relativeHumidityPercent: Number(rhPercent),
    humidityRatioKgKg: w,
    humidityRatioGKg: w * 1000,
    enthalpyKJkg: moistAirEnthalpyKJkg(tC, w),
    vapourPressurePa: saturationVapourPressurePa(tC) * Number(rhPercent) / 100
  };
}

export function rhCurve(rhPercent, tMin = 0, tMax = 45, step = 1, pressurePa = DEFAULT_PRESSURE_PA) {
  const points = [];
  for (let t = tMin; t <= tMax; t += step) {
    points.push(psychrometricPoint(t, rhPercent, pressurePa));
  }
  return points;
}


export function vapourPressureFromHumidityRatioPa(humidityRatioKgKgValue, pressurePa = DEFAULT_PRESSURE_PA) {
  const w = Math.max(0, Number(humidityRatioKgKgValue));
  return pressurePa * w / (0.621945 + w);
}

export function relativeHumidityFromHumidityRatio(tC, humidityRatioKgKgValue, pressurePa = DEFAULT_PRESSURE_PA) {
  const pw = vapourPressureFromHumidityRatioPa(humidityRatioKgKgValue, pressurePa);
  const pws = saturationVapourPressurePa(tC);
  return Math.max(0, (pw / Math.max(pws, 1e-9)) * 100);
}
