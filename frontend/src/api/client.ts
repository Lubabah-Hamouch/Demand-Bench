// Typed client for the DemandBench API (backend/src/demandbench/serving). The browser
// calls VITE_API_BASE_URL directly; the API must allow this app's origin (CORS).
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8020').replace(/\/+$/, '')

export type VolumeTier = 'low' | 'medium' | 'high' | 'new'

export interface Health {
  status: string
  model: string
  trained_through: string
  forecast_start: string
  forecast_end: string
  n_series: number
}

export interface ModelInfo {
  model: string
  point_model: string
  tweedie_variance_power: number
  quantiles: number[]
  train_start: string
  train_end: string
  train_rows: number
  horizon_days: number
  features: string[]
  created_at: string
}

export interface SeriesInfo {
  item_id: string
  store_id: string
  dept_id: string
  cat_id: string
  state_id: string
  total_sales: number
  sales_last_28d: number
  on_sale_since: string | null
  volume_tier: VolumeTier
}

export interface SeriesPage {
  total: number
  limit: number
  offset: number
  items: SeriesInfo[]
}

export interface SeriesQuery {
  q?: string
  store_id?: string
  state_id?: string
  volume_tier?: VolumeTier
  limit?: number
  offset?: number
}

export interface ForecastPoint {
  date: string
  forecast: number
  lower: number
  upper: number
}

export interface Forecast {
  item_id: string
  store_id: string
  dept_id: string
  cat_id: string
  state_id: string
  model: string
  trained_through: string
  horizon_days: number
  sell_price: number | null
  sales_last_28d: number
  interval: { lower_quantile: number; upper_quantile: number; nominal_coverage: number; note: string }
  points: ForecastPoint[]
}

export interface WhatIfRequest {
  has_promo?: boolean
  sell_price?: number
}

export interface WhatIfForecast extends Forecast {
  scenario: { has_promo: boolean | null; sell_price: number | null }
  note: string
}

export interface FeatureImportance {
  feature: string
  gain: number
  share: number
}

export interface Importance {
  model: string
  importance_type: string
  scope: string
  features: FeatureImportance[]
}

export interface HistoryPoint {
  date: string
  sales: number
  rolling_mean: number | null
  rolling_std: number | null
  z_score: number | null
  anomaly: boolean
}

export interface History {
  item_id: string
  store_id: string
  start: string
  end: string
  days: number
  anomaly_rule: string
  n_anomalies: number
  points: HistoryPoint[]
}

export interface FoldBacktest {
  fold: number
  test_start: string
  test_end: string
  actual_units: number
  forecast_units: number
  wape: number | null
  bias: number | null
}

/** How the model did on one series in the saved backtest. */
export interface SeriesBacktest {
  item_id: string
  store_id: string
  /** False when the backtest has no results for this series. */
  available: boolean
  /** Why a metric is unavailable or undefined, if it is. */
  reason: string | null
  model: string
  n_folds: number
  window_start: string | null
  window_end: string | null
  actual_units: number | null
  forecast_units: number | null
  wape: number | null
  bias: number | null
  overall_wape: number | null
  overall_bias: number | null
  folds: FoldBacktest[]
}

/** A non-2xx response; `status` 0 means the API could not be reached at all. */
export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = 'ApiError'
    this.status = status
  }
}

/** True when the request never got an answer: the API is down or blocks this origin. */
export const isOffline = (error: Error | null | undefined) => error instanceof ApiError && error.status === 0

function detailOf(body: unknown): string | null {
  if (body && typeof body === 'object' && 'detail' in body) {
    const { detail } = body as { detail: unknown }
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) {
      return detail.map((d) => (d && typeof d === 'object' && 'msg' in d ? String(d.msg) : String(d))).join('; ')
    }
  }
  return null
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response
  try {
    response = await fetch(API_BASE_URL + path, {
      ...init,
      headers: { Accept: 'application/json', ...(init.body ? { 'Content-Type': 'application/json' } : {}) },
    })
  } catch (err) {
    // Checked by name: the error may come from another realm's DOMException.
    if (err instanceof Error && err.name === 'AbortError') throw err
    // fetch rejects both when nothing is listening and when CORS blocks the response.
    throw new ApiError(0, `Cannot reach the DemandBench API at ${API_BASE_URL}.`)
  }
  const text = await response.text()
  let body: unknown = null
  try {
    body = text ? JSON.parse(text) : null
  } catch {
    // Not JSON (e.g. a proxy error page); fall back to the status code below.
  }
  if (!response.ok) {
    throw new ApiError(response.status, detailOf(body) ?? `Request failed with status ${response.status}.`)
  }
  return body as T
}

function query(params: object): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== '') search.set(key, String(value))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}

const seriesPath = (itemId: string, storeId: string) =>
  `${encodeURIComponent(itemId)}/${encodeURIComponent(storeId)}`

export const api = {
  health: (signal?: AbortSignal) => request<Health>('/health', { signal }),
  model: (signal?: AbortSignal) => request<ModelInfo>('/model', { signal }),
  importance: (signal?: AbortSignal) => request<Importance>('/model/importance', { signal }),
  series: (params: SeriesQuery, signal?: AbortSignal) =>
    request<SeriesPage>(`/series${query(params)}`, { signal }),
  forecast: (itemId: string, storeId: string, signal?: AbortSignal) =>
    request<Forecast>(`/forecast/${seriesPath(itemId, storeId)}`, { signal }),
  whatIf: (itemId: string, storeId: string, body: WhatIfRequest, signal?: AbortSignal) =>
    request<WhatIfForecast>(`/forecast/${seriesPath(itemId, storeId)}/whatif`, {
      method: 'POST',
      body: JSON.stringify(body),
      signal,
    }),
  history: (itemId: string, storeId: string, days: number, signal?: AbortSignal) =>
    request<History>(`/series/${seriesPath(itemId, storeId)}/history${query({ days })}`, { signal }),
  backtest: (itemId: string, storeId: string, signal?: AbortSignal) =>
    request<SeriesBacktest>(`/series/${seriesPath(itemId, storeId)}/backtest`, { signal }),
}
