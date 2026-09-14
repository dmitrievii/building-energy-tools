export function saturationPressurePa(tC) {
  if (!Number.isFinite(tC)) throw new TypeError('temperature must be finite');
  return tC >= 0
    ? 610.5 * Math.exp((17.269 * tC) / (237.3 + tC))
    : 610.5 * Math.exp((21.875 * tC) / (265.5 + tC));
}

export function vapourPressurePa(tC, rhFraction) {
  if (!(rhFraction >= 0 && rhFraction <= 1.5)) throw new RangeError('relative humidity must be a fraction');
  return rhFraction * saturationPressurePa(tC);
}

export function relativeHumidityFromDewPoint(tC, dewPointC) {
  return saturationPressurePa(dewPointC) / saturationPressurePa(tC);
}
