export function normalizeLayer(layer) {
  const d = Number(layer.thickness_m);
  const lambda = Number(layer.lambda_W_mK);
  if (!(d > 0)) throw new RangeError(`invalid thickness for ${layer.name ?? 'layer'}`);
  if (!(lambda > 0)) throw new RangeError(`invalid conductivity for ${layer.name ?? 'layer'}`);
  const sd = Number.isFinite(Number(layer.sd_m))
    ? Number(layer.sd_m)
    : Number(layer.mu) * d;
  if (!(sd >= 0)) throw new RangeError(`invalid sd/mu for ${layer.name ?? 'layer'}`);
  return {...layer, thickness_m: d, lambda_W_mK: lambda, sd_m: sd, R_m2K_W: d / lambda};
}

export function computeUValue(layers, {rsi = 0.13, rse = 0.04} = {}) {
  const normalized = layers.map(normalizeLayer);
  const layerR = normalized.reduce((sum, layer) => sum + layer.R_m2K_W, 0);
  const totalR = rsi + layerR + rse;
  return {U_W_m2K: 1 / totalR, totalR_m2K_W: totalR, layerR_m2K_W: layerR, layers: normalized};
}

export function interfaceState(layers, {ti_C, te_C, rsi = 0.13, rse = 0.04}) {
  const u = computeUValue(layers, {rsi, rse});
  const q_W_m2 = (ti_C - te_C) / u.totalR_m2K_W;
  const nodes = [{index: 0, label: 'inside', Rcum: 0, sdcum: 0, T_C: ti_C}];
  let Rcum = rsi;
  let sdcum = 0;
  nodes.push({index: 1, label: 'inside_surface', Rcum, sdcum, T_C: ti_C - q_W_m2 * Rcum});
  u.layers.forEach((layer, i) => {
    Rcum += layer.R_m2K_W;
    sdcum += layer.sd_m;
    nodes.push({index: nodes.length, label: `after_${i}`, layerIndex: i, Rcum, sdcum, T_C: ti_C - q_W_m2 * Rcum});
  });
  Rcum += rse;
  nodes.push({index: nodes.length, label: 'outside', Rcum, sdcum, T_C: te_C});
  return {...u, q_W_m2, nodes, totalSd_m: sdcum};
}
