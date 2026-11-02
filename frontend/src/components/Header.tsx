import { longDate, num } from '../lib/format'
import { GLOSSARY } from '../lib/glossary'
import { Explain } from './Explain'

interface Props {
  trainedThrough: string | null
  nSeries: number | null
  status: 'ok' | 'offline' | 'error'
}

export function Header({ trainedThrough, nSeries, status }: Props) {
  return (
    <header className="bg-brand text-white">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-2.5 px-7 py-3.5">
        <div className="flex items-baseline gap-2.5">
          <span className="font-display text-[30px] font-bold uppercase tracking-[0.01em]">DemandBench</span>
          <span className="inline-block size-[9px] rounded-full bg-coral" aria-hidden="true" />
        </div>
        <nav aria-label="Primary" className="flex flex-wrap gap-1">
          <a href="#forecast" className="border-b-[3px] border-coral px-3 py-2.5 font-semibold text-white no-underline">
            Forecasts
          </a>
          <a href="#drivers" className="px-3 py-2.5 text-on-brand no-underline hover:text-white">
            Drivers
          </a>
          <a href="#quality" className="px-3 py-2.5 text-on-brand no-underline hover:text-white">
            Model quality
          </a>
        </nav>
        <div className="tabular ml-auto text-[13px] text-on-brand">
          {trainedThrough ? (
            <>
              Trained through <span className="font-semibold text-white">{longDate(trainedThrough)}</span>
            </>
          ) : status === 'offline' ? (
            <span className="inline-flex items-center gap-2">
              <span className="inline-block size-2 rounded-full border-[1.5px] border-on-brand" aria-hidden="true" />
              API offline
            </span>
          ) : status === 'error' ? (
            'Model details unavailable'
          ) : (
            <span className="inline-block h-3 w-44 animate-pulse rounded-sm bg-white/20 align-middle" aria-label="Loading model" />
          )}
          {nSeries !== null && <> · {num(nSeries)} store-item series</>}
          {trainedThrough && <Explain {...GLOSSARY.trainedThrough} tone="onBrand" />}
        </div>
      </div>
    </header>
  )
}
