import { useState } from 'react'
import type { Forecast, History, SeriesBacktest, SeriesInfo } from '../api/client'
import { describeSeries, longDate, money, num, shortDate, TIER_LABEL } from '../lib/format'
import { GLOSSARY, type Explanation } from '../lib/glossary'
import { Explain } from './Explain'
import { Skeleton } from './Status'

interface Props {
  itemId: string
  storeId: string
  info: SeriesInfo | null
  baseline: Forecast | null
  shown: Forecast | null
  history: History | null
  scenarioActive: boolean
  /** null while loading; 'error' if the request failed. */
  backtest: SeriesBacktest | null | 'error'
  /** The API is unreachable: show only what the ids alone tell us. */
  offline: boolean
}

const total = (f: Forecast, key: 'forecast' | 'lower' | 'upper') => f.points.reduce((s, p) => s + p[key], 0)

interface Detail {
  label: string
  value: string
  tech: string
  explain?: Explanation
}

/**
 * This series' own backtest error and bias. When the backtest has no usable figure for
 * the series it says so, rather than showing the all-series number in its place.
 */
function backtestDetails(backtest: SeriesBacktest | null | 'error'): Detail[] {
  if (backtest === null) {
    return [
      { label: 'Backtest error, this series', value: '…', tech: 'loading', explain: GLOSSARY.seriesWape },
      { label: 'Forecast ÷ actual in backtests', value: '…', tech: 'loading', explain: GLOSSARY.seriesBias },
    ]
  }
  if (backtest === 'error') {
    return [{ label: 'Backtest for this series', value: 'Not available', tech: 'could not load backtest results', explain: GLOSSARY.seriesWape }]
  }
  const overallWape = backtest.overall_wape === null ? '' : ` · all series ${num(backtest.overall_wape, 3)}`
  const overallBias = backtest.overall_bias === null ? '' : ` · all series ${num(backtest.overall_bias * 100, 1)}%`
  if (backtest.wape === null || backtest.bias === null) {
    return [
      { label: 'Backtest for this series', value: 'Not available', tech: backtest.reason ?? 'no result for this series', explain: GLOSSARY.seriesWape },
    ]
  }
  const window =
    backtest.window_start && backtest.window_end
      ? `${shortDate(backtest.window_start)}–${shortDate(backtest.window_end)}`
      : `${backtest.n_folds} backtests`
  return [
    {
      label: 'Backtest error, this series',
      value: num(backtest.wape, 3),
      tech: `WAPE, ${backtest.n_folds} × 28 days, ${window}${overallWape}`,
      explain: GLOSSARY.seriesWape,
    },
    {
      label: 'Forecast ÷ actual in backtests',
      value: `${num(backtest.bias * 100, 1)}%`,
      tech: `${num(backtest.forecast_units ?? 0)} of ${num(backtest.actual_units ?? 0)} units${overallBias}`,
      explain: GLOSSARY.seriesBias,
    },
  ]
}

export function Summary({ itemId, storeId, info, baseline, shown, history, scenarioActive, backtest, offline }: Props) {
  const [open, setOpen] = useState(false)
  const name = describeSeries(itemId, storeId)

  const metaParts: string[] = []
  if (baseline?.sell_price != null) metaParts.push(`list price ${money(baseline.sell_price)}`)
  if (info) metaParts.push(TIER_LABEL[info.volume_tier])

  let sentence = <Skeleton className="mt-7 h-14 max-w-[760px]" />
  if (shown) {
    const units = total(shown, 'forecast')
    const last28 = shown.sales_last_28d
    const change = last28 > 0 ? units / last28 - 1 : null
    const compare =
      change === null
        ? 'with no sales in the previous four weeks'
        : Math.abs(change) < 0.005
          ? 'about the same as the previous four'
          : `${num(Math.abs(change) * 100)}% ${change > 0 ? 'more' : 'fewer'} than the previous four`
    sentence = (
      <p className="mt-6 max-w-[860px] text-2xl leading-snug">
        {scenarioActive ? 'With this scenario, expect about' : 'Expect about'}{' '}
        <span className="font-display tabular align-[-4px] text-[52px] font-bold text-coral">{num(units)}</span> units over
        the next four weeks, <span className="font-semibold text-brand">{compare}</span>.
      </p>
    )
  }

  const details: Detail[] | null =
    shown && history
      ? [
          {
            label: 'Likely range, next four weeks',
            value: `${num(total(shown, 'lower'))}–${num(total(shown, 'upper'))} units`,
            tech: 'sum of daily p10 and p90',
            explain: GLOSSARY.totalRange,
          },
          {
            label: 'Sold in the last four weeks',
            value: `${num(shown.sales_last_28d)} units`,
            tech: `actual, through ${shortDate(shown.trained_through)}`,
          },
          {
            label: 'Unusual days, last 180',
            value: num(history.n_anomalies),
            tech: '|z| > 3 vs prior 28 days',
            explain: GLOSSARY.unusualDay,
          },
          {
            label: 'On sale since',
            value: info?.on_sale_since ? longDate(info.on_sale_since) : '—',
            tech: info ? `${num(info.total_sales)} units sold in total` : '',
          },
          ...backtestDetails(backtest),
        ]
      : null

  return (
    <section aria-label="Summary" className="px-10 pb-7 pt-9">
      <div className="kicker text-brand">{name.crumb}</div>
      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-5 gap-y-1">
        <h1 className="font-display m-0 text-[88px] font-bold text-brand">{name.itemLabel}</h1>
        <span className="font-display text-[40px] font-semibold text-ink">{name.place}</span>
      </div>
      <div className="mt-3 text-[13px] text-muted">
        <span className="font-mono text-[12.5px]">
          M5 id {itemId} · {storeId}
        </span>
        {metaParts.map((part) => (
          <span key={part}> · {part}</span>
        ))}
      </div>

      {!offline && sentence}

      {!offline && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          aria-expanded={open}
          className="mt-[18px] inline-flex min-h-10 items-center gap-2 rounded-full border-[1.5px] border-brand bg-white px-3.5 text-sm font-semibold text-brand hover:bg-brand-tint"
        >
          <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden="true" className={open ? 'rotate-180' : ''}>
            <path d="M3 4.5 L6 7.5 L9 4.5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          {open ? 'Hide the numbers behind this' : 'Show the numbers behind this'}
        </button>
      )}
      {open && !offline && (
        <dl className="mt-4 grid grid-cols-[repeat(auto-fit,minmax(170px,1fr))] border-t-[3px] border-brand bg-surface-alt">
          {details
            ? details.map((d) => (
                <div key={d.label} className="border-b border-r border-rule px-4 py-3.5">
                  <dt className="text-[12.5px] text-muted">
                    <span>{d.label}</span>
                    {d.explain && <Explain {...d.explain} />}
                  </dt>
                  <dd className="tabular mt-1 text-xl font-semibold">{d.value}</dd>
                  <dd className="mt-0.5 text-xs leading-snug text-muted">{d.tech}</dd>
                </div>
              ))
            : Array.from({ length: 5 }, (_, i) => (
                <div key={i} className="border-b border-r border-rule px-4 py-3.5">
                  <Skeleton className="h-12" />
                </div>
              ))}
        </dl>
      )}
    </section>
  )
}
