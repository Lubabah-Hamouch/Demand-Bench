import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { API, requestLog, server } from '../test/server'
import { HORIZON, SERIES } from '../test/fixtures'
import { api, ApiError, isOffline } from './client'

const last = () => requestLog[requestLog.length - 1]

describe('api client: requests and parsing', () => {
  it('lists series with the given filters as query parameters', async () => {
    const page = await api.series({ q: 'foods_3', state_id: 'TX', volume_tier: 'high', limit: 25 })
    expect(last()).toMatchObject({
      method: 'GET',
      path: '/series',
      params: { q: 'foods_3', state_id: 'TX', volume_tier: 'high', limit: '25' },
    })
    expect(page.total).toBe(1)
    expect(page.items[0]).toMatchObject({ item_id: 'FOODS_3_586', store_id: 'TX_3', sales_last_28d: 2000 })
  })

  it('omits empty filters', async () => {
    await api.series({ q: '', store_id: undefined, limit: 5 })
    expect(last().params).toEqual({ limit: '5' })
  })

  it('fetches a forecast by item and store', async () => {
    const forecast = await api.forecast('FOODS_3_090', 'CA_1')
    expect(last()).toMatchObject({ method: 'GET', path: '/forecast/FOODS_3_090/CA_1' })
    expect(forecast.points).toHaveLength(HORIZON)
    expect(forecast.sell_price).toBe(2)
    expect(forecast.points[0]).toEqual({ date: '2016-05-23', forecast: 40, lower: 16, upper: 64 })
  })

  it('posts a what-if scenario as JSON', async () => {
    const result = await api.whatIf('FOODS_3_090', 'CA_1', { has_promo: true, sell_price: 1.6 })
    expect(last()).toMatchObject({
      method: 'POST',
      path: '/forecast/FOODS_3_090/CA_1/whatif',
      body: { has_promo: true, sell_price: 1.6 },
    })
    expect(result.scenario).toEqual({ has_promo: true, sell_price: 1.6 })
    expect(result.sell_price).toBe(1.6)
    expect(result.points).toHaveLength(HORIZON)
  })

  it('sends the JSON content type only for requests with a body', async () => {
    const contentTypes: (string | null)[] = []
    server.events.on('request:start', ({ request }) => {
      contentTypes.push(request.headers.get('content-type'))
    })
    await api.forecast('FOODS_3_090', 'CA_1')
    await api.whatIf('FOODS_3_090', 'CA_1', { has_promo: true })
    server.events.removeAllListeners()
    expect(contentTypes).toEqual([null, 'application/json'])
  })

  it('fetches history for the requested number of days', async () => {
    const history = await api.history('FOODS_3_586', 'TX_3', 180)
    expect(last()).toMatchObject({ path: '/series/FOODS_3_586/TX_3/history', params: { days: '180' } })
    expect(history.points).toHaveLength(180)
    expect(history.points.filter((p) => p.anomaly)).toHaveLength(1)
  })

  it('fetches feature importance', async () => {
    const importance = await api.importance()
    expect(last().path).toBe('/model/importance')
    expect(importance.features[0]).toEqual({ feature: 'roll_mean_28_h28', gain: 5.7e7, share: 0.573 })
  })

  it('fetches per-series backtest results', async () => {
    const backtest = await api.backtest('FOODS_3_090', 'CA_1')
    expect(last().path).toBe('/series/FOODS_3_090/CA_1/backtest')
    expect(backtest).toMatchObject({ available: true, wape: 0.432, bias: 0.754, overall_wape: 0.755 })
  })

  it('encodes ids in the path', async () => {
    server.use(http.get(`${API}/forecast/:itemId/:storeId`, ({ params }) => HttpResponse.json({ params })))
    const body = (await api.forecast('A B/C', 'S 1')) as unknown as { params: Record<string, string> }
    expect(body.params).toEqual({ itemId: 'A B/C', storeId: 'S 1' })
  })
})

describe('api client: errors', () => {
  it('turns a 404 into an ApiError carrying the status and the API detail', async () => {
    const error = await api.forecast('NOT_AN_ITEM', 'CA_1').catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect(error).toMatchObject({ status: 404 })
    expect((error as ApiError).message).toContain("item_id='NOT_AN_ITEM'")
    expect(isOffline(error as ApiError)).toBe(false)
  })

  it('joins validation error messages from a 422', async () => {
    server.use(
      http.post(`${API}/forecast/:itemId/:storeId/whatif`, () =>
        HttpResponse.json(
          { detail: [{ msg: 'Value error, provide at least one override' }, { msg: 'Input should be greater than 0' }] },
          { status: 422 },
        ),
      ),
    )
    const error = (await api.whatIf('FOODS_3_090', 'CA_1', {}).catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(422)
    expect(error.message).toBe('Value error, provide at least one override; Input should be greater than 0')
  })

  it('reports a network failure as offline (status 0) with the API address', async () => {
    server.use(http.get(`${API}/health`, () => HttpResponse.error()))
    const error = (await api.health().catch((e: unknown) => e)) as ApiError
    expect(error).toBeInstanceOf(ApiError)
    expect(error.status).toBe(0)
    expect(isOffline(error)).toBe(true)
    expect(error.message).toContain(API)
  })

  it('falls back to the status code when an error body is not JSON', async () => {
    server.use(http.get(`${API}/model`, () => new HttpResponse('Bad gateway', { status: 502 })))
    const error = (await api.model().catch((e: unknown) => e)) as ApiError
    expect(error.status).toBe(502)
    expect(error.message).toBe('Request failed with status 502.')
  })

  it('lets an aborted request reject as an AbortError, not an ApiError', async () => {
    const controller = new AbortController()
    const pending = api.forecast(SERIES[0].item_id, SERIES[0].store_id, controller.signal)
    controller.abort()
    const error = await pending.catch((e: unknown) => e)
    expect(error).not.toBeInstanceOf(ApiError)
    expect((error as Error).name).toBe('AbortError')
  })
})
