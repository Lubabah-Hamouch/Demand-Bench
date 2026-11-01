// MSW server mocking the DemandBench API at its default address.
import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { WhatIfRequest } from '../api/client'
import {
  backtestFor,
  findSeries,
  forecastFor,
  HEALTH,
  historyFor,
  IMPORTANCE,
  MODEL,
  SERIES,
} from './fixtures'

export const API = 'http://localhost:8020'

export interface LoggedRequest {
  method: string
  path: string
  params: Record<string, string>
  body: unknown
}

/** Every request the mocked API received in the current test (reset after each test). */
export const requestLog: LoggedRequest[] = []

async function log(request: Request): Promise<void> {
  const url = new URL(request.url)
  const body = request.method === 'POST' ? await request.clone().json() : null
  requestLog.push({
    method: request.method,
    path: url.pathname,
    params: Object.fromEntries(url.searchParams),
    body,
  })
}

const notFound = (itemId: string, storeId: string) =>
  HttpResponse.json(
    { detail: `No series for item_id='${itemId}', store_id='${storeId}'. Use GET /series to list available series.` },
    { status: 404 },
  )

export const handlers = [
  http.get(`${API}/health`, async ({ request }) => {
    await log(request)
    return HttpResponse.json(HEALTH)
  }),
  http.get(`${API}/model`, async ({ request }) => {
    await log(request)
    return HttpResponse.json(MODEL)
  }),
  http.get(`${API}/model/importance`, async ({ request }) => {
    await log(request)
    return HttpResponse.json(IMPORTANCE)
  }),
  // Mirrors the real filters: q is a case-insensitive item_id substring.
  http.get(`${API}/series`, async ({ request }) => {
    await log(request)
    const p = new URL(request.url).searchParams
    const q = p.get('q')?.toLowerCase()
    const items = SERIES.filter(
      (s) =>
        (!q || s.item_id.toLowerCase().includes(q)) &&
        (!p.get('store_id') || s.store_id === p.get('store_id')) &&
        (!p.get('state_id') || s.state_id === p.get('state_id')) &&
        (!p.get('volume_tier') || s.volume_tier === p.get('volume_tier')),
    ).map(({ level: _level, price: _price, ...info }) => info)
    const limit = Number(p.get('limit') ?? 100)
    const offset = Number(p.get('offset') ?? 0)
    return HttpResponse.json({ total: items.length, limit, offset, items: items.slice(offset, offset + limit) })
  }),
  http.get(`${API}/forecast/:itemId/:storeId`, async ({ request, params }) => {
    await log(request)
    const s = findSeries(String(params.itemId), String(params.storeId))
    return s ? HttpResponse.json(forecastFor(s)) : notFound(String(params.itemId), String(params.storeId))
  }),
  // A simple stand-in for the model: promo adds 5%, price moves demand inversely.
  http.post(`${API}/forecast/:itemId/:storeId/whatif`, async ({ request, params }) => {
    await log(request)
    const s = findSeries(String(params.itemId), String(params.storeId))
    if (!s) return notFound(String(params.itemId), String(params.storeId))
    const body = (await request.json()) as WhatIfRequest
    const price = body.sell_price ?? s.price
    const multiplier = (body.has_promo ? 1.05 : 1) * (s.price / price)
    return HttpResponse.json({
      ...forecastFor(s, { multiplier, price }),
      scenario: { has_promo: body.has_promo ?? null, sell_price: body.sell_price ?? null },
      note: 'Scenario forecasts reflect associations the model learned across all items.',
    })
  }),
  http.get(`${API}/series/:itemId/:storeId/history`, async ({ request, params }) => {
    await log(request)
    const s = findSeries(String(params.itemId), String(params.storeId))
    return s ? HttpResponse.json(historyFor(s)) : notFound(String(params.itemId), String(params.storeId))
  }),
  http.get(`${API}/series/:itemId/:storeId/backtest`, async ({ request, params }) => {
    await log(request)
    const s = findSeries(String(params.itemId), String(params.storeId))
    return s ? HttpResponse.json(backtestFor(s)) : notFound(String(params.itemId), String(params.storeId))
  }),
]

export const server = setupServer(...handlers)

export const requestsTo = (method: string, pathPattern: RegExp) =>
  requestLog.filter((r) => r.method === method && pathPattern.test(r.path))
