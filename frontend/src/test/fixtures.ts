// Fixture responses shaped like the DemandBench API's JSON (see backend serving/schemas.py).
import type {
  Forecast,
  ForecastPoint,
  Health,
  History,
  HistoryPoint,
  Importance,
  ModelInfo,
  SeriesBacktest,
  SeriesInfo,
} from '../api/client'

export const TRAIN_END = '2016-05-22'
export const FORECAST_START = '2016-05-23'
export const HISTORY_DAYS = 180
export const HORIZON = 28

/** Index (in a 180-day history) of the one day each fixture series flags as anomalous. */
export const ANOMALY_INDEX = 120

// All figures are made up (round numbers); only the ids follow the real M5 naming.
interface FixtureSeries extends SeriesInfo {
  /** Daily forecast level and list price used to generate the series' data. */
  level: number
  price: number
}

export const SERIES: FixtureSeries[] = [
  {
    item_id: 'FOODS_3_090', store_id: 'CA_1', dept_id: 'FOODS_3', cat_id: 'FOODS', state_id: 'CA',
    total_sales: 100000, sales_last_28d: 1000, on_sale_since: '2011-01-29', volume_tier: 'high',
    level: 40, price: 2,
  },
  {
    item_id: 'FOODS_3_586', store_id: 'TX_3', dept_id: 'FOODS_3', cat_id: 'FOODS', state_id: 'TX',
    total_sales: 200000, sales_last_28d: 2000, on_sale_since: '2011-01-29', volume_tier: 'high',
    level: 60, price: 3,
  },
  {
    item_id: 'HOBBIES_1_008', store_id: 'CA_1', dept_id: 'HOBBIES_1', cat_id: 'HOBBIES', state_id: 'CA',
    total_sales: 50000, sales_last_28d: 500, on_sale_since: '2011-01-29', volume_tier: 'high',
    level: 10, price: 1,
  },
  {
    item_id: 'HOUSEHOLD_1_118', store_id: 'TX_3', dept_id: 'HOUSEHOLD_1', cat_id: 'HOUSEHOLD', state_id: 'TX',
    total_sales: 10000, sales_last_28d: 300, on_sale_since: '2012-01-01', volume_tier: 'medium',
    level: 5, price: 4,
  },
]

export function findSeries(itemId: string, storeId: string): FixtureSeries | undefined {
  return SERIES.find((s) => s.item_id === itemId && s.store_id === storeId)
}

const toIso = (d: Date) => d.toISOString().slice(0, 10)
function dayAfter(iso: string, days: number): string {
  const d = new Date(`${iso}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + days)
  return toIso(d)
}

/** Weekly pattern so values vary day to day but stay deterministic. */
const WEEKLY = [1.0, 0.9, 0.85, 0.95, 1.1, 1.3, 1.25]

export function forecastPoints(level: number, multiplier = 1): ForecastPoint[] {
  return Array.from({ length: HORIZON }, (_, i) => {
    const value = Math.round(level * WEEKLY[i % 7] * multiplier * 10) / 10
    return { date: dayAfter(FORECAST_START, i), forecast: value, lower: Math.round(value * 0.4 * 10) / 10, upper: Math.round(value * 1.6 * 10) / 10 }
  })
}

export function forecastFor(s: FixtureSeries, options: { multiplier?: number; price?: number } = {}): Forecast {
  return {
    item_id: s.item_id,
    store_id: s.store_id,
    dept_id: s.dept_id,
    cat_id: s.cat_id,
    state_id: s.state_id,
    model: 'lightgbm_global',
    trained_through: TRAIN_END,
    horizon_days: HORIZON,
    sell_price: options.price ?? s.price,
    sales_last_28d: s.sales_last_28d,
    interval: {
      lower_quantile: 0.1,
      upper_quantile: 0.9,
      nominal_coverage: 0.8,
      note: 'In backtesting this interval covered about 80% of all days.',
    },
    points: forecastPoints(s.level, options.multiplier ?? 1),
  }
}

export function historyFor(s: FixtureSeries): History {
  const start = dayAfter(TRAIN_END, -(HISTORY_DAYS - 1))
  const points: HistoryPoint[] = Array.from({ length: HISTORY_DAYS }, (_, i) => {
    const anomaly = i === ANOMALY_INDEX
    const sales = anomaly ? Math.round(s.level * 5) : Math.round(s.level * WEEKLY[i % 7])
    return {
      date: dayAfter(start, i),
      sales,
      rolling_mean: i < 28 ? null : s.level,
      rolling_std: i < 28 ? null : s.level * 0.2,
      z_score: i < 28 ? null : anomaly ? 20 : 0.5,
      anomaly,
    }
  })
  return {
    item_id: s.item_id,
    store_id: s.store_id,
    start,
    end: TRAIN_END,
    days: HISTORY_DAYS,
    anomaly_rule: '|sales - mean| > 3 * std over the 28 previous days',
    n_anomalies: 1,
    points,
  }
}

export function backtestFor(s: FixtureSeries): SeriesBacktest {
  return {
    item_id: s.item_id,
    store_id: s.store_id,
    available: true,
    reason: null,
    model: 'lightgbm_global',
    n_folds: 5,
    window_start: '2016-01-04',
    window_end: TRAIN_END,
    actual_units: 7243,
    forecast_units: 5459,
    wape: s.item_id === 'FOODS_3_090' ? 0.432 : 0.194,
    bias: s.item_id === 'FOODS_3_090' ? 0.754 : 1.019,
    overall_wape: 0.755,
    overall_bias: 0.933,
    folds: [],
  }
}

export const HEALTH: Health = {
  status: 'ok',
  model: 'lightgbm_global',
  trained_through: TRAIN_END,
  forecast_start: FORECAST_START,
  forecast_end: '2016-06-19',
  n_series: 30490,
}

export const MODEL: ModelInfo = {
  model: 'lightgbm_global',
  point_model: 'tweedie',
  tweedie_variance_power: 1.5,
  quantiles: [0.1, 0.5, 0.9],
  train_start: '2015-05-24',
  train_end: TRAIN_END,
  train_rows: 11107801,
  horizon_days: HORIZON,
  features: ['roll_mean_28_h28', 'roll_mean_7_h28', 'item_id', 'sell_price'],
  created_at: '2026-11-01T05:14:12+00:00',
}

export const IMPORTANCE: Importance = {
  model: 'tweedie',
  importance_type: 'gain',
  scope: 'global (one model for all series)',
  features: [
    { feature: 'roll_mean_28_h28', gain: 5.7e7, share: 0.573 },
    { feature: 'roll_mean_7_h28', gain: 1.5e7, share: 0.149 },
    { feature: 'item_id', gain: 1.4e7, share: 0.144 },
    { feature: 'roll_std_28_h28', gain: 6.1e6, share: 0.061 },
    { feature: 'dept_id', gain: 1.6e6, share: 0.016 },
    { feature: 'month', gain: 1.2e6, share: 0.012 },
    { feature: 'wday', gain: 9e5, share: 0.009 },
    { feature: 'sell_price', gain: 8e5, share: 0.008 },
    { feature: 'store_id', gain: 7e5, share: 0.007 },
    { feature: 'lag_28', gain: 5e5, share: 0.005 },
  ],
}

export const sum = (points: { forecast: number }[]) => points.reduce((total, p) => total + p.forecast, 0)
