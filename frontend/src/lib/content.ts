/** Plain-language labels for the model's raw feature names. */
export const FEATURE_LABELS: Record<string, string> = {
  roll_mean_28_h28: 'Average daily sales over four weeks',
  roll_mean_7_h28: 'Average daily sales over one week',
  roll_std_28_h28: 'How much sales swing, four weeks',
  roll_std_7_h28: 'How much sales swing, one week',
  lag_28: 'Sales on the same weekday, four weeks earlier',
  lag_35: 'Sales five weeks earlier',
  lag_42: 'Sales six weeks earlier',
  lag_56: 'Sales eight weeks earlier',
  item_id: 'Which item it is',
  dept_id: 'Department',
  cat_id: 'Category',
  store_id: 'Which store',
  state_id: 'Which state',
  wday: 'Day of week',
  month: 'Month of year',
  is_event: 'Holiday or event day',
  snap: 'SNAP benefit day',
  has_promo: 'Promotion',
  sell_price: 'Price',
  sell_price_pct_change_28: 'Price change vs. four weeks earlier',
}

/**
 * Backtest results, STATIC: copied from the last documented 5-fold backtest run
 * (data/processed/backtest/, monotone-constrained LightGBM, see README). There is no
 * backtest endpoint yet; update these by hand after re-running
 * `python -m demandbench.backtest.compare`.
 */
export const BACKTEST = {
  window: 'January to May 2016',
  // WAPE of each model on the same 200-series stratified sample (Prophet only ran there).
  sample: [
    { name: 'DemandBench model', tech: 'lightgbm tweedie', wape: 0.794, primary: true },
    { name: 'Prophet', tech: 'per-series', wape: 0.825, primary: false },
    { name: 'Same weekday, four weeks earlier', tech: 'seasonal naive', wape: 0.976, primary: false },
  ],
  // LightGBM on all 30,490 series.
  full: { wape: 0.755, naiveWape: 0.916, bias: 0.933, coverage: 0.805, coverageWithSales: 0.739 },
} as const
