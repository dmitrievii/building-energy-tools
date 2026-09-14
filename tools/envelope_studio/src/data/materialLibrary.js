function finite(v) {
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

export function normalizeMaterialRecord(record, {muPolicy='dry'} = {}) {
  const thermal = record?.thermal ?? {};
  const meta = record?.nonthermal_metadata ?? {};
  const lambda = finite(thermal?.conductivity?.constant_W_per_mK);
  const density = finite(thermal?.density?.constant_value);
  const cp = finite(thermal?.specific_heat_capacity?.constant_value);
  const muDirect = finite(meta.water_vapour_diffusion_resistance_factor);
  const muDry = finite(meta.water_vapour_diffusion_resistance_factor_dry);
  const muWet = finite(meta.water_vapour_diffusion_resistance_factor_wet);
  const fallback = muPolicy === 'wet' ? (muWet ?? muDry) : (muDry ?? muWet);
  return {
    id: String(record?.id ?? record?.name ?? crypto.randomUUID()),
    name: String(record?.name ?? 'Unnamed material'),
    category: String(record?.category ?? 'generic_materials'),
    lambda_W_mK: lambda,
    density_kg_m3: density,
    cp_J_kgK: cp,
    mu: muDirect ?? fallback,
    muDirect,
    muDry,
    muWet,
    hasMoistureData: (muDirect ?? muDry ?? muWet) != null,
    source: record?.source ?? null,
    raw: record,
  };
}

export function parseMaterialLibrary(text, options={}) {
  const raw = JSON.parse(text);
  if (!Array.isArray(raw?.materials)) throw new Error('Material library must contain a materials array');
  return {
    meta: {
      schema_id: raw.schema_id ?? null,
      library_id: raw.library_id ?? null,
      library_version: raw.library_version ?? null,
      name: raw.name ?? null,
    },
    materials: raw.materials.map(m => normalizeMaterialRecord(m, options)).filter(m => m.lambda_W_mK != null),
  };
}

export function searchMaterials(materials, query, limit=80) {
  const q = String(query ?? '').trim().toLocaleLowerCase();
  if (!q) return materials.slice(0, limit);
  const tokens = q.split(/\s+/).filter(Boolean);
  return materials
    .map(m => {
      const hay = `${m.name} ${m.category}`.toLocaleLowerCase();
      const score = tokens.reduce((s,t) => s + (hay.includes(t) ? 1 : 0), 0) + (hay.startsWith(q) ? 2 : 0);
      return {m,score};
    })
    .filter(x => x.score > 0)
    .sort((a,b) => b.score-a.score || a.m.name.localeCompare(b.m.name))
    .slice(0,limit)
    .map(x => x.m);
}
