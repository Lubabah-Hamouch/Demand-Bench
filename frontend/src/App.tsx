import { useEffect, useState } from 'react'
import { api, ApiError, isOffline, type SeriesInfo, type WhatIfRequest } from './api/client'
import { ChartLegend, ForecastChart } from './components/ForecastChart'
import { ForecastTable } from './components/ForecastTable'
import { Drivers } from './components/Drivers'
import { Explain } from './components/Explain'
import { Header } from './components/Header'
import { ModelQuality } from './components/ModelQuality'
import { ScenarioBand } from './components/ScenarioBand'
import { Sidebar } from './components/Sidebar'
import { ChartSkeleton, ErrorNote, SectionHeading, TableSkeleton } from './components/Status'
import { Summary } from './components/Summary'
import { describeSeries, shortDate, units } from './lib/format'
import { GLOSSARY } from './lib/glossary'
import { useAsync, useDebounced } from './lib/hooks'

// A high-volume series that is always in the bundle, so the first screen has data.
const DEFAULT_SERIES = { itemId: 'FOODS_3_090', storeId: 'CA_1' }
const HISTORY_DAYS = 180
const SLIDER_DEBOUNCE_MS = 300

interface Scenario {
  promo: boolean
  pct: number
}
const NO_SCENARIO: Scenario = { promo: false, pct: 0 }

export default function App() {
  const [selected, setSelected] = useState(DEFAULT_SERIES)
  const [scenario, setScenario] = useState<Scenario>(NO_SCENARIO)
  const debouncedPct = useDebounced(scenario.pct, SLIDER_DEBOUNCE_MS)
  const { itemId, storeId } = selected
  const seriesKey = `${itemId}/${storeId}`

  const model = useAsync('model', (signal) => api.model(signal))
  const health = useAsync('health', (signal) => api.health(signal))
  const info = useAsync(`info/${seriesKey}`, (signal) =>
    api.series({ q: itemId, store_id: storeId, limit: 5 }, signal).then(
      (page) => page.items.find((s) => s.item_id === itemId && s.store_id === storeId) ?? null,
    ),
  )
  const baseline = useAsync(`forecast/${seriesKey}`, (signal) => api.forecast(itemId, storeId, signal))
  const history = useAsync(`history/${seriesKey}`, (signal) => api.history(itemId, storeId, HISTORY_DAYS, signal))
  const backtest = useAsync(`backtest/${seriesKey}`, (signal) => api.backtest(itemId, storeId, signal))

  // The scenario request, once the baseline (and so today's price) is known. The promo
  // toggle applies at once; the price slider is debounced while it is being dragged.
  const basePrice = baseline.data?.item_id === itemId && baseline.data.store_id === storeId ? baseline.data.sell_price : null
  const request: WhatIfRequest | null = (() => {
    if (!scenario.promo && debouncedPct === 0) return null
    const body: WhatIfRequest = {}
    if (scenario.promo) body.has_promo = true
    if (debouncedPct !== 0) {
      if (basePrice === null) return null
      body.sell_price = Math.round(basePrice * (1 + debouncedPct / 100) * 100) / 100
    }
    return body
  })()
  const whatIfKey = request ? `whatif/${seriesKey}/${JSON.stringify(request)}` : null
  const whatIf = useAsync(whatIfKey, (signal) => api.whatIf(itemId, storeId, request!, signal))

  const scenarioActive = scenario.promo || scenario.pct !== 0
  const scenarioData = scenarioActive && whatIf.data?.item_id === itemId && whatIf.data.store_id === storeId ? whatIf.data : null
  const baseData = baseline.data?.item_id === itemId && baseline.data.store_id === storeId ? baseline.data : null
  const historyData = history.data?.item_id === itemId && history.data.store_id === storeId ? history.data : null
  const backtestData =
    backtest.status === 'error'
      ? ('error' as const)
      : backtest.data?.item_id === itemId && backtest.data.store_id === storeId
        ? backtest.data
        : null
  const shown = scenarioData ?? baseData
  const sum = (points: { forecast: number }[]) => points.reduce((s, p) => s + p.forecast, 0)
  const pending = scenarioActive && (scenario.pct !== debouncedPct || whatIf.status === 'loading' || scenarioData === null)

  const select = (s: SeriesInfo) => {
    setSelected({ itemId: s.item_id, storeId: s.store_id })
    setScenario(NO_SCENARIO)
  }

  const seriesError = baseline.status === 'error' ? baseline.error : history.status === 'error' ? history.error : null
  // When the API cannot be reached at all, one explanation replaces every per-section error.
  const offline = [health, model, baseline, history].some((r) => r.status === 'error' && isOffline(r.error))

  useEffect(() => {
    const name = describeSeries(itemId, storeId)
    document.title = `${name.itemLabel}, ${name.place} · DemandBench`
  }, [itemId, storeId])

  return (
    <div className="flex min-h-screen flex-col bg-white text-ink">
      <Header
        trainedThrough={model.data?.train_end ?? null}
        nSeries={health.data?.n_series ?? null}
        status={offline ? 'offline' : model.status === 'error' ? 'error' : 'ok'}
      />
      <div className="flex flex-1 flex-col lg:flex-row lg:items-stretch">
        <Sidebar selected={selected} onSelect={select} nSeries={health.data?.n_series ?? null} />

        <main id="forecast" className="min-w-0 flex-1 bg-white">
          <Summary
            itemId={itemId}
            storeId={storeId}
            info={info.data}
            baseline={baseData}
            shown={shown}
            history={historyData}
            scenarioActive={scenarioActive && scenarioData !== null}
            offline={offline}
            backtest={backtestData}
          />

          {offline ? (
            <div className="px-10 pb-12">
              <ErrorNote error={new ApiError(0, 'offline')} onRetry={() => window.location.reload()} />
            </div>
          ) : seriesError ? (
            <div className="px-10 pb-8">
              <ErrorNote
                error={seriesError}
                onRetry={() => {
                  baseline.reload()
                  history.reload()
                }}
              />
            </div>
          ) : (
            <>
              <ScenarioBand
                promo={scenario.promo}
                pct={scenario.pct}
                price={basePrice}
                baseTotal={baseData ? sum(baseData.points) : null}
                scenarioTotal={scenarioData ? sum(scenarioData.points) : null}
                updating={pending}
                error={scenarioActive && whatIf.status === 'error' ? whatIf.error.message : null}
                onPromo={(promo) => setScenario((s) => ({ ...s, promo }))}
                onPct={(pct) => setScenario((s) => ({ ...s, pct }))}
                onReset={() => setScenario(NO_SCENARIO)}
              />

              <section aria-label="Sales and forecast" className="px-10 pb-2.5 pt-[30px]">
                <SectionHeading
                  index="01"
                  title="Daily sales and forecast"
                  aside={<ChartLegend scenarioActive={scenarioData !== null} />}
                />
                <div className={`mt-5 transition-opacity ${pending ? 'opacity-70' : ''}`}>
                  {baseData && historyData ? (
                    <ForecastChart history={historyData} baseline={baseData} scenario={scenarioData} />
                  ) : (
                    <ChartSkeleton />
                  )}
                </div>
                {historyData && (
                  <div className="mt-3.5 flex flex-wrap items-baseline gap-x-3.5 gap-y-2 text-[13.5px]">
                    <span className="kicker text-coral-deep">Unusual days</span>
                    {historyData.points.filter((p) => p.anomaly).length === 0 && (
                      <span className="text-muted">None in the last {HISTORY_DAYS} days</span>
                    )}
                    {historyData.points
                      .filter((p) => p.anomaly)
                      .reverse()
                      .map((p) => (
                        <span key={p.date} className="tabular">
                          <span className="font-semibold">{shortDate(p.date)}</span>{' '}
                          <span className="text-muted">
                            {units(p.sales)} sold vs ~{p.rolling_mean === null ? '—' : units(p.rolling_mean)} usual
                          </span>
                        </span>
                      ))}
                  </div>
                )}
              </section>

              <section aria-label="Next 28 days" className="px-10 pb-2.5 pt-[30px]">
                <SectionHeading
                  index="02"
                  title="Day by day, next four weeks"
                  aside={
                    <span className="text-[13px] text-muted">
                      {scenarioData
                        ? 'Units per day with scenario · small figures: change vs. no scenario'
                        : (
                          <>
                            Units per day · small figures: likely range
                            <Explain {...GLOSSARY.dailyRange} />
                          </>
                        )}
                    </span>
                  }
                />
                {shown && baseData ? (
                  <ForecastTable shown={shown} baseline={baseData} scenarioActive={scenarioData !== null} />
                ) : (
                  <TableSkeleton />
                )}
              </section>
            </>
          )}

          {!offline && (
            <div className="flex flex-wrap gap-x-12 gap-y-10 px-10 pb-12 pt-[30px]">
              <Drivers />
              <ModelQuality />
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
