import { useCallback, useMemo, useReducer, useRef } from 'react'

import { clone, safeJson } from '../lib/builder'
import { HISTORY_COALESCE_MS, HISTORY_LIMIT } from '../lib/builderConstants'
import type { BuilderDocument } from '../types'

type DocumentState = {
  document: BuilderDocument | null
  dirty: boolean
  historyVersion: number
  pastCount: number
  futureCount: number
}

type DocumentAction =
  | { type: 'set-document'; value: BuilderDocument | null }
  | { type: 'set-dirty'; value: boolean }
  | { type: 'commit'; change: (next: BuilderDocument) => void; recordHistory: boolean; historyKey: string }
  | { type: 'replace-from-history'; snapshot: string }
  | { type: 'reset-history' }

const INITIAL_DOCUMENT_STATE: DocumentState = { document: null, dirty: false, historyVersion: 0, pastCount: 0, futureCount: 0 }

export function useBuilderDocumentState() {
  const past = useRef<string[]>([])
  const future = useRef<string[]>([])
  const documentRef = useRef<BuilderDocument | null>(null)
  const savedSnapshot = useRef('')
  const lastHistory = useRef({ key: '', at: 0 })
  const historyCounts = () => ({ pastCount: past.current.length, futureCount: future.current.length })

  const [state, dispatch] = useReducer((current: DocumentState, action: DocumentAction): DocumentState => {
    switch (action.type) {
      case 'set-document':
        documentRef.current = action.value
        return { ...current, document: action.value, historyVersion: current.historyVersion + 1, ...historyCounts() }
      case 'set-dirty':
        return { ...current, dirty: action.value }
      case 'commit': {
        if (!current.document) return current
        const before = safeJson(current.document)
        const next = clone(current.document)
        action.change(next)
        const after = safeJson(next)
        if (before === after) return current
        if (action.recordHistory) {
          const now = Date.now()
          const coalesce = Boolean(action.historyKey) && lastHistory.current.key === action.historyKey && now - lastHistory.current.at <= HISTORY_COALESCE_MS
          if (!coalesce) past.current.push(before)
          if (past.current.length > HISTORY_LIMIT) past.current.shift()
          future.current = []
          lastHistory.current = { key: action.historyKey, at: now }
        }
        documentRef.current = next
        return { document: next, dirty: after !== savedSnapshot.current, historyVersion: current.historyVersion + 1, ...historyCounts() }
      }
      case 'replace-from-history': {
        const document = JSON.parse(action.snapshot) as BuilderDocument
        documentRef.current = document
        return { document, dirty: action.snapshot !== savedSnapshot.current, historyVersion: current.historyVersion + 1, ...historyCounts() }
      }
      case 'reset-history':
        return { ...current, historyVersion: current.historyVersion + 1, ...historyCounts() }
    }
  }, INITIAL_DOCUMENT_STATE)

  const stateBytes = useMemo(() => state.document ? new Blob([safeJson(state.document.schema)]).size : 0, [state.document])

  const setDocument = useCallback((value: BuilderDocument | null) => dispatch({ type: 'set-document', value }), [])
  const setDirty = useCallback((value: boolean) => dispatch({ type: 'set-dirty', value }), [])

  const resetHistory = useCallback(() => {
    past.current = []
    future.current = []
    lastHistory.current = { key: '', at: 0 }
    dispatch({ type: 'reset-history' })
  }, [])

  const commit = useCallback((change: (next: BuilderDocument) => void, recordHistory = true, historyKey = '') => {
    dispatch({ type: 'commit', change, recordHistory, historyKey })
  }, [])

  const undo = useCallback(() => {
    if (!state.document || !past.current.length) return
    const snapshot = past.current.pop()!
    future.current.push(safeJson(state.document))
    lastHistory.current = { key: '', at: 0 }
    dispatch({ type: 'replace-from-history', snapshot })
  }, [state.document])

  const redo = useCallback(() => {
    if (!state.document || !future.current.length) return
    const snapshot = future.current.pop()!
    past.current.push(safeJson(state.document))
    lastHistory.current = { key: '', at: 0 }
    dispatch({ type: 'replace-from-history', snapshot })
  }, [state.document])

  return {
    document: state.document,
    setDocument,
    documentRef,
    dirty: state.dirty,
    setDirty,
    savedSnapshot,
    past,
    future,
    lastHistory,
    stateBytes,
    commit,
    undo,
    redo,
    resetHistory,
    canUndo: state.pastCount > 0,
    canRedo: state.futureCount > 0,
  }
}
