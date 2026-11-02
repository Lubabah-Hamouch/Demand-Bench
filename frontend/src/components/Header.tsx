import type { Ref } from 'react'
import { longDate, num } from '../lib/format'
import { GLOSSARY } from '../lib/glossary'
import { Explain } from './Explain'

interface Props {
  trainedThrough: string | null
  nSeries: number | null
  status: 'ok' | 'offline' | 'error'
  /** Narrow screens: the button that opens the series drawer. */
  menu?: { open: boolean; onToggle: () => void }
  menuRef?: Ref<HTMLButtonElement>
}

export function Header({ trainedThrough, nSeries, status, menu, menuRef }: Props) {
  return (
    <header className="bg-brand text-white">
      <div className="flex flex-wrap items-center gap-x-8 gap-y-1 px-4 py-2.5 sm:gap-y-2.5 sm:px-7 sm:py-3.5">
        {menu ? (
          <div className="flex items-center gap-2.5">
            <button
              ref={menuRef}
              type="button"
              onClick={menu.onToggle}
              aria-label="Choose a series"
              aria-expanded={menu.open}
              aria-controls="series-drawer"
              className="-ml-2 inline-flex size-11 flex-none items-center justify-center rounded-md text-white hover:bg-white/10"
            >
              <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
                <path d="M3 6 H19 M3 11 H19 M3 16 H19" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />
              </svg>
            </button>
            <Wordmark />
          </div>
        ) : (
          <Wordmark />
        )}
        <nav aria-label="Primary" className="-mx-3 flex flex-wrap gap-1 sm:mx-0">
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
        <div className="tabular w-full pb-1 text-[13px] text-on-brand sm:ml-auto sm:w-auto sm:pb-0">
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
          {menu ? (
            // Narrower screens, where this line can wrap: the "?" stays with the last word.
            <>
              {nSeries !== null && <> · {num(nSeries)} store-item </>}
              <span className="whitespace-nowrap">
                {nSeries !== null && 'series'}
                {trainedThrough && <Explain {...GLOSSARY.trainedThrough} tone="onBrand" />}
              </span>
            </>
          ) : (
            <>
              {nSeries !== null && <> · {num(nSeries)} store-item series</>}
              {trainedThrough && <Explain {...GLOSSARY.trainedThrough} tone="onBrand" />}
            </>
          )}
        </div>
      </div>
    </header>
  )
}

function Wordmark() {
  return (
    <div className="flex items-baseline gap-2.5">
      <span className="font-display text-[24px] font-bold uppercase tracking-[0.01em] sm:text-[30px]">DemandBench</span>
      <span className="inline-block size-[9px] rounded-full bg-coral" aria-hidden="true" />
    </div>
  )
}
