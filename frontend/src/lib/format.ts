import type { VolumeTier } from '../api/client'

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
const MONTHS_LONG = [
  'January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December',
]
export const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
export const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

const STATES: Record<string, string> = { CA: 'California', TX: 'Texas', WI: 'Wisconsin' }
export const STATE_CODES: Record<string, string> = { california: 'CA', texas: 'TX', wisconsin: 'WI' }

export const TIER_LABEL: Record<VolumeTier, string> = {
  high: 'high-volume tier',
  medium: 'medium-volume tier',
  low: 'low-volume tier',
  new: 'recently launched',
}

/** ISO date (YYYY-MM-DD) parsed as a UTC calendar day. */
export function parseDay(iso: string): Date {
  const [y, m, d] = iso.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d))
}

export const shortDate = (iso: string) => {
  const d = parseDay(iso)
  return `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`
}
export const longDate = (iso: string) => {
  const d = parseDay(iso)
  return `${MONTHS_LONG[d.getUTCMonth()]} ${d.getUTCDate()}, ${d.getUTCFullYear()}`
}
export const monthName = (iso: string) => MONTHS[parseDay(iso).getUTCMonth()]
export const weekday = (iso: string) => WEEKDAYS[parseDay(iso).getUTCDay()]
export const weekdayShort = (iso: string) => WEEKDAYS_SHORT[parseDay(iso).getUTCDay()]

export function num(value: number, digits = 0): string {
  return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

/** One decimal for small daily values, none from 100 up. */
export const units = (value: number) => num(value, value >= 100 ? 0 : 1)

export function signedPct(ratio: number, digits = 1): string {
  const pct = ratio * 100
  const sign = pct > 0.05 ? '+' : pct < -0.05 ? '−' : '±'
  return `${sign}${num(Math.abs(pct), digits)}%`
}

export const money = (value: number) => `$${num(value, 2)}`

const titleCase = (word: string) => word.charAt(0) + word.slice(1).toLowerCase()

/**
 * The real hierarchy encoded in an M5 id. M5 has no product names, so this is the most
 * readable honest label: FOODS_3_090 at CA_1 -> "Foods / Dept. 3 / Item 090",
 * "California, Store 1".
 */
export function describeSeries(itemId: string, storeId: string) {
  const [cat = itemId, dept = '', item = ''] = itemId.split('_')
  const [state = storeId, store = ''] = storeId.split('_')
  const category = titleCase(cat)
  return {
    category,
    dept,
    itemLabel: item ? `Item ${item}` : itemId,
    path: dept ? `${category} / Dept. ${dept}` : category,
    crumb: [category, dept && `Dept. ${dept}`, item && `Item ${item}`].filter(Boolean).join(' / '),
    place: STATES[state] ? `${STATES[state]}, Store ${store}` : storeId,
  }
}
