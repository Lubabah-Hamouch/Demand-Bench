import { useEffect, useState } from 'react'

export type AsyncState<T> =
  | { status: 'loading'; data: T | null; error: null }
  | { status: 'success'; data: T; error: null }
  | { status: 'error'; data: T | null; error: Error }

/**
 * Runs `load` whenever `key` changes, aborting the previous request. Keeps the last
 * successful data while a new request is in flight, so views can avoid flashing empty.
 * A null key means "nothing to load".
 */
export function useAsync<T>(
  key: string | null,
  load: (signal: AbortSignal) => Promise<T>,
): AsyncState<T> & { reload: () => void } {
  const [state, setState] = useState<AsyncState<T>>({ status: 'loading', data: null, error: null })
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    if (key === null) return
    const controller = new AbortController()
    setState((prev) => ({ status: 'loading', data: prev.data, error: null }))
    load(controller.signal).then(
      (data) => setState({ status: 'success', data, error: null }),
      (error: unknown) => {
        if (controller.signal.aborted) return
        setState((prev) => ({
          status: 'error',
          data: prev.data,
          error: error instanceof Error ? error : new Error(String(error)),
        }))
      },
    )
    return () => controller.abort()
    // `load` is expected to change with `key`; keying on it alone avoids refetch loops.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, attempt])

  return { ...state, reload: () => setAttempt((n) => n + 1) }
}

/** `value`, updated only after it has stopped changing for `delayMs`. */
export function useDebounced<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delayMs)
    return () => clearTimeout(id)
  }, [value, delayMs])
  return debounced
}
