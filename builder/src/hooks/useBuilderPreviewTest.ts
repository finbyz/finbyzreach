import { useCallback, useReducer } from 'react'

import type { useBuilderData } from './useBuilderData'
import { getErrorMessage } from '../lib/errors'
import type { BuilderDocument, BuilderTemplateDoctype, PreviewResult } from '../types'
import type { ModalName } from '../components/BuilderDialogs'
import type { NoticeKind, NoticeOptions } from '../components/notificationContext'

type Notify = (value: unknown, kind?: NoticeKind, options?: NoticeOptions) => void

type PreviewTestOptions = {
  document: BuilderDocument | null
  sdk: ReturnType<typeof useBuilderData>
  templateName: string
  templateDoctype: BuilderTemplateDoctype
  notify: Notify
  setModal: (modal: ModalName) => void
  resetPreviewFormat: () => void
}

type PreviewTestState = {
  preview: PreviewResult | null
  previewError: string
  recipient: string
}

type PreviewTestAction =
  | { type: 'reset-preview' }
  | { type: 'set-preview'; value: PreviewResult }
  | { type: 'set-preview-error'; value: string }
  | { type: 'set-recipient'; value: string }

const INITIAL_PREVIEW_TEST_STATE: PreviewTestState = {
  preview: null,
  previewError: '',
  recipient: '',
}

function previewTestReducer(state: PreviewTestState, action: PreviewTestAction): PreviewTestState {
  switch (action.type) {
    case 'reset-preview':
      return { ...state, preview: null, previewError: '' }
    case 'set-preview':
      return { ...state, preview: action.value }
    case 'set-preview-error':
      return { ...state, previewError: action.value }
    case 'set-recipient':
      return { ...state, recipient: action.value }
  }
}

export function useBuilderPreviewTest({ document, sdk, templateName, templateDoctype, notify, setModal, resetPreviewFormat }: PreviewTestOptions) {
  const [state, dispatch] = useReducer(previewTestReducer, INITIAL_PREVIEW_TEST_STATE)

  const setRecipient = useCallback((value: string) => dispatch({ type: 'set-recipient', value }), [])

  const openPreview = useCallback(async () => {
    if (!document) return
    dispatch({ type: 'reset-preview' })
    resetPreviewFormat()
    setModal('preview')
    try {
      const response = await sdk.preview.call({
        schema: JSON.stringify(document.schema),
        metadata: JSON.stringify(document.metadata),
        reference_doctype: document.metadata.reference_doctype,
        reference_name: document.metadata.preview_document,
      })
      dispatch({ type: 'set-preview', value: response.message })
    } catch (error) {
      dispatch({ type: 'set-preview-error', value: getErrorMessage(error, 'Preview could not be compiled.') })
    }
  }, [document, resetPreviewFormat, sdk.preview, setModal])

  const sendTest = useCallback(async () => {
    if (!document || !state.recipient.trim()) return
    try {
      await sdk.testEmail.call({
        template_name: templateName,
        template_doctype: templateDoctype,
        schema: JSON.stringify(document.schema),
        metadata: JSON.stringify(document.metadata),
        recipient: state.recipient.trim(),
        reference_doctype: document.metadata.reference_doctype,
        reference_name: document.metadata.preview_document,
      })
      setModal(null)
      notify('Test email queued', 'success')
    } catch (error) {
      notify(getErrorMessage(error, 'Test email could not be queued.'), 'error')
    }
  }, [document, notify, sdk.testEmail, setModal, state.recipient, templateDoctype, templateName])

  const retryPreview = useCallback(() => { void openPreview() }, [openPreview])
  const sendTestEmail = useCallback(() => { void sendTest() }, [sendTest])

  return {
    preview: state.preview,
    previewError: state.previewError,
    recipient: state.recipient,
    setRecipient,
    retryPreview,
    sendTestEmail,
  }
}
