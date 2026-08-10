import { createContext } from 'react'

export type NoticeKind = 'success' | 'error' | 'info' | 'warning'
export type NoticeOptions = { title?: string; duration?: number }
export type NotificationContextValue = {
  notify: (message: unknown, kind?: NoticeKind, options?: NoticeOptions) => void
  dismiss: (id: number) => void
}

export const NotificationContext = createContext<NotificationContextValue | null>(null)
