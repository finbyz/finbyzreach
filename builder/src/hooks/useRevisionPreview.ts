import { useCallback, useReducer } from 'react'

import type { useBuilderData } from './useBuilderData'
import { getErrorMessage } from '../lib/errors'
import type { RevisionPreviewResult } from '../types'
import type { ModalName, PreviewFormat } from '../components/BuilderDialogs'

type RevisionPreviewState = {
  revisionPreview: RevisionPreviewResult | null
  revisionPreviewError: string
  revisionPreviewName: string
}

type RevisionPreviewAction =
  | { type: 'start'; revisionName: string }
  | { type: 'success'; value: RevisionPreviewResult }
  | { type: 'error'; value: string }

const INITIAL_REVISION_PREVIEW_STATE: RevisionPreviewState = {
  revisionPreview: null,
  revisionPreviewError: '',
  revisionPreviewName: '',
}

function revisionPreviewReducer(state: RevisionPreviewState, action: RevisionPreviewAction): RevisionPreviewState {
  switch (action.type) {
    case 'start':
      return { revisionPreview: null, revisionPreviewError: '', revisionPreviewName: action.revisionName }
    case 'success':
      return { ...state, revisionPreview: action.value, revisionPreviewError: '' }
    case 'error':
      return { ...state, revisionPreviewError: action.value }
  }
}

export function useRevisionPreview({
  sdk,
  templateName,
  setModal,
  setPreviewFormat,
}: {
  sdk: ReturnType<typeof useBuilderData>
  templateName: string
  setModal: (modal: ModalName) => void
  setPreviewFormat: (format: PreviewFormat) => void
}) {
  const [state, dispatch] = useReducer(revisionPreviewReducer, INITIAL_REVISION_PREVIEW_STATE)

  const openRevisionPreview = useCallback(async (revisionName: string) => {
    if (!templateName || !revisionName) return
    dispatch({ type: 'start', revisionName })
    setPreviewFormat('html')
    setModal('revision-preview')
    try {
      const response = await sdk.revisionPreview.call({ template_name: templateName, revision_name: revisionName })
      dispatch({ type: 'success', value: response.message })
    } catch (error) {
      dispatch({ type: 'error', value: getErrorMessage(error, 'Revision preview could not be loaded.') })
    }
  }, [sdk.revisionPreview, setModal, setPreviewFormat, templateName])

  const retryRevisionPreview = useCallback(() => {
    if (state.revisionPreviewName) void openRevisionPreview(state.revisionPreviewName)
  }, [openRevisionPreview, state.revisionPreviewName])

  return {
    revisionPreview: state.revisionPreview,
    revisionPreviewError: state.revisionPreviewError,
    openRevisionPreview,
    retryRevisionPreview,
  }
}
