import { startTransition, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'
import { FrappeContext } from 'frappe-react-sdk'

type RealtimeStatus = 'disabled' | 'connecting' | 'connected' | 'reconnecting' | 'disconnected' | 'error'

export type BuilderRealtimeEvent = {
  template_name?: string
  modified?: string
  content_hash?: string
  revision?: string | null
  revision_number?: number | null
  actor?: string
  client_id?: string
}

export type BuilderAssetEvent = {
  template_name?: string
  file_name?: string | null
  actor?: string
  client_id?: string
}

type DocViewersEvent = {
  doctype?: string
  docname?: string
  users?: string[]
}

type BuilderSocket = {
  connected?: boolean
  emit: (event: string, ...args: unknown[]) => void
  on: (event: string, handler: (...args: any[]) => void) => BuilderSocket
  off: (event: string, handler?: (...args: any[]) => void) => BuilderSocket
  io?: {
    on: (event: string, handler: (...args: any[]) => void) => void
    off: (event: string, handler?: (...args: any[]) => void) => void
  }
}

type UseBuilderRealtimeOptions = {
  templateName: string
  enabled?: boolean
  onRemoteSave?: (event: BuilderRealtimeEvent) => void
  onRevisionCreated?: (event: BuilderRealtimeEvent) => void
  onAssetsChanged?: (event: BuilderAssetEvent) => void
  onAiStep?: (event: { template_name?: string; step: { type: string; label: string; detail?: string } }) => void
}

const EMAIL_TEMPLATE_DOCTYPE = 'Email Template'

function makeClientId(templateName: string) {
  const key = `email-builder-socket-client:${window.location.host}:${templateName || 'new'}`
  try {
    const existing = sessionStorage.getItem(key)
    if (existing) return existing
    const next = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`
    sessionStorage.setItem(key, next)
    return next
  } catch {
    return `${Date.now()}-${Math.random().toString(36).slice(2)}`
  }
}

function useLatestRef<T>(value: T) {
  const ref = useRef(value)
  ref.current = value
  return ref
}

export function useBuilderRealtime({
  templateName,
  enabled = true,
  onRemoteSave,
  onRevisionCreated,
  onAssetsChanged,
  onAiStep,
}: UseBuilderRealtimeOptions) {
  const frappe = useContext(FrappeContext)
  const socket = frappe?.socket as BuilderSocket | undefined
  const [status, setStatus] = useState<RealtimeStatus>(() => (socket ? (socket.connected ? 'connected' : 'connecting') : 'disabled'))
  const [viewers, setViewers] = useState<string[]>([])
  const remoteSaveRef = useLatestRef(onRemoteSave)
  const revisionCreatedRef = useLatestRef(onRevisionCreated)
  const assetsChangedRef = useLatestRef(onAssetsChanged)
  const aiStepRef = useLatestRef(onAiStep)
  const clientId = useMemo(() => makeClientId(templateName), [templateName])

  const isOwnEvent = useCallback((event?: { client_id?: string }) => Boolean(event?.client_id && event.client_id === clientId), [clientId])
  const isCurrentTemplate = useCallback((event?: { template_name?: string }) => !event?.template_name || event.template_name === templateName, [templateName])

  useEffect(() => {
    if (!enabled || !templateName || !socket) {
      setStatus(enabled && templateName ? 'error' : 'disabled')
      setViewers([])
      return
    }

    const subscribe = () => {
      socket.emit('doc_subscribe', EMAIL_TEMPLATE_DOCTYPE, templateName)
      socket.emit('doc_open', EMAIL_TEMPLATE_DOCTYPE, templateName)
    }
    const unsubscribe = () => {
      socket.emit('doc_close', EMAIL_TEMPLATE_DOCTYPE, templateName)
      socket.emit('doc_unsubscribe', EMAIL_TEMPLATE_DOCTYPE, templateName)
    }
    const onConnect = () => { setStatus('connected'); subscribe() }
    const onDisconnect = () => { setStatus('disconnected'); setViewers([]) }
    const onReconnectAttempt = () => setStatus('reconnecting')
    const onConnectError = () => setStatus('error')
    const onDocViewers = (event: DocViewersEvent) => {
      if (event.doctype !== EMAIL_TEMPLATE_DOCTYPE || event.docname !== templateName) return
      startTransition(() => setViewers(Array.isArray(event.users) ? event.users : []))
    }
    const onSaved = (event: BuilderRealtimeEvent) => {
      if (!isCurrentTemplate(event) || isOwnEvent(event)) return
      startTransition(() => remoteSaveRef.current?.(event))
    }
    const onRevision = (event: BuilderRealtimeEvent) => {
      if (!isCurrentTemplate(event) || isOwnEvent(event)) return
      startTransition(() => revisionCreatedRef.current?.(event))
    }
    const onAssets = (event: BuilderAssetEvent) => {
      if (!isCurrentTemplate(event)) return
      startTransition(() => assetsChangedRef.current?.(event))
    }
    const onAiStepHandler = (event: { template_name?: string; step: { type: string; label: string; detail?: string } }) => {
      if (!isCurrentTemplate(event)) return
      startTransition(() => aiStepRef.current?.(event))
    }

    setStatus(socket.connected ? 'connected' : 'connecting')
    subscribe()
    socket.on('connect', onConnect)
    socket.on('disconnect', onDisconnect)
    socket.on('connect_error', onConnectError)
    socket.on('doc_viewers', onDocViewers)
    socket.on('email_builder_saved', onSaved)
    socket.on('email_builder_revision_created', onRevision)
    socket.on('email_builder_assets_changed', onAssets)
    socket.on('email_builder_ai_step', onAiStepHandler)
    socket.io?.on('reconnect_attempt', onReconnectAttempt)
    socket.io?.on('reconnect', onConnect)

    return () => {
      unsubscribe()
      socket.off('connect', onConnect)
      socket.off('disconnect', onDisconnect)
      socket.off('connect_error', onConnectError)
      socket.off('doc_viewers', onDocViewers)
      socket.off('email_builder_saved', onSaved)
      socket.off('email_builder_revision_created', onRevision)
      socket.off('email_builder_assets_changed', onAssets)
      socket.off('email_builder_ai_step', onAiStepHandler)
      socket.io?.off('reconnect_attempt', onReconnectAttempt)
      socket.io?.off('reconnect', onConnect)
    }
  }, [aiStepRef, assetsChangedRef, enabled, isCurrentTemplate, isOwnEvent, remoteSaveRef, revisionCreatedRef, socket, templateName])

  return {
    clientId,
    status,
    connected: status === 'connected',
    viewers,
  }
}

export type { RealtimeStatus }
