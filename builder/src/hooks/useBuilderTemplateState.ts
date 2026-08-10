import { useCallback, useReducer } from 'react'

import type { RecoveryDraft } from '../components/BuilderDialogs'

type TemplateState = {
  modified: string
  mode: string
  requiresOverwrite: boolean
  saving: boolean
  saveConflict: string
  recoveryDraft: RecoveryDraft | null
}

type TemplateAction =
  | { type: 'patch'; value: Partial<TemplateState> }
  | { type: 'set-modified'; value: string }
  | { type: 'set-mode'; value: string }
  | { type: 'set-requires-overwrite'; value: boolean }
  | { type: 'set-saving'; value: boolean }
  | { type: 'set-save-conflict'; value: string }
  | { type: 'set-recovery-draft'; value: RecoveryDraft | null }

const INITIAL_TEMPLATE_STATE: TemplateState = {
  modified: '',
  mode: 'Visual',
  requiresOverwrite: false,
  saving: false,
  saveConflict: '',
  recoveryDraft: null,
}

function templateReducer(state: TemplateState, action: TemplateAction): TemplateState {
  switch (action.type) {
    case 'patch':
      return { ...state, ...action.value }
    case 'set-modified':
      return { ...state, modified: action.value }
    case 'set-mode':
      return { ...state, mode: action.value }
    case 'set-requires-overwrite':
      return { ...state, requiresOverwrite: action.value }
    case 'set-saving':
      return { ...state, saving: action.value }
    case 'set-save-conflict':
      return { ...state, saveConflict: action.value }
    case 'set-recovery-draft':
      return { ...state, recoveryDraft: action.value }
  }
}

export function useBuilderTemplateState() {
  const [state, dispatch] = useReducer(templateReducer, INITIAL_TEMPLATE_STATE)

  const patchTemplateState = useCallback((value: Partial<TemplateState>) => dispatch({ type: 'patch', value }), [])
  const setModified = useCallback((value: string) => dispatch({ type: 'set-modified', value }), [])
  const setMode = useCallback((value: string) => dispatch({ type: 'set-mode', value }), [])
  const setRequiresOverwrite = useCallback((value: boolean) => dispatch({ type: 'set-requires-overwrite', value }), [])
  const setSaving = useCallback((value: boolean) => dispatch({ type: 'set-saving', value }), [])
  const setSaveConflict = useCallback((value: string) => dispatch({ type: 'set-save-conflict', value }), [])
  const setRecoveryDraft = useCallback((value: RecoveryDraft | null) => dispatch({ type: 'set-recovery-draft', value }), [])

  return {
    ...state,
    patchTemplateState,
    setModified,
    setMode,
    setRequiresOverwrite,
    setSaving,
    setSaveConflict,
    setRecoveryDraft,
  }
}
