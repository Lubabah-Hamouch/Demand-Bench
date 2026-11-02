import { useEffect, useRef, useState, type ReactNode } from 'react'
import type { Forecast, ForecastPoint } from '../api/client'
import { num, shortDate, units, weekdayShort } from '../lib/format'

interface Props {
  shown: Forecast
  baseline: Forecast
  scenarioActive: boolean
  /** Phone widths: one row per day, grouped by week, instead of a weeks × weekdays grid. */
  compact?: boolean
}

/** The 28 forecast days, with week totals: four rows of seven, or (compact) a day per row. */
export function ForecastTable({ shown, baseline, scenarioActive, compact = false }: Props) {
  const weeks = Array.from({ length: Math.ceil(shown.points.length / 7) }, (_, w) => shown.points.slice(w * 7, w * 7 + 7))
  const weekTotal = (days: ForecastPoint[]) => num(days.reduce((s, p) => s + p.forecast, 0))
  // The small figure under each forecast: the likely range, or the change a scenario makes.
  const detail = (p: ForecastPoint, i: number) => {
    if (!scenarioActive) {
      return (
        <span className="text-muted">
          {units(p.lower)}–{units(p.upper)}
        </span>
      )
    }
    const delta = p.forecast - baseline.points[i].forecast
    return (
      <span className="font-semibold text-coral-deep">
        {delta >= 0 ? '+' : '−'}
        {units(Math.abs(delta))}
      </span>
    )
  }

  if (compact) {
    return (
      <table className="tabular mt-4 w-full border-collapse text-sm">
        <thead>
          <tr className="bg-surface-alt">
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-left text-xs font-semibold text-muted">
              Day
            </th>
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-right text-xs font-semibold text-muted">
              Units
            </th>
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-right text-xs font-semibold text-muted">
              {scenarioActive ? 'Change' : 'Likely range'}
            </th>
          </tr>
        </thead>
        {weeks.map((days, w) => (
          <tbody key={days[0].date}>
            <tr>
              <th scope="rowgroup" colSpan={2} className="border-b border-brand px-3 pb-1.5 pt-4 text-left font-semibold">
                Week of {shortDate(days[0].date)}
              </th>
              <td className="border-b border-brand px-3 pb-1.5 pt-4 text-right font-bold text-brand">{weekTotal(days)}</td>
            </tr>
            {days.map((p, k) => (
              <tr key={p.date} className={scenarioActive ? 'bg-coral/6' : ''}>
                <th scope="row" className="border-b border-rule px-3 py-2 text-left font-normal">
                  <span className="inline-block w-9 text-muted">{weekdayShort(p.date)}</span>
                  {shortDate(p.date)}
                </th>
                <td className="border-b border-rule px-3 py-2 text-right font-medium">{units(p.forecast)}</td>
                <td className="border-b border-rule px-3 py-2 text-right text-[12.5px]">{detail(p, w * 7 + k)}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
    )
  }

  const weekdays = weeks[0]?.map((p) => weekdayShort(p.date)) ?? []
  return (
    <HorizontalScroll>
      <table className="tabular w-full min-w-[680px] border-collapse text-sm">
        <thead>
          <tr className="bg-surface-alt">
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-left text-xs font-semibold text-muted">
              Week starting
            </th>
            {weekdays.map((d, i) => (
              <th key={i} scope="col" className="border-b-2 border-brand px-2.5 py-2.5 text-right text-xs font-semibold text-muted lg:px-3">
                {d}
              </th>
            ))}
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-right text-xs font-bold text-brand">
              Week total
            </th>
          </tr>
        </thead>
        <tbody>
          {weeks.map((days, w) => (
            <tr key={days[0].date}>
              <th scope="row" className="whitespace-nowrap border-b border-rule px-3 py-2.5 text-left font-semibold">
                {shortDate(days[0].date)}
              </th>
              {days.map((p, k) => (
                <td key={p.date} className={`border-b border-rule px-2.5 py-2 text-right lg:px-3 ${scenarioActive ? 'bg-coral/6' : ''}`}>
                  <div className="font-medium">{units(p.forecast)}</div>
                  <div className="text-[11.5px]">{detail(p, w * 7 + k)}</div>
                </td>
              ))}
              <td className="border-b border-rule px-3 py-2 text-right font-bold text-brand">{weekTotal(days)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </HorizontalScroll>
  )
}

/**
 * Scrolls its content sideways when it is wider than the container, with a fade on each
 * edge that has more content beyond it, so it is clear the table continues.
 */
function HorizontalScroll({ children }: { children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [more, setMore] = useState({ left: false, right: false })

  useEffect(() => {
    const el = ref.current
    if (!el) return
    const update = () =>
      setMore({ left: el.scrollLeft > 1, right: el.scrollLeft + el.clientWidth < el.scrollWidth - 1 })
    update()
    el.addEventListener('scroll', update, { passive: true })
    const observer = new ResizeObserver(update)
    observer.observe(el)
    return () => {
      el.removeEventListener('scroll', update)
      observer.disconnect()
    }
  }, [])

  const scrolls = more.left || more.right
  const fade = 'pointer-events-none absolute inset-y-0 w-10 from-white to-transparent transition-opacity'
  return (
    <div className="relative mt-4">
      {/* Focusable while it scrolls, so keyboard users can scroll it too. */}
      <div
        ref={ref}
        className="overflow-x-auto"
        tabIndex={scrolls ? 0 : undefined}
        role={scrolls ? 'group' : undefined}
        aria-label={scrolls ? 'Forecast table, scrolls sideways' : undefined}
      >
        {children}
      </div>
      <div aria-hidden="true" className={`${fade} left-0 bg-linear-to-r ${more.left ? 'opacity-100' : 'opacity-0'}`} />
      <div aria-hidden="true" className={`${fade} right-0 bg-linear-to-l ${more.right ? 'opacity-100' : 'opacity-0'}`} />
    </div>
  )
}
