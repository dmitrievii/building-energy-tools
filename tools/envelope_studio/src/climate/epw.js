import {relativeHumidityFromDewPoint} from '../engine/psychrometrics.js';

export function parseEpw(text) {
  const lines = String(text).replace(/\r/g, '').split('\n').filter(Boolean);
  if (lines.length < 9 || !lines[0].startsWith('LOCATION,')) throw new Error('Not a valid EPW file');
  const location = lines[0].split(',');
  const records = [];
  for (const line of lines.slice(8)) {
    const c = line.split(',');
    if (c.length < 10) continue;
    const year = Number(c[0]);
    const month = Number(c[1]);
    const day = Number(c[2]);
    const hour = Number(c[3]);
    const dryBulbC = Number(c[6]);
    const dewPointC = Number(c[7]);
    let rh = Number(c[8]) / 100;
    if (!Number.isFinite(rh) && Number.isFinite(dewPointC)) rh = relativeHumidityFromDewPoint(dryBulbC, dewPointC);
    records.push({year, month, day, hour, dryBulbC, dewPointC, rh, pressurePa: Number(c[9])});
  }
  return {
    meta: {city: location[1], region: location[2], country: location[3], source: location[4], wmo: location[5], latitude: Number(location[6]), longitude: Number(location[7]), timezone: Number(location[8]), elevation_m: Number(location[9])},
    records,
  };
}

export function monthlyMeans(records) {
  const groups = Array.from({length: 12}, () => []);
  records.forEach(r => { if (r.month >= 1 && r.month <= 12) groups[r.month - 1].push(r); });
  return groups.map((g, i) => ({
    month: i + 1,
    dryBulbC: g.reduce((s, r) => s + r.dryBulbC, 0) / Math.max(1, g.length),
    rh: g.reduce((s, r) => s + r.rh, 0) / Math.max(1, g.length),
    hours: g.length,
  }));
}
