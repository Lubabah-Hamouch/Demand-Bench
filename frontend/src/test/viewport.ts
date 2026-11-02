// jsdom has no layout, so window.matchMedia does not exist. This stands in for it with a
// settable viewport width. (min-width: Npx) queries follow that width (see useMinWidth);
// any other query, such as Recharts' prefers-reduced-motion, does not match.
const DESKTOP_WIDTH = 1440

let width = DESKTOP_WIDTH
const lists = new Set<{ query: string; listeners: Set<() => void> }>()

const matches = (query: string) => {
  const min = /^\(min-width:\s*(\d+)px\)$/.exec(query)
  return min !== null && width >= Number(min[1])
}

export function installMatchMedia() {
  window.matchMedia = (query: string) => {
    // Registered only once something listens: useMinWidth also calls matchMedia on every
    // render just to read `matches`.
    const entry = { query, listeners: new Set<() => void>() }
    const listen = (fn: () => void) => {
      lists.add(entry)
      entry.listeners.add(fn)
    }
    return {
      get matches() {
        return matches(query)
      },
      media: query,
      onchange: null,
      addEventListener: (_: string, fn: () => void) => listen(fn),
      removeEventListener: (_: string, fn: () => void) => entry.listeners.delete(fn),
      addListener: listen,
      removeListener: (fn: () => void) => entry.listeners.delete(fn),
      dispatchEvent: () => false,
    } as unknown as MediaQueryList
  }
}

/** Sets the viewport width the media queries see, notifying subscribers. */
export function setViewportWidth(px: number) {
  width = px
  for (const entry of lists) for (const fn of entry.listeners) fn()
}

export function resetViewport() {
  setViewportWidth(DESKTOP_WIDTH)
  lists.clear()
}
