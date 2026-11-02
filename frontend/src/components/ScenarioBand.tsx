import { money, num, signedPct } from '../lib/format'
import { GLOSSARY } from '../lib/glossary'
import { Explain } from './Explain'

interface Props {
  promo: boolean
  pct: number
  price: number | null
  baseTotal: number | null
  scenarioTotal: number | null
  updating: boolean
  error: string | null
  onPromo: (on: boolean) => void
  onPct: (pct: number) => void
  onReset: () => void
}

export function ScenarioBand({ promo, pct, price, baseTotal, scenarioTotal, updating, error, onPromo, onPct, onReset }: Props) {
  const active = promo || pct !== 0
  const ready = active && baseTotal !== null && scenarioTotal !== null
  const change = ready && baseTotal > 0 ? scenarioTotal / baseTotal - 1 : 0

  // Exactly equal totals, not a change that merely rounds to 0.0%.
  const unchanged = ready && scenarioTotal === baseTotal
  // Which way the constraint points: a promotion or price cut can only raise the forecast,
  // a price rise can only lower it.
  const lever = promo && pct > 0 ? null : promo ? 'promotion' : pct < 0 ? 'price cut' : 'price rise'
  const [never, maybe] = lever === 'price rise' ? ['raise', 'lower'] : ['lower', 'raise']

  let note = 'Change the price or add a promotion to see the effect'
  if (error) note = `Couldn't re-score: ${error}`
  else if (active && !ready) note = 'Re-scoring…'
  else if (ready) note = `${num(scenarioTotal)} units over four weeks, vs ${num(baseTotal)} without it`

  return (
    <section aria-label="Scenario" className="flex flex-wrap items-center gap-x-6 gap-y-4 bg-brand-tint px-10 py-5">
      <div className="kicker flex-none text-brand">Try a scenario</div>
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center font-semibold">
          Promotion
          <Explain {...GLOSSARY.promotion} />
        </span>
        <button
          type="button"
          aria-pressed={promo}
          onClick={() => onPromo(!promo)}
          className={`min-h-10 min-w-28 rounded-full border-2 px-4 text-sm font-bold ${
            promo ? 'border-coral bg-coral text-ink' : 'border-brand bg-white text-brand'
          }`}
        >
          {promo ? 'Promo on' : 'No promo'}
        </button>
      </div>
      <div className="@container min-w-[180px] flex-1">
        <div className="flex items-baseline justify-between gap-2.5">
          <span className="inline-flex items-center">
            <label htmlFor="price-change" className="font-semibold">
              Price
            </label>
            <Explain {...GLOSSARY.price} />
          </span>
          {/* One line always; "vs list price" only where the column has room for it (the
              scale below marks the list price either way). */}
          <span className="tabular text-sm whitespace-nowrap">
            <span className="font-semibold">{price === null ? '—' : money(price * (1 + pct / 100))}</span>{' '}
            <span className="text-muted">
              {pct === 0 ? (
                'list price'
              ) : (
                <>
                  {`${pct > 0 ? '+' : '−'}${Math.abs(pct)}%`}
                  <span className="hidden @min-[232px]:inline"> vs list price</span>
                </>
              )}
            </span>
          </span>
        </div>
        <input
          id="price-change"
          type="range"
          min={-30}
          max={30}
          step={5}
          value={pct}
          disabled={price === null}
          onChange={(e) => onPct(Number(e.target.value))}
          className="h-8 w-full accent-coral disabled:opacity-50"
        />
        <div className="tabular flex justify-between text-xs text-muted">
          <span>−30%</span>
          <span>list price</span>
          <span>+30%</span>
        </div>
      </div>
      {/* Fixed width, so the row does not reflow as the result text changes. */}
      <div className="flex w-[352px] flex-none items-center gap-3" aria-live="polite">
        <span
          className={`font-display tabular w-[170px] flex-none text-right text-[52px] leading-none font-bold transition-opacity ${
            ready ? 'text-coral' : 'text-ghost'
          } ${updating ? 'opacity-50' : ''}`}
        >
          {ready ? signedPct(change) : '±0%'}
        </span>
        <span className="min-w-0 flex-1 text-sm leading-snug text-ink">
          {note}
          <Explain {...GLOSSARY.scenarioResult} />
        </span>
      </div>
      <button
        type="button"
        onClick={onReset}
        disabled={!active}
        className="min-h-10 flex-none rounded-md border-[1.5px] border-brand px-3.5 font-semibold text-brand hover:bg-white disabled:opacity-40"
      >
        Reset
      </button>
      {unchanged && (
        <p role="note" className="basis-full border-l-4 border-brand bg-white px-3.5 py-2 text-[13px] leading-snug text-ink">
          <span className="font-semibold text-brand">No change for this item</span> —{' '}
          {lever
            ? `the monotone constraint only guarantees a ${lever} won’t ${never} the forecast, not that it will ${maybe} it.`
            : 'the monotone constraint only fixes which way each change can push the forecast, not that it will move it.'}
          <Explain {...GLOSSARY.monotone} />
        </p>
      )}
    </section>
  )
}
