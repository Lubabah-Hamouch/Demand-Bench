import { BACKTEST } from '../lib/content'
import { num } from '../lib/format'
import { GLOSSARY } from '../lib/glossary'
import { Explain } from './Explain'
import { SectionHeading } from './Status'

export function ModelQuality() {
  const worst = Math.max(...BACKTEST.sample.map((m) => m.wape))
  const model = BACKTEST.sample.find((m) => m.primary)!
  const naive = BACKTEST.sample[BACKTEST.sample.length - 1]
  const improvement = 1 - model.wape / naive.wape

  return (
    <section id="quality" aria-label="How much to trust it" className="min-w-0 flex-[1_1_360px]">
      <SectionHeading index="04" title="How much to trust it" />
      <p className="mt-1.5 text-sm text-muted">
        Backtests: the model forecast five past four-week periods ({BACKTEST.window}), each time using only earlier
        data, and the forecasts were checked against what actually sold.
      </p>
      <p className="mt-[18px] text-lg leading-snug">
        The model&apos;s error is{' '}
        <span className="font-display text-[34px] font-bold text-brand">{num(improvement * 100)}% lower</span> than repeating
        sales from four weeks earlier, and it stays on the right side of price and promo changes.
        <Explain {...GLOSSARY.monotone} />
      </p>
      <div className="mt-[18px] text-[12.5px] text-muted">
        Weighted error (WAPE)
        <Explain {...GLOSSARY.wape} /> on the same 200-series sample
        <Explain {...GLOSSARY.sample} /> · lower is better
      </div>
      <div className="mt-2.5 flex flex-col gap-2.5">
        {BACKTEST.sample.map((m) => (
          <div key={m.name}>
            <div className="flex justify-between text-sm">
              <span className={m.primary ? 'font-semibold' : ''}>
                {m.name} <span className="font-mono text-[11.5px] font-normal text-muted">{m.tech}</span>
              </span>
              <span className={`tabular ${m.primary ? 'font-bold' : ''}`}>{num(m.wape, 3)}</span>
            </div>
            <div className="mt-1 h-3 bg-surface-alt">
              <div className={`h-3 ${m.primary ? 'bg-brand' : 'bg-ghost'}`} style={{ width: `${(m.wape / worst) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      <dl className="tabular mt-5 grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] border-t border-rule">
        <div className="pr-3 pt-3">
          <dt className="text-[12.5px] text-muted">All 30,490 series</dt>
          <dd className="mt-0.5 text-lg font-semibold">WAPE {num(BACKTEST.full.wape, 3)}</dd>
        </div>
        <div className="pr-3 pt-3">
          <dt className="text-[12.5px] text-muted">
            Forecast ÷ actual
            <Explain {...GLOSSARY.bias} />
          </dt>
          <dd className="mt-0.5 text-lg font-semibold">{num(BACKTEST.full.bias * 100, 1)}%</dd>
        </div>
        <div className="pr-3 pt-3">
          <dt className="text-[12.5px] text-muted">
            Inside the 80% range
            <Explain {...GLOSSARY.coverage} />
          </dt>
          <dd className="mt-0.5 text-lg font-semibold">{num(BACKTEST.full.coverage * 100, 1)}%</dd>
          <dd className="text-xs text-muted">{num(BACKTEST.full.coverageWithSales * 100, 1)}% on days with sales</dd>
        </div>
      </dl>
    </section>
  )
}
