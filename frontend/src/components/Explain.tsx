import { useEffect, useId, useLayoutEffect, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react'
import type { Explanation } from '../lib/glossary'

const GAP = 6
const MARGIN = 8
const HOVER_CLOSE_MS = 150

interface Props extends Explanation {
  /** 'onBrand' on the dark green header and sidebar. */
  tone?: 'default' | 'onBrand'
}

/**
 * A small "?" after a term that opens a short plain-language explanation: on mouse hover,
 * or pinned open with a click, Enter or Space. Escape, a click elsewhere or scrolling
 * closes it. The panel is fixed-positioned (and kept inside the viewport) so scrolling
 * containers such as the sidebar cannot clip it.
 */
export function Explain({ term, text, read, tone = 'default' }: Props) {
  const [pinned, setPinned] = useState(false)
  const [hovered, setHovered] = useState(false)
  const open = pinned || hovered
  const id = useId()
  const wrapper = useRef<HTMLSpanElement>(null)
  const button = useRef<HTMLButtonElement>(null)
  const panel = useRef<HTMLSpanElement>(null)
  const hoverTimer = useRef<number | undefined>(undefined)

  const close = () => {
    window.clearTimeout(hoverTimer.current)
    setPinned(false)
    setHovered(false)
  }

  // Place the panel under the button (above it if there is no room below), before paint.
  useLayoutEffect(() => {
    if (!open || !button.current || !panel.current) return
    const anchor = button.current.getBoundingClientRect()
    const { offsetWidth: width, offsetHeight: height } = panel.current
    const left = Math.max(MARGIN, Math.min(anchor.left - 12, window.innerWidth - width - MARGIN))
    const fitsBelow = anchor.bottom + GAP + height <= window.innerHeight - MARGIN
    panel.current.style.left = `${left}px`
    panel.current.style.top = `${fitsBelow ? anchor.bottom + GAP : Math.max(MARGIN, anchor.top - GAP - height)}px`
  }, [open])

  useEffect(() => {
    if (!open) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close()
    }
    const onPointer = (e: PointerEvent) => {
      if (!wrapper.current?.contains(e.target as Node)) close()
    }
    document.addEventListener('keydown', onKey)
    document.addEventListener('pointerdown', onPointer)
    window.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('keydown', onKey)
      document.removeEventListener('pointerdown', onPointer)
      window.removeEventListener('scroll', close, true)
    }
  }, [open])

  useEffect(() => () => window.clearTimeout(hoverTimer.current), [])

  // Hover only for a mouse: on touch, the tap's click does the opening and closing.
  const onPointerEnter = (e: ReactPointerEvent) => {
    if (e.pointerType !== 'mouse') return
    window.clearTimeout(hoverTimer.current)
    setHovered(true)
  }
  const onPointerLeave = (e: ReactPointerEvent) => {
    if (e.pointerType !== 'mouse') return
    // A short delay, so the pointer can cross the gap into the panel.
    hoverTimer.current = window.setTimeout(() => setHovered(false), HOVER_CLOSE_MS)
  }

  const icon =
    tone === 'onBrand'
      ? `text-on-brand hover:text-white ${open ? 'text-white' : ''}`
      : `text-muted hover:text-brand ${open ? 'text-brand' : ''}`

  return (
    <span ref={wrapper} className="inline-flex align-middle" onPointerEnter={onPointerEnter} onPointerLeave={onPointerLeave}>
      <button
        ref={button}
        type="button"
        aria-label={`About ${term}`}
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => (pinned ? close() : setPinned(true))}
        className={`-my-1 ml-0.5 inline-flex size-6 flex-none items-center justify-center rounded-full ${icon}`}
      >
        <span
          aria-hidden="true"
          className="inline-flex size-4 items-center justify-center rounded-full border-[1.5px] border-current font-sans text-[10.5px] font-bold leading-none tracking-normal"
        >
          ?
        </span>
      </button>
      {open && (
        <span
          ref={panel}
          id={id}
          role="note"
          className="fixed left-0 top-0 z-50 block w-[280px] max-w-[calc(100vw-16px)] border-t-4 border-brand bg-white px-3.5 py-3 text-left font-sans whitespace-normal text-[13px] font-normal normal-case leading-snug tracking-normal text-ink shadow-[0_6px_18px_rgba(16,36,26,0.16)]"
        >
          <span className="block">{text}</span>
          {read && <span className="mt-1.5 block font-semibold text-brand">{read}</span>}
        </span>
      )}
    </span>
  )
}
