import { BACKTEST } from './content'
import { num } from './format'

/**
 * Plain-language explanations shown by the "?" buttons (components/Explain.tsx). `text`
 * says what the thing is; `read` says how to read it (which direction is better, what a
 * value means). Kept in one place so the wording stays consistent across the page.
 */
export interface Explanation {
  /** Completes the button's accessible name: "About <term>". */
  term: string
  text: string
  read?: string
}

const pct = (ratio: number) => `${num(ratio * 100, 1)}%`
const { full } = BACKTEST

export const GLOSSARY = {
  trainedThrough: {
    term: 'the training date and series count',
    text: 'The model learned from daily sales up to this date and forecasts the four weeks after it. The M5 data ends in 2016, so "next four weeks" means late May to mid-June 2016.',
    read: 'A series is one item’s daily sales at one store.',
  },
  volumeTier: {
    term: 'sales volume tiers',
    text: 'Each series is ranked by units sold up to early January 2016, against the others in its category and state, and split into thirds: high, medium and low.',
    read: 'Slow sellers are harder to forecast, because most of their days have no sales at all.',
  },
  dailyRange: {
    term: 'the likely range',
    text: 'For each day, the range runs from the model’s low estimate to its high estimate (the 10th and 90th percentiles), so actual sales should land inside it on about 8 days in 10.',
    read: `In backtests they did on ${pct(full.coverage)} of days. A wider range means a less predictable day.`,
  },
  totalRange: {
    term: 'the likely range for four weeks',
    text: 'The sum of every day’s low and high estimates (p10 and p90). Adding up each day’s extremes makes it a cautious range: the four-week total should land inside it more often than 8 times in 10.',
    read: 'The headline figure above is the best single estimate.',
  },
  unusualDay: {
    term: 'unusual days',
    text: 'A day whose sales were far outside the normal day-to-day swing: more than three standard deviations away from the average of the 28 days before it.',
    read: 'Holidays, stock-outs and data glitches are common causes.',
  },
  seriesWape: {
    term: 'backtest error for this series',
    text: 'How far off past forecasts were for this item at this store. In five backtests the model forecast a past four-week period using only earlier data; this is WAPE: units missed, divided by units sold.',
    read: 'Lower is better, and 0 would be perfect. Compare it with the all-series figure.',
  },
  seriesBias: {
    term: 'forecast ÷ actual for this series',
    text: 'Units this series was forecast to sell in the backtests, divided by the units it actually sold.',
    read: '100% means forecasts matched sales overall. Below 100% the model forecast too low; above, too high.',
  },
  promotion: {
    term: 'promotion',
    text: 'M5 has no promotion records, so a promotion here means a markdown: a price below the item’s usual price (its median over the previous 90 days).',
    read: '“Promo on” forecasts as if all 28 days were marked down, without changing the price itself.',
  },
  price: {
    term: 'the price change',
    text: 'Sets the item’s price for all 28 days, from 30% below to 30% above its list price (its latest price in the data).',
    read: 'A price below the item’s usual level also counts as a promotion.',
  },
  scenarioResult: {
    term: 'the scenario result',
    text: 'The change in total forecast units over the next four weeks: with this scenario, compared with no scenario.',
    read: 'The direction is built in (a lower price or a promotion never lowers the forecast). The size is learned across all items, so treat it as a rough guide.',
  },
  importance: {
    term: 'the driver percentages',
    text: 'Each input’s share of how much it improved the model’s fit during training (LightGBM “gain”). Inputs that carry similar information, like the different sales lags, split the credit.',
    read: 'A bigger share means the model relied on it more; it doesn’t say whether it pushes sales up or down. Grey names are the model’s own.',
  },
  wape: {
    term: 'WAPE',
    text: 'Weighted absolute percentage error: every day’s miss in units, too high or too low, added up and divided by the units sold. 0.79 means the misses add up to 79% of the units sold.',
    read: 'Lower is better. Daily sales of single items are noisy, so values this high are normal here: compare the models rather than reading one number alone.',
  },
  sample: {
    term: 'the 200-series sample',
    text: 'Prophet fits a separate model for every series, too slow to run on all 30,490, so the three models are compared on the same 200 series, chosen to cover every category, state and sales volume in proportion.',
  },
  bias: {
    term: 'forecast ÷ actual',
    text: 'Units forecast across all series and backtests, divided by the units actually sold.',
    read: `100% would mean no lean either way. ${pct(full.bias)} means forecasts ran about ${num(Math.abs(1 - full.bias) * 100)}% ${full.bias < 1 ? 'low' : 'high'} overall.`,
  },
  coverage: {
    term: 'inside the 80% range',
    text: 'How often actual daily sales landed inside the likely range. It is built to catch 8 days in 10, so close to 80% means it is honest about its uncertainty.',
    read: `Days with no sales are easy to catch (the range often starts at zero), so on days with at least one sale it is lower: ${pct(full.coverageWithSales)}.`,
  },
  monotone: {
    term: 'how the model treats price and promotions',
    text: 'The model is built so that a price cut or a promotion can never lower its forecast, and a price rise can never raise it (monotone constraints).',
    read: `This keeps what-if answers sensible at a small cost in accuracy: WAPE ${num(full.wape, 3)}, against ${num(full.unconstrainedWape, 3)} without the constraints.`,
  },
} satisfies Record<string, Explanation>
