import { useState } from 'react'
import { api, isOffline, type SeriesInfo, type SeriesQuery, type VolumeTier } from '../api/client'
import { describeSeries, num, STATE_CODES } from '../lib/format'
import { useAsync, useDebounced } from '../lib/hooks'
import { ErrorNote, Skeleton } from './Status'

const PAGE_SIZE = 25
const TIERS: { value: VolumeTier | 'all'; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Med' },
  { value: 'low', label: 'Low' },
]
const FILLER_WORDS = new Set(['/', 'dept', 'dept.', 'department', 'item', 'store', 'at', ','])

/**
 * Turns what people type ("Foods 3 / Item 090", "hobbies CA_2", "texas") into /series
 * filters: store ids and state names become filters, the remaining words are joined
 * with underscores to match the item id ("foods 3" -> "foods_3").
 */
function toSeriesQuery(text: string): Pick<SeriesQuery, 'q' | 'store_id' | 'state_id'> {
  const params: Pick<SeriesQuery, 'q' | 'store_id' | 'state_id'> = {}
  const words: string[] = []
  for (const raw of text.toLowerCase().split(/[\s,]+/)) {
    const token = raw.trim()
    if (!token || FILLER_WORDS.has(token)) continue
    if (/^(ca|tx|wi)_\d$/.test(token)) params.store_id = token.toUpperCase()
    else if (STATE_CODES[token]) params.state_id = STATE_CODES[token]
    else words.push(token.replace(/\/+/g, ''))
  }
  const q = words.filter(Boolean).join('_')
  if (q) params.q = q
  return params
}

interface Props {
  selected: { itemId: string; storeId: string }
  onSelect: (series: SeriesInfo) => void
  nSeries: number | null
}

export function Sidebar({ selected, onSelect, nSeries }: Props) {
  const [text, setText] = useState('')
  const [tier, setTier] = useState<VolumeTier | 'all'>('all')
  const [limit, setLimit] = useState(PAGE_SIZE)
  const search = useDebounced(text, 250)
  const params: SeriesQuery = {
    ...toSeriesQuery(search),
    volume_tier: tier === 'all' ? undefined : tier,
    limit,
  }
  const key = JSON.stringify(params)
  const page = useAsync(key, (signal) => api.series(params, signal))

  const items = page.data?.items ?? []
  const total = page.data?.total ?? 0

  return (
    // The green column runs the full page height; the list inside it stays in view.
    <div className="w-full shrink-0 bg-brand lg:w-[300px]">
      <aside
        aria-label="Choose a series"
        className="px-[18px] pb-7 pt-6 text-white lg:sticky lg:top-0 lg:max-h-screen lg:overflow-y-auto"
      >
        <div className="kicker text-on-brand-muted">Series</div>
        <label htmlFor="series-search" className="mt-3 block text-[13px] text-on-brand">
          Search item, department or store
        </label>
        <input
          id="series-search"
          type="search"
          value={text}
          onChange={(e) => {
            setText(e.target.value)
            setLimit(PAGE_SIZE)
          }}
          placeholder="Foods 3, CA_1, Hobbies…"
          className="mt-1.5 min-h-11 w-full rounded-md bg-white px-3 text-[15px] text-ink placeholder:text-muted"
        />
        <div role="group" aria-label="Volume tier" className="mt-3 flex flex-wrap gap-1.5">
          {TIERS.map((t) => {
            const active = tier === t.value
            return (
              <button
                key={t.value}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setTier(t.value)
                  setLimit(PAGE_SIZE)
                }}
                className={`min-h-9 rounded-full border-[1.5px] px-3 text-[13px] font-semibold ${
                  active ? 'border-white bg-white text-brand' : 'border-white/55 text-white hover:border-white'
                }`}
              >
                {t.label}
              </button>
            )
          })}
        </div>

        <div className="mt-[18px] flex flex-col gap-1" aria-busy={page.status === 'loading'}>
          {page.status === 'error' && !page.data &&
            (isOffline(page.error) ? (
              <p className="px-3.5 py-3 text-sm text-on-brand">Series will appear here once the API is reachable.</p>
            ) : (
              <ErrorNote error={page.error} onRetry={page.reload} title="Could not load series" compact />
            ))}
          {page.status === 'loading' && !page.data &&
            Array.from({ length: 7 }, (_, i) => (
              <div key={i} aria-hidden="true" className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 px-3.5 py-3">
                <div className="flex flex-col gap-2">
                  <Skeleton className="h-2.5 w-24 bg-white/15" />
                  <Skeleton className="h-5 w-28 bg-white/20" />
                  <Skeleton className="h-2.5 w-32 bg-white/15" />
                </div>
                <div className="flex flex-col items-end gap-2 self-center">
                  <Skeleton className="h-5 w-12 bg-white/20" />
                  <Skeleton className="h-2.5 w-16 bg-white/15" />
                </div>
              </div>
            ))}
          {items.map((s) => {
            const name = describeSeries(s.item_id, s.store_id)
            const isSelected = s.item_id === selected.itemId && s.store_id === selected.storeId
            return (
              <button
                key={`${s.item_id}/${s.store_id}`}
                type="button"
                onClick={() => onSelect(s)}
                aria-current={isSelected ? 'true' : undefined}
                className={`grid min-h-11 w-full grid-cols-[minmax(0,1fr)_auto] gap-x-2.5 gap-y-0.5 rounded-md px-3.5 py-3 text-left ${
                  isSelected ? 'bg-white' : 'hover:bg-white/10'
                }`}
              >
                <span className={`text-xs tracking-[0.02em] ${isSelected ? 'text-muted' : 'text-on-brand'}`}>{name.path}</span>
                <span className={`tabular row-span-2 self-center text-right text-[13px] ${isSelected ? 'text-muted' : 'text-on-brand'}`}>
                  <span className={`font-display block text-[22px] font-bold ${isSelected ? 'text-brand' : 'text-white'}`}>
                    {num(s.sales_last_28d)}
                  </span>
                  units / 4 wk
                </span>
                <span className="min-w-0">
                  <span className={`font-display block text-2xl font-bold ${isSelected ? 'text-brand' : 'text-white'}`}>{name.itemLabel}</span>
                  <span className={`mt-1 block text-[13px] ${isSelected ? 'text-muted' : 'text-on-brand'}`}>{name.place}</span>
                  <span className={`mt-1 block font-mono text-[11px] ${isSelected ? 'text-muted' : 'text-on-brand-muted'}`}>
                    {s.item_id} · {s.store_id}
                  </span>
                </span>
              </button>
            )
          })}
          {page.data && items.length === 0 && <p className="px-3.5 py-3.5 text-sm text-on-brand">Nothing matches that search.</p>}
          {page.data && items.length < total && (
            <button
              type="button"
              onClick={() => setLimit((n) => Math.min(n + PAGE_SIZE, 1000))}
              disabled={page.status === 'loading'}
              className="mt-2 min-h-10 rounded-md border-[1.5px] border-white/55 text-sm font-semibold text-white hover:border-white disabled:opacity-60"
            >
              {page.status === 'loading' ? 'Loading…' : `Show more (${num(total - items.length)} left)`}
            </button>
          )}
        </div>

        <p className="mt-[18px] border-t border-white/20 pt-3.5 text-[12.5px] text-on-brand">
          {page.data && (
            <>
              {num(items.length)} of {num(total)} matching series shown
              {nSeries !== null && ` (${num(nSeries)} in total)`}, busiest first.{' '}
            </>
          )}
          IDs and sales come from the M5 Walmart dataset, which does not include product names.
        </p>
      </aside>
    </div>
  )
}
