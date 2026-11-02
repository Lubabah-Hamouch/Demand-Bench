import type { ReactNode } from 'react'
import { ApiError, API_BASE_URL, isOffline } from '../api/client'

export function Skeleton({ className = '' }: { className?: string }) {
  return <div aria-hidden="true" className={`animate-pulse bg-brand-tint ${className}`} />
}

/** The chart's frame (axis labels, gridlines, forecast region) with a pulsing body. */
export function ChartSkeleton() {
  return (
    <div role="status" aria-label="Loading sales history and forecast" className="grid h-[380px] grid-cols-[48px_minmax(0,1fr)] pt-7">
      <div className="flex flex-col justify-between pb-7 pr-2">
        {Array.from({ length: 5 }, (_, i) => (
          <Skeleton key={i} className="ml-auto h-3 w-6" />
        ))}
      </div>
      <div className="relative">
        <div className="absolute inset-x-0 bottom-7 top-0 flex flex-col justify-between">
          {Array.from({ length: 5 }, (_, i) => (
            <div key={i} className="border-t border-rule" />
          ))}
        </div>
        <div className="absolute bottom-7 left-0 right-[13.5%] top-[35%] animate-pulse bg-brand-tint/70" />
        <div className="absolute bottom-7 right-0 top-0 w-[13.5%] border-l-2 border-coral/40 bg-coral/6" />
        <div className="absolute inset-x-0 bottom-0 flex h-5 justify-between px-6">
          {Array.from({ length: 7 }, (_, i) => (
            <Skeleton key={i} className="h-3 w-7" />
          ))}
        </div>
      </div>
    </div>
  )
}

/** Four week rows of the 28-day table. */
export function TableSkeleton() {
  return (
    <div role="status" aria-label="Loading forecast" className="mt-4">
      <div className="flex gap-6 border-b-2 border-brand bg-surface-alt px-3 py-3">
        {Array.from({ length: 9 }, (_, i) => (
          <Skeleton key={i} className="h-3 flex-1" />
        ))}
      </div>
      {Array.from({ length: 4 }, (_, r) => (
        <div key={r} className="flex gap-6 border-b border-rule px-3 py-3">
          {Array.from({ length: 9 }, (_, i) => (
            <div key={i} className="flex flex-1 flex-col items-end gap-1.5">
              <Skeleton className="h-3.5 w-full" />
              <Skeleton className="h-2.5 w-2/3" />
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

function AlertIcon() {
  return (
    <svg width="28" height="28" viewBox="0 0 28 28" aria-hidden="true" className="flex-none">
      <circle cx="14" cy="14" r="12.5" fill="none" stroke="currentColor" strokeWidth="2" />
      <path d="M14 7.5 V15.5" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="14" cy="20" r="1.5" fill="currentColor" />
    </svg>
  )
}

function OfflineHelp() {
  return (
    <>
      Nothing is answering at <span className="font-mono text-[13px]">{API_BASE_URL}</span>, or it does not allow
      requests from this page. Start it from <span className="font-mono text-[13px]">backend/</span> with{' '}
      <span className="font-mono text-[13px]">uv run python -m demandbench.serving</span>; its{' '}
      <span className="font-mono text-[13px]">DEMANDBENCH_CORS_ORIGINS</span> must include{' '}
      <span className="font-mono text-[13px]">{window.location.origin}</span>.
    </>
  )
}

/**
 * A failed request, in the page's own language: a green rule like the section
 * dividers, the display face for the headline, and a retry in the house button style.
 */
export function ErrorNote({
  error,
  onRetry,
  title,
  compact = false,
}: {
  error: Error
  onRetry?: () => void
  title?: string
  compact?: boolean
}) {
  const offline = isOffline(error)
  const notFound = error instanceof ApiError && error.status === 404
  const body: ReactNode = offline ? <OfflineHelp /> : error.message
  return (
    <div role="alert" className={`flex gap-4 border-t-4 border-brand bg-surface-alt ${compact ? 'px-4 py-3.5' : 'px-6 py-5'}`}>
      <span className="mt-0.5 text-brand">
        <AlertIcon />
      </span>
      <div className="min-w-0">
        <p className={`font-display font-bold text-brand ${compact ? 'text-lg' : 'text-2xl'}`}>
          {title ?? (offline ? 'The forecasting API is offline' : notFound ? 'Series not found' : 'Something went wrong')}
        </p>
        <p className="mt-1.5 max-w-3xl text-[15px] leading-relaxed text-ink">{body}</p>
        {onRetry && (
          <button
            type="button"
            onClick={onRetry}
            className="mt-3.5 min-h-10 rounded-full border-[1.5px] border-brand bg-white px-4 text-sm font-semibold text-brand hover:bg-brand-tint"
          >
            Try again
          </button>
        )}
      </div>
    </div>
  )
}

/** The numbered section heading with the thick green rule. */
export function SectionHeading({ index, title, aside }: { index: string; title: string; aside?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-5 gap-y-2 border-t-4 border-brand pt-3.5">
      <h2 className="font-display text-[28px] font-bold text-brand sm:text-[34px]">
        <span className="text-coral">{index}</span> {title}
      </h2>
      {aside}
    </div>
  )
}
