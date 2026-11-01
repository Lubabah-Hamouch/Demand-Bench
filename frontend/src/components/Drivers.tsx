import { api } from '../api/client'
import { FEATURE_LABELS } from '../lib/content'
import { num } from '../lib/format'
import { useAsync } from '../lib/hooks'
import { ErrorNote, SectionHeading, Skeleton } from './Status'

const SHOWN = 10

export function Drivers() {
  const importance = useAsync('importance', (signal) => api.importance(signal))
  const features = importance.data?.features.slice(0, SHOWN) ?? []
  const top = features[0]?.share ?? 1

  return (
    <section id="drivers" aria-label="What the model leans on" className="min-w-0 flex-[1_1_360px]">
      <SectionHeading index="03" title="What the model leans on" />
      <p className="mt-1.5 text-sm text-muted">One model covers every series, so these weights are the same for all of them.</p>
      <div className="mt-[18px] flex flex-col gap-3">
        {importance.status === 'error' && <ErrorNote error={importance.error} onRetry={importance.reload} />}
        {importance.status === 'loading' && !importance.data &&
          Array.from({ length: SHOWN }, (_, i) => <Skeleton key={i} className="h-9" />)}
        {features.map((f) => (
          <div key={f.feature}>
            <div className="flex justify-between gap-3 text-sm">
              <span>
                {FEATURE_LABELS[f.feature] ?? f.feature}{' '}
                <span className="font-mono text-[11.5px] text-muted">{f.feature}</span>
              </span>
              <span className="tabular font-semibold">{num(f.share * 100, 1)}%</span>
            </div>
            <div className="mt-1.5 h-2.5 bg-brand-tint">
              <div className="h-2.5 bg-brand" style={{ width: `${(f.share / top) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </section>
  )
}
