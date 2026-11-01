import type { Forecast } from '../api/client'
import { num, shortDate, units, weekdayShort } from '../lib/format'

interface Props {
  shown: Forecast
  baseline: Forecast
  scenarioActive: boolean
}

/** The 28 forecast days as four rows of seven, with week totals. */
export function ForecastTable({ shown, baseline, scenarioActive }: Props) {
  const weeks = Array.from({ length: Math.ceil(shown.points.length / 7) }, (_, w) => shown.points.slice(w * 7, w * 7 + 7))
  const weekdays = weeks[0]?.map((p) => weekdayShort(p.date)) ?? []

  return (
    <div className="mt-4 overflow-x-auto">
      <table className="tabular w-full min-w-[760px] border-collapse text-sm">
        <thead>
          <tr className="bg-surface-alt">
            <th scope="col" className="border-b-2 border-brand px-3 py-2.5 text-left text-xs font-semibold text-muted">
              Week starting
            </th>
            {weekdays.map((d, i) => (
              <th key={i} scope="col" className="border-b-2 border-brand px-3 py-2.5 text-right text-xs font-semibold text-muted">
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
              {days.map((p, k) => {
                const base = baseline.points[w * 7 + k]
                const delta = p.forecast - base.forecast
                return (
                  <td key={p.date} className={`border-b border-rule px-3 py-2 text-right ${scenarioActive ? 'bg-coral/6' : ''}`}>
                    <div className="font-medium">{units(p.forecast)}</div>
                    {scenarioActive ? (
                      <div className="text-[11.5px] font-semibold text-coral-deep">
                        {delta >= 0 ? '+' : '−'}
                        {units(Math.abs(delta))}
                      </div>
                    ) : (
                      <div className="text-[11.5px] text-muted">
                        {units(p.lower)}–{units(p.upper)}
                      </div>
                    )}
                  </td>
                )
              })}
              <td className="border-b border-rule px-3 py-2 text-right font-bold text-brand">
                {num(days.reduce((s, p) => s + p.forecast, 0))}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
