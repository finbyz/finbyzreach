import { useEffect } from 'react'

import type { Selection } from '../types'

type KeyboardShortcutOptions = {
  dirty: boolean
  selection: Selection
  undo: () => void
  redo: () => void
  deleteNode: (selection: NonNullable<Selection>) => void
  readOnly?: boolean
}

export function useBuilderKeyboardShortcuts({ dirty, selection, undo, redo, deleteNode, readOnly = false }: KeyboardShortcutOptions) {
  useEffect(() => {
    const onKeyDown = (event: globalThis.KeyboardEvent) => {
      const target = event.target as HTMLElement
      if (target.matches('input,textarea,select,[contenteditable="true"]')) return
      if (!readOnly && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'z') {
        event.preventDefault()
        if (event.shiftKey) redo()
        else undo()
        return
      }
      if (!readOnly && (event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'y') {
        event.preventDefault()
        redo()
        return
      }
      if (!readOnly && (event.key === 'Delete' || event.key === 'Backspace') && selection) {
        event.preventDefault()
        deleteNode(selection)
      }
    }
    const beforeUnload = (event: BeforeUnloadEvent) => { if (dirty) event.preventDefault() }
    window.addEventListener('keydown', onKeyDown)
    window.addEventListener('beforeunload', beforeUnload)
    return () => {
      window.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('beforeunload', beforeUnload)
    }
  }, [deleteNode, dirty, readOnly, redo, selection, undo])
}
