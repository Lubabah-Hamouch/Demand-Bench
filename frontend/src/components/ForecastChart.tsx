import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { Forecast, History } from '../api/client'
import { monthName, shortDate, units, weekday } from '../lib/format'
import { colors } from '../theme'

interface Row {
  date: string
  actual?: number
  usual?: number | null
  anomaly?: boolean
  base?: number
  baseRange?: [number, number]
  scenario?: number
  scenarioRange?: [number, number]
}

function buildRows(history: History, baseline: Forecast, scenario: Forecast | null): Row[] {
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

interface DotProps {
  cx?: number
  cy?: number
  index?: number
  payload?: Row
}

function AnomalyDot({ cx, cy, payload }: DotProps) {
  if (!payload?.anomaly || cx === undefined || cy === undefined) return <g />
  return <circle cx={cx} cy={cy} r={5.5} fill="#FFFFFF" stroke={colors.coral} strokeWidth={3} />
}

interface TooltipProps {
  active?: boolean
  label?: string | number
  payload?: ReadonlyArray<{ payload?: Row }>
  scenarioActive: boolean
}

function ChartTooltip({ active, payload, scenarioActive }: TooltipProps) {
  const row = payload?.[0]?.payload
  if (!active || !row) return null
  const lines: { label: string; value: string; className: string }[] = []
  if (row.baseRange === undefined) {
    lines.push({ label: 'Sold', value: units(row.actual ?? 0), className: 'text-brand' })
    if (row.anomaly && row.usual != null) lines.push({ label: 'Usually', value: `~${units(row.usual)}`, className: 'text-coral-deep' })
  } else {
    const shown = scenarioActive && row.scenario !== undefined ? row.scenario : row.base
    const range = scenarioActive && row.scenarioRange ? row.scenarioRange : row.baseRange
    lines.push({ label: scenarioActive ? 'Scenario' : 'Forecast', value: units(shown ?? 0), className: 'text-coral-deep' })
    lines.push({ label: 'Likely range', value: `${units(range[0])}–${units(range[1])}`, className: 'text-ink' })
    if (scenarioActive && row.base !== undefined) lines.push({ label: 'Without scenario', value: units(row.base), className: 'text-muted' })
  }
  return (
    <div className="min-w-[180px] border-t-4 border-brand bg-white px-3 py-2.5 text-[13.5px] shadow-[0_6px_18px_rgba(16,36,26,0.16)]">
      <div className="mb-1 font-semibold">
        {weekday(row.date)}, {shortDate(row.date)}
      </div>
      {lines.map((l) => (
        <div key={l.label} className="flex justify-between gap-4">
          <span className="text-muted">{l.label}</span>
          <span className={`tabular font-semibold ${l.className}`}>{l.value}</span>
        </div>
      ))}
    </div>
  )
}

interface Props {
  history: History
  baseline: Forecast
  scenario: Forecast | null
}

export function ForecastChart({ history, baseline, scenario }: Props) {
  const rows = buildRows(history, baseline, scenario)
  const scenarioActive = scenario !== null
  const firstForecast = baseline.points[0]?.date
  const lastForecast = baseline.points[baseline.points.length - 1]?.date
  const monthTicks = rows.filter((r, i) => i > 2 && i < rows.length - 3 && r.date.endsWith('-01')).map((r) => r.date)

  return (
    <div className="h-[380px] w-full" role="img" aria-label="Daily units sold over 180 days with a four-week forecast and its likely range">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={rows} margin={{ top: 28, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke={colors.rule} />
          <ReferenceArea x1={firstForecast} x2={lastForecast} fill={colors.coral} fillOpacity={0.06} ifOverflow="extendDomain" />
          <ReferenceLine
            x={firstForecast}
            stroke={colors.coral}
            strokeWidth={2}
            label={{ value: 'NEXT 4 WEEKS', position: 'insideTopLeft', fill: colors.coralDeep, fontSize: 12, fontWeight: 600, letterSpacing: 1.5, dy: -22 }}
          />
          <XAxis
            dataKey="date"
            ticks={monthTicks}
            tickFormatter={monthName}
            tick={{ fill: colors.muted, fontSize: 12.5 }}
            axisLine={{ stroke: colors.rule }}
            tickLine={false}
            interval={0}
          />
          <YAxis
            width={48}
            tick={{ fill: colors.muted, fontSize: 12.5 }}
            axisLine={false}
            tickLine={false}
            allowDecimals={false}
          />
          <Tooltip
            content={(props) => (
              <ChartTooltip
                active={props.active}
                payload={props.payload as TooltipProps['payload']}
                scenarioActive={scenarioActive}
              />
            )}
            cursor={{ stroke: colors.ink, strokeOpacity: 0.35, strokeWidth: 1.5 }}
            isAnimationActive={false}
          />
          {!scenarioActive && (
            <Area dataKey="baseRange" stroke="none" fill={colors.coral} fillOpacity={0.17} isAnimationActive={false} activeDot={false} />
          )}
          {scenarioActive && (
            <Area dataKey="scenarioRange" stroke="none" fill={colors.coral} fillOpacity={0.17} isAnimationActive={false} activeDot={false} />
          )}
          <Line
            dataKey="actual"
            stroke={colors.brand}
            strokeWidth={1.5}
            dot={(props: DotProps) => <AnomalyDot key={`dot-${props.index}`} {...props} />}
            activeDot={{ r: 4, fill: colors.brand, stroke: '#FFFFFF' }}
            isAnimationActive={false}
            connectNulls={false}
          />
          <Line
            dataKey="base"
            stroke={scenarioActive ? colors.ghost : colors.coral}
            strokeWidth={scenarioActive ? 1.6 : 2.6}
            strokeDasharray={scenarioActive ? '6 5' : undefined}
            dot={false}
            activeDot={scenarioActive ? false : { r: 4, fill: colors.coral, stroke: '#FFFFFF' }}
            isAnimationActive={false}
          />
          {scenarioActive && (
            <Line
              dataKey="scenario"
              stroke={colors.coral}
              strokeWidth={2.6}
              dot={false}
              activeDot={{ r: 4, fill: colors.coral, stroke: '#FFFFFF' }}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  )
}

export function ChartLegend({ scenarioActive }: { scenarioActive: boolean }) {
  // Sized to sit beside the section title at 1440px even with the scenario entry.
  const item = 'inline-flex items-center gap-1.5 whitespace-nowrap'
  return (
    <div className="flex flex-wrap gap-x-3.5 gap-y-1.5 text-[12.5px]">
      <span className={item}>
        <span className="inline-block h-0.5 w-3.5 bg-brand" />
        Units sold
      </span>
      <span className={item}>
        <span className="inline-block h-[3px] w-3.5 bg-coral" />
        {scenarioActive ? 'Forecast with scenario' : 'Forecast'}
      </span>
      <span className={item}>
        <span className="inline-block h-2.5 w-3.5 bg-coral/20" />
        Likely range (80%)
      </span>
      {scenarioActive && (
        <span className={item}>
          <span className="inline-block w-3.5 border-t-2 border-dashed border-ghost" />
          Without scenario
        </span>
      )}
      <span className={item}>
        <span className="inline-block size-[11px] rounded-full border-[3px] border-coral bg-white" />
        Unusual day
      </span>
    </div>
  )
}
