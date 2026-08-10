import { useCallback, useRef } from 'react'

import type { TextEditorController } from '../components/Canvas'

export function useTextEditorBridge() {
  const textEditorControllers = useRef(new Map<string, TextEditorController>())

  const registerTextEditor = useCallback((controller: TextEditorController | null, blockId?: string) => {
    if (controller) {
      textEditorControllers.current.set(controller.blockId, controller)
      return
    }
    if (blockId) {
      textEditorControllers.current.delete(blockId)
      return
    }
    textEditorControllers.current.clear()
  }, [])

  const focusTextEditor = useCallback((blockId: string) => {
    textEditorControllers.current.get(blockId)?.focus()
  }, [])

  const prepareMergeField = useCallback((blockId: string) => {
    textEditorControllers.current.get(blockId)?.captureSelection()
  }, [])

  const insertMergeField = useCallback((blockId: string, token: string) => {
    const controller = textEditorControllers.current.get(blockId)
    if (!controller) return false
    return controller.insertDynamicField(token)
  }, [])

  return { registerTextEditor, focusTextEditor, prepareMergeField, insertMergeField }
}
