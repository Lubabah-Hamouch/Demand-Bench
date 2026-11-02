import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ANOMALY_INDEX, forecastFor, HISTORY_DAYS, HORIZON, historyFor, SERIES } from '../test/fixtures'
import { colors } from '../theme'
import { buildRows } from '../lib/chartData'
import { ChartLegend, ForecastChart } from './ForecastChart'

// vi.mock is hoisted above the imports, so the helper is imported inside the factory.
vi.mock('recharts', async (importOriginal) => {
  const { withFixedSizeContainer } = await import('../test/recharts')
  return withFixedSizeContainer(await importOriginal<object>())
})

const series = SERIES[0]
const history = historyFor(series)
const baseline = forecastFor(series)
const scenario = forecastFor(series, { multiplier: 1.1 })

describe('buildRows (the data handed to the chart)', () => {
  it('has one row per observed day and per forecast day', () => {
    const rows = buildRows(history, baseline, null)
    expect(rows).toHaveLength(HISTORY_DAYS + HORIZON)
    expect(rows.slice(0, HISTORY_DAYS).every((r) => r.actual !== undefined && r.baseRange === undefined)).toBe(true)
    expect(rows.slice(HISTORY_DAYS).every((r) => r.actual === undefined && r.baseRange !== undefined)).toBe(true)
  })

  it('carries the forecast, range and anomaly flags from the API data', () => {
    const rows = buildRows(history, baseline, null)
    const firstForecast = rows[HISTORY_DAYS]
    expect(firstForecast).toMatchObject({
      date: baseline.points[0].date,
      base: baseline.points[0].forecast,
      baseRange: [baseline.points[0].lower, baseline.points[0].upper],
    })
    expect(rows.filter((r) => r.anomaly).map((r) => r.date)).toEqual([history.points[ANOMALY_INDEX].date])
  })

  it('joins the forecast line to the last observed day', () => {
    const rows = buildRows(history, baseline, scenario)
    const lastObserved = rows[HISTORY_DAYS - 1]
    expect(lastObserved.base).toBe(lastObserved.actual)
    expect(lastObserved.scenario).toBe(lastObserved.actual)
  })

  it('adds scenario values only when a scenario is given', () => {
    expect(buildRows(history, baseline, null).some((r) => r.scenario !== undefined && r.baseRange)).toBe(false)
    const rows = buildRows(history, baseline, scenario)
    expect(rows[HISTORY_DAYS]).toMatchObject({
      scenario: scenario.points[0].forecast,
      scenarioRange: [scenario.points[0].lower, scenario.points[0].upper],
    })
  })
})

describe('ForecastChart rendering', () => {
  it('marks each anomalous day with a ring in the accent color', () => {
    const { container } = render(<ForecastChart history={history} baseline={baseline} scenario={null} />)
    const rings = container.querySelectorAll(`circle[stroke="${colors.coral}"][fill="#FFFFFF"]`)
    expect(rings).toHaveLength(history.points.filter((p) => p.anomaly).length)
  })

  it('draws the baseline solid without a scenario and grey dashed with one', () => {
    const plain = render(<ForecastChart history={history} baseline={baseline} scenario={null} />)
    expect(plain.container.querySelector('path[stroke-dasharray="6 5"]')).toBeNull()
    plain.unmount()

    const { container } = render(<ForecastChart history={history} baseline={baseline} scenario={scenario} />)
    const dashed = container.querySelector('path[stroke-dasharray="6 5"]')
    expect(dashed).not.toBeNull()
    expect(dashed).toHaveAttribute('stroke', colors.ghost)
  })
})

describe('ChartLegend', () => {
  it('names the scenario line and the baseline only when a scenario is active', () => {
    const { rerender } = render(<ChartLegend scenarioActive={false} />)
    expect(screen.getByText('Forecast')).toBeInTheDocument()
    expect(screen.queryByText('Without scenario')).toBeNull()
    rerender(<ChartLegend scenarioActive />)
    expect(screen.getByText('With scenario')).toBeInTheDocument()
    expect(screen.getByText('Without scenario')).toBeInTheDocument()
  })
})
