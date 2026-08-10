import { type PropsWithChildren, useEffect, useRef } from 'react'
import { X } from 'lucide-react'

export function Modal({ title, children, onClose, width = 760 }: PropsWithChildren<{ title: string; onClose: () => void; width?: number }>) {
  const dialogRef = useRef<HTMLElement>(null)
  const onCloseRef = useRef(onClose)
  useEffect(() => { onCloseRef.current = onClose }, [onClose])
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onCloseRef.current() }
    }
    window.addEventListener('keydown', onKeyDown)
    dialogRef.current?.focus()
    return () => { window.removeEventListener('keydown', onKeyDown); previous?.focus() }
  }, [])
  return (
    <div className="modal-backdrop" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}>
      <section ref={dialogRef} tabIndex={-1} className="modal-card" role="dialog" aria-modal="true" aria-label={title} style={{ maxWidth: width }}>
        <header><h2>{title}</h2><button type="button" className="icon-button" onClick={onClose} aria-label="Close"><X size={18} /></button></header>
        <div className="modal-body">{children}</div>
      </section>
    </div>
  )
}

export function Spinner({ label = 'Loading' }: { label?: string }) {
  return <div className="loading-state"><span className="spinner" /><strong>{label}</strong></div>
}

export function SkeletonLine({ width = '100%', height = 10 }: { width?: string; height?: number }) {
  return <span className="skeleton-line" style={{ width, height }} />
}

export function DialogLoadingFallback({ label = 'Loading dialog' }: { label?: string }) {
  return (
    <div className="modal-backdrop dialog-loading-fallback" role="status" aria-live="polite">
      <section className="modal-card dialog-skeleton-card" aria-label={label}>
        <header>
          <div>
            <SkeletonLine width="150px" height={16} />
            <SkeletonLine width="92px" height={8} />
          </div>
          <SkeletonLine width="32px" height={32} />
        </header>
        <div className="dialog-skeleton-body">
          <SkeletonLine width="78%" height={12} />
          <SkeletonLine width="100%" height={220} />
          <div className="dialog-skeleton-row"><SkeletonLine width="35%" height={34} /><SkeletonLine width="28%" height={34} /></div>
        </div>
      </section>
    </div>
  )
}

export function PanelSkeleton({ side, open }: { side: 'sidebar' | 'inspector'; open: boolean }) {
  if (!open) return null
  const isSidebar = side === 'sidebar'
  return (
    <aside className={`${isSidebar ? 'builder-sidebar' : 'builder-inspector'} is-open builder-panel-skeleton`} aria-label={isSidebar ? 'Loading content library' : 'Loading inspector'} aria-live="polite">
      {isSidebar ? (
        <>
          <nav className="sidebar-tabs skeleton-tabs"><SkeletonLine /><SkeletonLine /><SkeletonLine /><SkeletonLine /></nav>
          <div className="sidebar-scroll skeleton-panel-body">
            <SkeletonLine width="58%" height={18} />
            <SkeletonLine width="100%" height={34} />
            <div className="skeleton-card-grid">
              {Array.from({ length: 8 }).map((_, index) => <SkeletonLine key={index} height={72} />)}
            </div>
          </div>
        </>
      ) : (
        <>
          <header className="inspector-header"><div><SkeletonLine width="42px" height={8} /><SkeletonLine width="150px" height={17} /></div><SkeletonLine width="34px" height={34} /></header>
          <div className="inspector-tabs skeleton-tabs"><SkeletonLine /><SkeletonLine /><SkeletonLine /></div>
          <div className="inspector-scroll skeleton-panel-body">
            {Array.from({ length: 4 }).map((_, index) => (
              <section className="inspector-group skeleton-group" key={index}>
                <SkeletonLine width="40%" height={10} />
                <SkeletonLine width="100%" height={38} />
                <SkeletonLine width="84%" height={38} />
              </section>
            ))}
          </div>
        </>
      )}
    </aside>
  )
}

export function EmptyState({ title, description }: { title: string; description?: string }) {
  return <div className="empty-state"><strong>{title}</strong>{description && <span>{description}</span>}</div>
}
