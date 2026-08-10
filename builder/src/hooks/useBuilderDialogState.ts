import { useCallback, useReducer } from 'react'

import type { ModalName, PreviewFormat } from '../components/BuilderDialogs'
import type { Viewport } from '../types'

type DialogState = {
  modal: ModalName
  previewWidth: Viewport
  previewFormat: PreviewFormat
  componentName: string
  componentCategory: string
  overwriteConfirmationOpen: boolean
}

type DialogAction =
  | { type: 'patch'; value: Partial<DialogState> }
  | { type: 'set-modal'; value: ModalName }
  | { type: 'set-preview-width'; value: Viewport }
  | { type: 'set-preview-format'; value: PreviewFormat }
  | { type: 'set-component-name'; value: string }
  | { type: 'set-component-category'; value: string }
  | { type: 'set-overwrite-confirmation'; value: boolean }

const INITIAL_DIALOG_STATE: DialogState = {
  modal: null,
  previewWidth: 'desktop',
  previewFormat: 'html',
  componentName: '',
  componentCategory: 'Content',
  overwriteConfirmationOpen: false,
}

function dialogReducer(state: DialogState, action: DialogAction): DialogState {
  switch (action.type) {
    case 'patch':
      return { ...state, ...action.value }
    case 'set-modal':
      return { ...state, modal: action.value }
    case 'set-preview-width':
      return { ...state, previewWidth: action.value }
    case 'set-preview-format':
      return { ...state, previewFormat: action.value }
    case 'set-component-name':
      return { ...state, componentName: action.value }
    case 'set-component-category':
      return { ...state, componentCategory: action.value }
    case 'set-overwrite-confirmation':
      return { ...state, overwriteConfirmationOpen: action.value }
  }
}

export function useBuilderDialogState() {
  const [state, dispatch] = useReducer(dialogReducer, INITIAL_DIALOG_STATE)

  const setModal = useCallback((value: ModalName) => dispatch({ type: 'set-modal', value }), [])
  const setPreviewWidth = useCallback((value: Viewport) => dispatch({ type: 'set-preview-width', value }), [])
  const setPreviewFormat = useCallback((value: PreviewFormat) => dispatch({ type: 'set-preview-format', value }), [])
  const setComponentName = useCallback((value: string) => dispatch({ type: 'set-component-name', value }), [])
  const setComponentCategory = useCallback((value: string) => dispatch({ type: 'set-component-category', value }), [])
  const setOverwriteConfirmationOpen = useCallback((value: boolean) => dispatch({ type: 'set-overwrite-confirmation', value }), [])

  const closeModal = useCallback(() => setModal(null), [setModal])
  const openHistory = useCallback(() => setModal('history'), [setModal])
  const openShortcuts = useCallback(() => setModal('shortcuts'), [setModal])
  const openSuggestions = useCallback(() => setModal('suggestions'), [setModal])
  const openTestDialog = useCallback(() => setModal('test'), [setModal])
  const closeOverwriteConfirmation = useCallback(() => setOverwriteConfirmationOpen(false), [setOverwriteConfirmationOpen])

  return {
    ...state,
    setModal,
    setPreviewWidth,
    setPreviewFormat,
    setComponentName,
    setComponentCategory,
    setOverwriteConfirmationOpen,
    closeModal,
    openHistory,
    openShortcuts,
    openSuggestions,
    openTestDialog,
    closeOverwriteConfirmation,
  }
}
