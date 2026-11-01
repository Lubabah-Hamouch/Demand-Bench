import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterAll, afterEach, beforeAll } from 'vitest'
import { requestLog, server } from './server'

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  requestLog.length = 0
})
afterAll(() => server.close())

// jsdom has no layout engine; Recharts' ResponsiveContainer only needs the observer to
// exist (the chart renders at its initial dimension).
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
}
