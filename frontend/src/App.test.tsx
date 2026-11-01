import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { num } from './lib/format'
import { findSeries, forecastFor, sum } from './test/fixtures'
import { API, requestsTo, server } from './test/server'
import { colors } from './theme'

// vi.mock is hoisted above the imports, so the helper is imported inside the factory.
vi.mock('recharts', async (importOriginal) => {
  const { withFixedSizeContainer } = await import('./test/recharts')
  return withFixedSizeContainer(await importOriginal<object>())
})

const FOODS_090 = findSeries('FOODS_3_090', 'CA_1')!
const FOODS_586 = findSeries('FOODS_3_586', 'TX_3')!
const summary = () => screen.getByRole('region', { name: 'Summary' })
const weekTotals = () =>
  within(screen.getByRole('region', { name: 'Next 28 days' }))
    .getAllByRole('row')
    .slice(1)
    .map((row) => within(row).getAllByRole('cell').at(-1)!.textContent)

/** Week totals as the table formats them, from a forecast's points. */
const expectedWeekTotals = (points: { forecast: number }[]) =>
  [0, 1, 2, 3].map((w) => num(sum(points.slice(w * 7, w * 7 + 7))))

async function renderLoaded() {
  render(<App />)
  await screen.findByText(/Expect about/)
  await waitFor(() => expect(screen.getByRole('region', { name: 'Next 28 days' }).querySelectorAll('tbody tr')).toHaveLength(4))
}

afterEach(() => {
  vi.useRealTimers()
})

describe('App: switching series (integration)', () => {
  it('updates the headline, chart and table to the newly selected series', async () => {
    const user = userEvent.setup()
    await renderLoaded()

    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Item 090')
    expect(summary()).toHaveTextContent('California, Store 1')
    expect(summary()).toHaveTextContent('M5 id FOODS_3_090 · CA_1')
    expect(summary()).toHaveTextContent(`Expect about ${num(sum(forecastFor(FOODS_090).points))} units`)
    expect(weekTotals()).toEqual(expectedWeekTotals(forecastFor(FOODS_090).points))
    expect(document.title).toBe('Item 090, California, Store 1 · DemandBench')

    const sidebar = screen.getByRole('complementary', { name: 'Choose a series' })
    const row = within(sidebar)
      .getAllByRole('button')
      .find((b) => b.textContent?.includes('FOODS_3_586 · TX_3'))!
    await user.click(row)

    await waitFor(() => expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Item 586'))
    expect(summary()).toHaveTextContent('Texas, Store 3')
    expect(summary()).toHaveTextContent('M5 id FOODS_3_586 · TX_3')
    await waitFor(() =>
      expect(summary()).toHaveTextContent(`Expect about ${num(sum(forecastFor(FOODS_586).points))} units`),
    )
    await waitFor(() => expect(weekTotals()).toEqual(expectedWeekTotals(forecastFor(FOODS_586).points)))
    expect(row).toHaveAttribute('aria-current', 'true')
    expect(document.title).toBe('Item 586, Texas, Store 3 · DemandBench')

    // Every per-series endpoint was fetched for the new series.
    for (const path of [
      '/forecast/FOODS_3_586/TX_3',
      '/series/FOODS_3_586/TX_3/history',
      '/series/FOODS_3_586/TX_3/backtest',
    ]) {
      expect(requestsTo('GET', new RegExp(`^${path}$`)).length).toBeGreaterThan(0)
    }
    // The chart shows the new series' history, including its anomaly ring.
    const chart = screen.getByRole('region', { name: 'Sales and forecast' })
    expect(chart.querySelectorAll(`circle[stroke="${colors.coral}"][fill="#FFFFFF"]`)).toHaveLength(1)
    expect(within(chart).getByText(/sold vs ~/)).toBeInTheDocument()
  })

  it('shows the per-series backtest numbers in the details strip', async () => {
    const user = userEvent.setup()
    await renderLoaded()
    await user.click(screen.getByRole('button', { name: 'Show the numbers behind this' }))
    const details = await screen.findByText('Backtest error, this series')
    expect(details.parentElement).toHaveTextContent('0.432')
    expect(details.parentElement).toHaveTextContent('all series 0.755')
  })
})

describe('App: scenario controls', () => {
  it('toggling promo calls what-if with has_promo and shows the result', async () => {
    const user = userEvent.setup()
    await renderLoaded()
    await user.click(screen.getByRole('button', { name: 'No promo' }))

    await waitFor(() => expect(requestsTo('POST', /\/whatif$/)).toHaveLength(1))
    expect(requestsTo('POST', /\/whatif$/)[0]).toMatchObject({
      path: '/forecast/FOODS_3_090/CA_1/whatif',
      body: { has_promo: true },
    })
    const band = screen.getByRole('region', { name: 'Scenario' })
    await waitFor(() => expect(band).toHaveTextContent('+5.0%'))
    expect(screen.getByRole('button', { name: 'Promo on' })).toHaveAttribute('aria-pressed', 'true')
    expect(summary()).toHaveTextContent('With this scenario, expect about')
  })

  it('debounces the price slider: one request for the final value, after the pause', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true })
    await renderLoaded()
    const slider = screen.getByLabelText('Price')

    // Drag from 0% to -20% in steps, faster than the debounce.
    for (const value of ['-5', '-10', '-15', '-20']) {
      fireEvent.change(slider, { target: { value } })
      await act(() => vi.advanceTimersByTimeAsync(100))
    }
    expect(requestsTo('POST', /\/whatif$/)).toHaveLength(0)

    await act(() => vi.advanceTimersByTimeAsync(299))
    await waitFor(() => expect(requestsTo('POST', /\/whatif$/)).toHaveLength(1))
    // 20% below the API's $2.00 list price, rounded to cents.
    expect(requestsTo('POST', /\/whatif$/)[0].body).toEqual({ sell_price: 1.6 })
    await waitFor(() => expect(screen.getByRole('region', { name: 'Scenario' })).toHaveTextContent('+25.0%'))
  })

  it('sends promo and price together, and Reset returns to the baseline', async () => {
    const user = userEvent.setup()
    await renderLoaded()
    await user.click(screen.getByRole('button', { name: 'No promo' }))
    fireEvent.change(screen.getByLabelText('Price'), { target: { value: '10' } })
    await waitFor(() =>
      expect(requestsTo('POST', /\/whatif$/).map((r) => r.body)).toContainEqual({ has_promo: true, sell_price: 2.2 }),
    )

    await user.click(screen.getByRole('button', { name: 'Reset' }))
    expect(screen.getByRole('button', { name: 'No promo' })).toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Scenario' })).toHaveTextContent('±0%')
    expect(summary()).toHaveTextContent(/^.*Expect about/)
  })
})

describe('App: loading and error states', () => {
  it('shows layout-shaped skeletons while the forecast is loading', async () => {
    server.use(
      http.get(`${API}/forecast/:itemId/:storeId`, async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    render(<App />)
    expect(await screen.findByRole('status', { name: 'Loading sales history and forecast' })).toBeInTheDocument()
    expect(screen.getByRole('status', { name: 'Loading forecast' })).toBeInTheDocument()
    expect(screen.queryByRole('alert')).toBeNull()
    // The headline comes from the ids alone, so it is there before any data.
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Item 090')
  })

  it('shows one offline explanation, not an error per section, when the API is unreachable', async () => {
    server.use(http.all(`${API}/*`, () => HttpResponse.error()))
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('The forecasting API is offline')
    expect(alert).toHaveTextContent('http://localhost:8020')
    expect(alert).toHaveTextContent('DEMANDBENCH_CORS_ORIGINS')
    expect(screen.getByRole('button', { name: 'Try again' })).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('banner')).toHaveTextContent('API offline'))
    expect(screen.getAllByRole('alert')).toHaveLength(1)
    expect(screen.getByText('Series will appear here once the API is reachable.')).toBeInTheDocument()
    expect(screen.queryByText(/Expect about/)).toBeNull()
  })

  it('explains a series the API does not know, with the API message', async () => {
    server.use(
      http.get(`${API}/forecast/:itemId/:storeId`, () =>
        HttpResponse.json({ detail: "No series for item_id='FOODS_3_090', store_id='CA_1'." }, { status: 404 }),
      ),
    )
    render(<App />)
    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Series not found')
    expect(alert).toHaveTextContent("No series for item_id='FOODS_3_090'")
  })

  it('reports a failed what-if inside the scenario band and keeps the baseline', async () => {
    server.use(
      http.post(`${API}/forecast/:itemId/:storeId/whatif`, () =>
        HttpResponse.json({ detail: 'Input should be greater than 0' }, { status: 422 }),
      ),
    )
    const user = userEvent.setup()
    await renderLoaded()
    await user.click(screen.getByRole('button', { name: 'No promo' }))
    const band = screen.getByRole('region', { name: 'Scenario' })
    await waitFor(() => expect(band).toHaveTextContent("Couldn't re-score: Input should be greater than 0"))
    expect(weekTotals()).toEqual(expectedWeekTotals(forecastFor(FOODS_090).points))
  })
})
