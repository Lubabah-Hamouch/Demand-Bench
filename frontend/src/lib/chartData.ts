import type { Forecast, History } from '../api/client'

export interface Row {
  date: string
  actual?: number
  usual?: number | null
  anomaly?: boolean
  base?: number
  baseRange?: [number, number]
  scenario?: number
  scenarioRange?: [number, number]
}

/** One row per day: 180 observed days, then the forecast days (joined at the last observed day). */
export function buildRows(history: History, baseline: Forecast, scenario: Forecast | null): Row[] {
  const rows: Row[] = history.points.map((p) => ({
    date: p.date,
    actual: p.sales,
    usual: p.rolling_mean,
    anomaly: p.anomaly,
  }))
  // Start the forecast lines at the last observed day so they join the actual line.
  const last = rows[rows.length - 1]
  if (last && last.actual !== undefined) {
    last.base = last.actual
    if (scenario) last.scenario = last.actual
  }
  baseline.points.forEach((p, i) => {
    const s = scenario?.points[i]
    rows.push({
      date: p.date,
      base: p.forecast,
      baseRange: [p.lower, p.upper],
      scenario: s?.forecast,
      scenarioRange: s ? [s.lower, s.upper] : undefined,
    })
  })
  return rows
}
