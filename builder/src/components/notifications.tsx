import { type PropsWithChildren, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { CheckCircle2, CircleAlert, Info, X } from 'lucide-react'

import { NotificationContext, type NoticeKind, type NoticeOptions } from './notificationContext'

type Notice = { id: number; message: string; title: string; kind: NoticeKind; duration: number }

const MAX_NOTICES = 3
const NOTICE_DURATIONS: Record<NoticeKind, number> = {
  success: 3500,
  info: 5000,
  warning: 6500,
  error: 8500,
}
const NOTICE_TITLES: Record<NoticeKind, string> = {
  success: 'Done',
  info: 'Heads up',
  warning: 'Needs attention',
  error: 'Something went wrong',
}

function getNoticeContent(value: unknown) {
  if (typeof value === 'string') return { message: value, title: '' }
  if (value && typeof value === 'object') {
    const notice = value as { message?: unknown; title?: unknown }
    return {
      message: String(notice.message ?? 'Something went wrong'),
      title: notice.title == null ? '' : String(notice.title),
    }
  }
  return { message: String(value ?? 'Something went wrong'), title: '' }
}

export function NotificationProvider({ children }: PropsWithChildren) {
  const [notices, setNotices] = useState<Notice[]>([])
  const timers = useRef(new Map<number, ReturnType<typeof setTimeout>>())
  const lastNotice = useRef({ key: '', at: 0 })

  const dismiss = useCallback((id: number) => {
    const timer = timers.current.get(id)
    if (timer) clearTimeout(timer)
    timers.current.delete(id)
    setNotices((current) => current.filter((notice) => notice.id !== id))
  }, [])

  useEffect(() => () => timers.current.forEach((timer) => clearTimeout(timer)), [])

  const notify = useCallback((value: unknown, kind: NoticeKind = 'info', options: NoticeOptions = {}) => {
    const content = getNoticeContent(value)
    const message = content.message.trim() || 'Something went wrong'
    const key = `${kind}:${message}`
    const now = Date.now()
    if (lastNotice.current.key === key && now - lastNotice.current.at < 900) return
    lastNotice.current = { key, at: now }
    const requestedDuration = Number(options.duration)
    const duration = Number.isFinite(requestedDuration)
      ? Math.max(2000, Math.min(requestedDuration, 15000))
      : NOTICE_DURATIONS[kind]
    const id = Date.now() + Math.random()
    const notice = { id, message, title: options.title || content.title || NOTICE_TITLES[kind], kind, duration }
    setNotices((current) => [...current, notice].slice(-MAX_NOTICES))
    timers.current.set(id, setTimeout(() => dismiss(id), duration))
  }, [dismiss])

  const value = useMemo(() => ({ notify, dismiss }), [dismiss, notify])
  return (
    <NotificationContext.Provider value={value}>
      {children}
      <div className="toast-stack" aria-live="polite" aria-relevant="additions">
        {notices.map((notice) => {
          const Icon = notice.kind === 'success' ? CheckCircle2 : notice.kind === 'info' ? Info : CircleAlert
          return (
            <article className={`toast toast--${notice.kind}`} key={notice.id} role={notice.kind === 'error' ? 'alert' : 'status'} aria-atomic="true">
              <span className="toast__icon"><Icon size={18} /></span>
              <div className="toast__content"><strong>{notice.title}</strong><p>{notice.message}</p></div>
              <button type="button" className="toast__dismiss" aria-label={`Dismiss ${notice.title} notification`} onClick={() => dismiss(notice.id)}><X size={15} /></button>
              <i className="toast__progress" aria-hidden="true" style={{ animationDuration: `${notice.duration}ms` }} />
            </article>
          )
        })}
      </div>
    </NotificationContext.Provider>
  )
}
