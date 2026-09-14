import {runSeries} from '../engine/glaser.js';

export function buildMonthlyPeriods(rows) {
  return rows.map(row => ({
    timestamp: `month-${row.month}`,
    month: row.month,
    ti_C: Number(row.ti_C),
    te_C: Number(row.te_C),
    rhi: Number(row.rhi),
    rhe: Number(row.rhe),
    duration_s: Number(row.days) * 86400,
  }));
}

export function runMonthlyMode({layers, rows, rsi=0.25, rse=0.04, deltaAir_kg_m_s_Pa=2e-10}) {
  const periods = buildMonthlyPeriods(rows);
  return runSeries({layers, periods, rsi, rse, deltaAir_kg_m_s_Pa});
}
