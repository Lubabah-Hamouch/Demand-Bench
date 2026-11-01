// jsdom has no layout, so Recharts' ResponsiveContainer measures 0x0 and draws nothing.
// Tests that need the chart drawn replace it with a fixed-size container:
//   vi.mock('recharts', async (importOriginal) => {
//     const { withFixedSizeContainer } = await import('./test/recharts')
//     return withFixedSizeContainer(await importOriginal<object>())
//   })
import { cloneElement, isValidElement, type ReactNode } from 'react'

export const CHART_SIZE = { width: 1000, height: 380 }

export function withFixedSizeContainer<T extends object>(recharts: T): T {
  return {
    ...recharts,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => (
      <div style={CHART_SIZE}>{isValidElement(children) ? cloneElement(children, CHART_SIZE) : children}</div>
    ),
  }
}
