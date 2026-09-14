import {runSeries} from '../engine/glaser.js';

export function buildHourlyPeriods(epwRecords, indoor={ti_C:22, rhi:0.5}) {
  return epwRecords.map((r, i) => {
    const state = typeof indoor === 'function' ? indoor(r, i) : indoor;
    return {
      timestamp: `${r.year}-${String(r.month).padStart(2,'0')}-${String(r.day).padStart(2,'0')}T${String(r.hour).padStart(2,'0')}:00`,
      month: r.month,
      ti_C: Number(state.ti_C),
      rhi: Number(state.rhi),
      te_C: Number(r.dryBulbC),
      rhe: Number(r.rh),
      duration_s: 3600,
    };
  });
}

export function runQuasiHourlyMode({layers, epwRecords, indoor, rsi=0.25, rse=0.04, deltaAir_kg_m_s_Pa=2e-10}) {
  const periods = buildHourlyPeriods(epwRecords, indoor);
  return runSeries({layers, periods, rsi, rse, deltaAir_kg_m_s_Pa});
}
