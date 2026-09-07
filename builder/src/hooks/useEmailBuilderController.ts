import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useBuilderAi } from './useBuilderAi'
import { useBuilderData } from './useBuilderData'
import { useBuilderDialogState } from './useBuilderDialogState'
import { useBuilderDocumentState } from './useBuilderDocumentState'
import { useBuilderDnd } from './useBuilderDnd'
import { useBuilderImageUpload } from './useBuilderImageUpload'
import { useBuilderKeyboardShortcuts } from './useBuilderKeyboardShortcuts'
import { useBuilderPanels } from './useBuilderPanels'
import { useBuilderPreviewTest } from './useBuilderPreviewTest'
import { useBuilderRealtime, type BuilderRealtimeEvent, type BuilderAssetEvent } from './useBuilderRealtime'
import { useBuilderTemplateState } from './useBuilderTemplateState'
import { useNotifications } from './useNotifications'
import { useRevisionPreview } from './useRevisionPreview'
import { useTextEditorBridge } from './useTextEditorBridge'
import { clone, cloneNode, createBlock, createSection, findBlock, findColumn, findSection, normalizeColumnWidths, resizeSection, safeJson } from '../lib/builder'
import { EMPTY_COMPONENTS, EMPTY_MERGE_FIELDS, EMPTY_REVISIONS } from '../lib/builderConstants'
import { getErrorMessage, isConcurrencyError } from '../lib/errors'
import { analyzeReferenceDoctypeUsage, removeReferenceDependentContent, type PendingReferenceDoctypeChange } from '../lib/referenceDoctype'
import { collectBuilderSuggestions } from '../lib/suggestions'
import type { BlockType, BuilderBlock, BuilderDocument, BuilderSection, LayoutType, Selection } from '../types'
import type { RecoveryDraft } from '../components/BuilderDialogs'

const AUTOSAVE_IDLE_DELAY_MS = 4000
const AUTOSAVE_MAX_WAIT_MS = 30000

const getTemplateName = () => new URLSearchParams(window.location.search).get('template')?.trim() || ''

function setAtPath(target: Record<string, unknown>, path: string, value: unknown) {
  const keys = path.split('.')
  let current = target
  keys.slice(0, -1).forEach((key) => {
    if (!current[key] || typeof current[key] !== 'object') current[key] = {}
    current = current[key] as Record<string, unknown>
  })
  current[keys.at(-1)!] = value
}

export function useEmailBuilderController() {
  const templateName = useMemo(getTemplateName, [])
  const {
    modified,
    mode,
    requiresOverwrite,
    saving,
    saveConflict,
    recoveryDraft,
    patchTemplateState,
    setSaving,
    setSaveConflict,
    setRecoveryDraft,
  } = useBuilderTemplateState()
  const initialized = useRef(false)
  const historyRequested = useRef(false)
  const mounted = useRef(true)
  const {
    document,
    setDocument,
    documentRef,
    dirty,
    setDirty,
    savedSnapshot,
    stateBytes,
    commit,
    undo,
    redo,
    resetHistory,
    canUndo,
    canRedo,
  } = useBuilderDocumentState()
  const { notify } = useNotifications()
  const {
    modal,
    setModal,
    previewWidth,
    setPreviewWidth,
    previewFormat,
    setPreviewFormat,
    componentName,
    setComponentName,
    componentCategory,
    setComponentCategory,
    overwriteConfirmationOpen,
    setOverwriteConfirmationOpen,
    closeModal,
    openHistory,
    openShortcuts,
    openSuggestions,
    openTestDialog,
    closeOverwriteConfirmation,
  } = useBuilderDialogState()
  const resetPreviewFormat = useCallback(() => setPreviewFormat('html'), [setPreviewFormat])
  const {
    selection,
    setSelection,
    viewport,
    uiMode,
    workspaceWidth,
    exclusivePanels,
    setShellElement,
    sidebarOpen,
    inspectorOpen,
    sidebarTab,
    inspectorTab,
    showStructure,
    setSidebarTab,
    setInspectorTab,
    select,
    openTemplateInspector,
    requestAddBlock,
    editSection,
    toggleSidebar,
    toggleInspector,
    closePanels,
    closeInspector,
    toggleStructure,
    showDesktopViewport,
    showMobileViewport,
  } = useBuilderPanels()
  const { registerTextEditor, focusTextEditor, prepareMergeField, insertMergeField } = useTextEditorBridge()
  const sdk = useBuilderData(templateName, modal === 'history', document)
  const { preview, previewError, recipient, setRecipient, retryPreview, sendTestEmail } = useBuilderPreviewTest({ document, sdk, templateName, notify, setModal, resetPreviewFormat })
  const { revisionPreview, revisionPreviewError, openRevisionPreview, retryRevisionPreview } = useRevisionPreview({ sdk, templateName, setModal, setPreviewFormat })
  const mutateRevisions = sdk.revisions.mutate
  const draftKey = useMemo(() => `email-builder-react:${window.location.host}:${templateName}`, [templateName])
  const autosaveKey = useMemo(() => `email-builder-autosave:${window.location.host}:${templateName}`, [templateName])
  const autosaveFailureCount = useRef(0)
  const autosaveFirstDirtyAt = useRef<number | null>(null)
  const [autosaveEnabled, setAutosaveEnabled] = useState(() => {
    try { return localStorage.getItem(autosaveKey) !== 'off' } catch { return true }
  })
  const [visualEditingUnlocked, setVisualEditingUnlocked] = useState(false)
  const [pendingReferenceDoctypeChange, setPendingReferenceDoctypeChange] = useState<PendingReferenceDoctypeChange | null>(null)

  useEffect(() => () => { mounted.current = false }, [])

  const readOnlyReason = saveConflict ? 'conflict' : mode !== 'Visual' && !visualEditingUnlocked ? 'raw-html' : ''
  const isReadOnly = Boolean(readOnlyReason)

  const {
    aiEnabled,
    aiSamplePrompts,
    saveAiSamplePrompt,
    aiPrompt,
    aiProposal,
    aiError,
    aiGenerating,
    aiScope,
    chatTurns,
    setAiPrompt,
    openAiRewrite,
    closeAiRewrite,
    generateAiRewrite,
    acceptAiProposal,
    discardAiProposal,
    applyPastProposal,
    loadProposalPreview,
    clearAiProposal,
    handleAiStep,
    aiLiveStep,
    clearAiChat,
  } = useBuilderAi({ document, sdk, templateName, notify, setModal, commit, isReadOnly })

  useEffect(() => {
    try { localStorage.setItem(autosaveKey, autosaveEnabled ? 'on' : 'off') } catch { /* optional preference */ }
  }, [autosaveEnabled, autosaveKey])

  const toggleAutosave = useCallback(() => {
    if (isReadOnly) return
    setAutosaveEnabled((current) => {
      const next = !current
      if (next) autosaveFailureCount.current = 0
      return next
    })
  }, [isReadOnly])

  const requestVisualEditing = useCallback(() => {
    if (mode === 'Visual') return
    setModal('visual-unlock')
  }, [mode, setModal])

  const confirmVisualEditing = useCallback(() => {
    setVisualEditingUnlocked(true)
    setModal(null)
    notify('Visual editing unlocked. Review carefully before saving over the current HTML.', 'info')
  }, [notify, setModal])

  useEffect(() => {
    const loaded = sdk.load.data?.message
    if (!loaded || initialized.current) return
    const serverDocument: BuilderDocument = {
      schema: clone(loaded.schema),
      metadata: {
        subject: loaded.subject || '',
        preheader: loaded.preheader || '',
        reference_doctype: loaded.reference_doctype || '',
        preview_document: loaded.preview_document || '',
        validate_dynamic_fields: Boolean(loaded.validate_dynamic_fields ?? loaded.reference_doctype),
      },
    }
    let browserDraft: RecoveryDraft | null = null
    try {
      const draft = JSON.parse(sessionStorage.getItem(draftKey) || 'null') as { document?: BuilderDocument; modified?: string } | null
      const validDraft = draft?.document && Array.isArray(draft.document.schema?.sections) && draft.document.metadata
      if (validDraft && safeJson(draft.document) !== safeJson(serverDocument)) {
        if (draft.modified === loaded.modified) {
          browserDraft = { document: clone(draft.document!) }
        } else {
          sessionStorage.removeItem(draftKey)
          notify('A browser draft was based on an older server version and was not restored.', 'info')
        }
      }
    } catch { /* optional recovery */ }
    documentRef.current = serverDocument
    setDocument(serverDocument)
    patchTemplateState({
      modified: loaded.modified,
      mode: loaded.mode,
      requiresOverwrite: Boolean(loaded.requires_overwrite_confirmation),
      saveConflict: '',
      recoveryDraft: browserDraft,
    })
    setVisualEditingUnlocked(false)
    savedSnapshot.current = safeJson(serverDocument)
    resetHistory()
    setDirty(false)
    initialized.current = true
  }, [documentRef, draftKey, notify, patchTemplateState, resetHistory, savedSnapshot, sdk.load.data, setDirty, setDocument])

  useEffect(() => {
    if (!document) return
    if (!dirty) {
      if (!recoveryDraft) sessionStorage.removeItem(draftKey)
      return
    }
    const timer = window.setTimeout(() => {
      try { sessionStorage.setItem(draftKey, JSON.stringify({ document, modified, saved_at: Date.now() })) } catch { /* optional storage */ }
    }, 450)
    return () => window.clearTimeout(timer)
  }, [dirty, document, draftKey, modified, recoveryDraft])

  const discardRecoveryDraft = useCallback(() => {
    sessionStorage.removeItem(draftKey)
    setRecoveryDraft(null)
  }, [draftKey, setRecoveryDraft])

  const restoreRecoveryDraft = useCallback(() => {
    if (!recoveryDraft) return
    const recovered = clone(recoveryDraft.document)
    documentRef.current = recovered
    setDocument(recovered)
    resetHistory()
    setDirty(safeJson(recovered) !== savedSnapshot.current)
    setRecoveryDraft(null)
    notify('Browser draft restored', 'success')
  }, [documentRef, notify, recoveryDraft, resetHistory, savedSnapshot, setDirty, setDocument, setRecoveryDraft])

  const targetColumnId = useCallback((source: BuilderDocument) => {
    if (selection?.kind === 'column' && findColumn(source.schema, selection.id)) return selection.id
    if (selection?.kind === 'block') return findBlock(source.schema, selection.id)?.column.id
    if (selection?.kind === 'section') return findSection(source.schema, selection.id)?.section.columns[0]?.id
    return source.schema.sections.at(-1)?.columns[0]?.id
  }, [selection])

  const addSection = useCallback((layout: LayoutType = '1', index?: number) => {
    if (isReadOnly) return
    const section = createSection(layout)
    commit((next) => next.schema.sections.splice(index ?? next.schema.sections.length, 0, section))
    select({ kind: 'section', id: section.id })
    return section
  }, [commit, isReadOnly, select])

  const addBlock = useCallback((type: BlockType, explicitColumnId?: string, index?: number) => {
    if (isReadOnly) return
    const block = createBlock(type)
    commit((next) => {
      let columnId = explicitColumnId || targetColumnId(next)
      if (!columnId || !findColumn(next.schema, columnId)) {
        const section = createSection('1')
        next.schema.sections.push(section)
        columnId = section.columns[0].id
      }
      const column = findColumn(next.schema, columnId)?.column
      column?.blocks.splice(index ?? column.blocks.length, 0, block)
    })
    select({ kind: 'block', id: block.id })
  }, [commit, isReadOnly, select, targetColumnId])

  const updateContent = useCallback((blockId: string, key: string, value: unknown) => {
    if (isReadOnly) return
    commit((next) => {
      const block = findBlock(next.schema, blockId)?.block
      if (block) block.content[key] = value
    }, true, `content:${blockId}:${key}`)
  }, [commit, isReadOnly])

  const {
    pendingImageBlock,
    uploadProgress,
    chooseImage,
    uploadInspectorImage,
    imagePickerBlock,
    imagePickerScope,
    imageSearch,
    imageLibrary,
    imageLibraryLoading,
    imageLibraryLoadingMore,
    imageLibraryHasMore,
    imageLibraryError,
    optimizeImages,
    maxImageWidth,
    setOptimizeImages,
    setMaxImageWidth,
    closeImagePicker,
    changeImageScope,
    changeImageSearch,
    refreshImageLibrary,
    loadMoreImages,
    selectExistingImage,
    uploadImageFromPicker,
  } = useBuilderImageUpload({ fileUpload: sdk.fileUpload, listImages: sdk.listImages, attachImage: sdk.attachImage, templateName, notify, updateContent })

  const updateNode = useCallback((selected: NonNullable<Selection>, path: string, value: unknown) => {
    if (isReadOnly) return
    commit((next) => {
      const node = selected.kind === 'block' ? findBlock(next.schema, selected.id)?.block : selected.kind === 'column' ? findColumn(next.schema, selected.id)?.column : findSection(next.schema, selected.id)?.section
      if (node) setAtPath(node as unknown as Record<string, unknown>, path, value)
    }, true, `node:${selected.kind}:${selected.id}:${path}`)
  }, [commit, isReadOnly])

  const applyReferenceDoctypeChange = useCallback((nextValue: string, removeDependentContent: boolean) => {
    if (isReadOnly) return
    commit((next) => {
      if (removeDependentContent) {
        const cleaned = removeReferenceDependentContent(next)
        next.schema = cleaned.schema
        next.metadata = cleaned.metadata
      }
      next.metadata.reference_doctype = nextValue
      next.metadata.preview_document = ''
      next.metadata.validate_dynamic_fields = removeDependentContent ? Boolean(nextValue) : false
    }, true, 'metadata:reference_doctype')
    setPendingReferenceDoctypeChange(null)
    setModal(null)
  }, [commit, isReadOnly, setModal])

  const cancelReferenceDoctypeChange = useCallback(() => {
    setPendingReferenceDoctypeChange(null)
    setModal(null)
  }, [setModal])

  const keepReferenceDependentContent = useCallback(() => {
    if (!pendingReferenceDoctypeChange) return
    applyReferenceDoctypeChange(pendingReferenceDoctypeChange.nextValue, false)
    notify('Reference DocType changed. Dynamic fields were kept and validation was turned off.', 'info')
  }, [applyReferenceDoctypeChange, notify, pendingReferenceDoctypeChange])

  const removeReferenceDependentFields = useCallback(() => {
    if (!pendingReferenceDoctypeChange) return
    applyReferenceDoctypeChange(pendingReferenceDoctypeChange.nextValue, true)
    notify('Reference DocType changed. Dynamic fields and record conditions were removed.', 'success')
  }, [applyReferenceDoctypeChange, notify, pendingReferenceDoctypeChange])

  const updateMetadata = useCallback((key: keyof BuilderDocument['metadata'], value: BuilderDocument['metadata'][keyof BuilderDocument['metadata']]) => {
    if (isReadOnly) return
    if (key === 'reference_doctype') {
      if (!document) return
      const nextValue = String(value || '').trim()
      const previousValue = document.metadata.reference_doctype || ''
      if (nextValue === previousValue) return

      const usage = analyzeReferenceDoctypeUsage(document)
      if (usage.hasReferenceDependentContent) {
        setPendingReferenceDoctypeChange({ ...usage, previousValue, nextValue })
        setModal('reference-doctype-change')
        return
      }

      commit((next) => {
        next.metadata.reference_doctype = nextValue
        next.metadata.preview_document = ''
        if (!nextValue) next.metadata.validate_dynamic_fields = false
      }, true, 'metadata:reference_doctype')
      return
    }
    commit((next) => { Object.assign(next.metadata, { [key]: value }) }, true, `metadata:${key}`)
  }, [commit, document, isReadOnly, setModal])

  const updateSetting = useCallback((key: keyof BuilderDocument['schema']['settings'], value: string | number) => {
    if (isReadOnly) return
    commit((next) => { Object.assign(next.schema.settings, { [key]: value }) }, true, `setting:${key}`)
  }, [commit, isReadOnly])

  const duplicateNode = useCallback((selected: NonNullable<Selection>) => {
    if (isReadOnly) return
    commit((next) => {
      if (selected.kind === 'section') {
        const location = findSection(next.schema, selected.id)
        if (location) next.schema.sections.splice(location.sectionIndex + 1, 0, cloneNode(location.section))
      } else if (selected.kind === 'block') {
        const location = findBlock(next.schema, selected.id)
        if (location) location.column.blocks.splice(location.blockIndex + 1, 0, cloneNode(location.block))
      }
    })
  }, [commit, isReadOnly])

  const deleteNode = useCallback((selected: NonNullable<Selection>) => {
    if (isReadOnly) return
    if (!document || selected.kind === 'column') return
    let nextSelection: Selection = null
    if (selected.kind === 'block') {
      const location = findBlock(document.schema, selected.id)
      const sibling = location && (location.column.blocks[location.blockIndex + 1] || location.column.blocks[location.blockIndex - 1])
      nextSelection = sibling ? { kind: 'block', id: sibling.id } : location ? { kind: 'column', id: location.column.id } : null
    } else {
      const location = findSection(document.schema, selected.id)
      const sibling = location && (document.schema.sections[location.sectionIndex + 1] || document.schema.sections[location.sectionIndex - 1])
      nextSelection = sibling ? { kind: 'section', id: sibling.id } : null
    }
    commit((next) => {
      if (selected.kind === 'section') {
        const location = findSection(next.schema, selected.id)
        if (location) next.schema.sections.splice(location.sectionIndex, 1)
      } else if (selected.kind === 'block') {
        const location = findBlock(next.schema, selected.id)
        if (location) location.column.blocks.splice(location.blockIndex, 1)
      }
    })
    setSelection(nextSelection)
    notify((selected.kind === 'section' ? 'Row' : 'Content') + ' deleted. Use Ctrl+Z to restore it.', 'info')
  }, [commit, document, isReadOnly, notify, setSelection])

  const changeLayout = useCallback((sectionId: string, layout: LayoutType) => {
    if (isReadOnly) return
    commit((next) => {
      const section = findSection(next.schema, sectionId)?.section
      if (section) resizeSection(section, layout)
    })
  }, [commit, isReadOnly])

  const changeColumnWidths = useCallback((sectionId: string, widths: number[]) => {
    if (isReadOnly) return
    commit((next) => {
      const section = findSection(next.schema, sectionId)?.section
      if (section) section.column_widths = normalizeColumnWidths(widths, section.columns.length)
    })
  }, [commit, isReadOnly])

  const resolveTarget = useCallback((source: BuilderDocument, overData: Record<string, unknown> | undefined) => {
    if (overData?.kind === 'column') return { columnId: String(overData.columnId), index: findColumn(source.schema, String(overData.columnId))?.column.blocks.length ?? 0 }
    if (overData?.kind === 'block') {
      const target = findBlock(source.schema, String(overData.blockId))
      if (target) return { columnId: target.column.id, index: target.blockIndex }
    }
    if (overData?.kind === 'section') {
      const section = findSection(source.schema, String(overData.sectionId))?.section
      if (section?.columns[0]) return { columnId: section.columns[0].id, index: section.columns[0].blocks.length }
    }
    const columnId = targetColumnId(source)
    return columnId ? { columnId, index: findColumn(source.schema, columnId)?.column.blocks.length ?? 0 } : null
  }, [targetColumnId])

  const { activeDrag, setActiveDrag, sensors, onDragStart, onDragEnd } = useBuilderDnd({ document, commit, addBlock, addSection, resolveTarget, readOnly: isReadOnly })

  const handleConcurrentEdit = useCallback((error: unknown) => {
    if (!isConcurrencyError(error)) return false
    const message = 'A newer saved version is available. Your local edits are still protected in this browser, but cannot overwrite the newer template.'
    setSaveConflict(message)
    setModal('conflict')
    notify({ title: 'Save blocked to protect newer work', message }, 'warning', { duration: 10000 })
    return true
  }, [notify, setModal, setSaveConflict])

  const reloadLatestTemplate = useCallback(async () => {
    sessionStorage.removeItem(draftKey)
    setRecoveryDraft(null)
    setSelection(null)
    setSaveConflict('')
    setVisualEditingUnlocked(false)
    setModal(null)
    initialized.current = false
    documentRef.current = null
    setDocument(null)
    try {
      await sdk.load.mutate()
    } catch (error) {
      initialized.current = true
      setSaveConflict('The latest saved template could not be loaded. Retry before saving local work.')
      notify(getErrorMessage(error, 'The latest saved template could not be loaded.'), 'error')
    }
  }, [documentRef, draftKey, notify, sdk.load, setDocument, setModal, setRecoveryDraft, setSaveConflict, setSelection])

  const handleRemoteSave = useCallback((event: BuilderRealtimeEvent) => {
    if (!event.modified || event.modified === modified) return
    const actor = event.actor ? ` by ${event.actor}` : ''
    if (dirty || saving) {
      const message = `This template was saved${actor}. Reload latest before saving local changes.`
      setSaveConflict(message)
      notify({ title: 'Newer saved version available', message }, 'warning', { duration: 12000 })
      return
    }
    notify(`Template updated${actor}. Reloading latest version…`, 'info')
    void reloadLatestTemplate()
  }, [dirty, modified, notify, reloadLatestTemplate, saving, setSaveConflict])

  const handleRemoteRevision = useCallback((_event: BuilderRealtimeEvent) => {
    if (modal === 'history') void mutateRevisions()
  }, [modal, mutateRevisions])

  const handleRemoteAssets = useCallback((_event: BuilderAssetEvent) => {
    if (imagePickerBlock) void refreshImageLibrary(imagePickerScope, imageSearch)
  }, [imagePickerBlock, imagePickerScope, imageSearch, refreshImageLibrary])

  const realtime = useBuilderRealtime({
    templateName,
    enabled: Boolean(templateName),
    onRemoteSave: handleRemoteSave,
    onRevisionCreated: handleRemoteRevision,
    onAssetsChanged: handleRemoteAssets,
    onAiStep: handleAiStep,
  })

  const saveDocument = useCallback(async (silent = false, allowOverwrite = false) => {
    if (!document || saving || !dirty) return
    if (saveConflict) {
      if (!silent) setModal('conflict')
      return
    }
    if (requiresOverwrite && !allowOverwrite) {
      if (!silent) setOverwriteConfirmationOpen(true)
      return
    }
    setSaving(true)
    const submittedSnapshot = safeJson(document)
    try {
      const response = await sdk.save.call({
        template_name: templateName,
        expected_modified: modified,
        schema: JSON.stringify(document.schema),
        metadata: JSON.stringify(document.metadata),
        allow_overwrite_html: allowOverwrite ? 1 : 0,
        client_id: realtime.clientId,
      })
      if (!mounted.current) return
      autosaveFailureCount.current = 0
      patchTemplateState({ saveConflict: '', modified: response.message.modified, mode: 'Visual', requiresOverwrite: false })
      const currentSnapshot = documentRef.current ? safeJson(documentRef.current) : ''
      const hasNoNewerChanges = currentSnapshot === submittedSnapshot
      const serverDocument: BuilderDocument = { schema: clone(response.message.schema), metadata: clone(response.message.metadata) }
      const serverSnapshot = safeJson(serverDocument)
      savedSnapshot.current = serverSnapshot
      if (hasNoNewerChanges) {
        documentRef.current = serverDocument
        setDocument(serverDocument)
      }
      setDirty(hasNoNewerChanges ? false : currentSnapshot !== serverSnapshot)
      if (hasNoNewerChanges) sessionStorage.removeItem(draftKey)
      if (!silent) notify(hasNoNewerChanges ? 'Email template saved' : 'Saved. Newer local changes are still pending.', 'success')
      const issues = response.message.issues || []
      const messages = issues.length ? issues.map((issue) => issue.message) : response.message.warnings || []
      if (!silent) messages.slice(0, 3).forEach((message) => notify(message, 'info'))
    } catch (error) {
      if (!mounted.current) return
      const handledConflict = handleConcurrentEdit(error)
      if (silent) {
        if (!handledConflict) {
          autosaveFailureCount.current += 1
          const errorMessage = getErrorMessage(error, 'The template could not be autosaved. Your browser draft is safe.')
          if (autosaveFailureCount.current >= 3) {
            autosaveFailureCount.current = 0
            setAutosaveEnabled(false)
            notify({
              title: 'Autosave turned off after 3 failed attempts',
              message: `${errorMessage} Autosave is now off. Your browser draft is still safe; save manually after fixing the issue.`,
            }, 'error', { duration: 14000 })
          } else {
            notify({
              title: `Autosave failed (${autosaveFailureCount.current}/3)`,
              message: errorMessage,
            }, 'warning', { duration: 8000 })
          }
        }
      } else if (!handledConflict) {
        notify(getErrorMessage(error, 'The template could not be saved. Your browser draft is safe.'), 'error')
      }
    } finally {
      if (mounted.current) setSaving(false)
    }
  }, [dirty, document, documentRef, draftKey, handleConcurrentEdit, modified, notify, patchTemplateState, realtime.clientId, requiresOverwrite, savedSnapshot, saveConflict, saving, sdk.save, setDirty, setDocument, setModal, setOverwriteConfirmationOpen, setSaving, templateName])

  useEffect(() => {
    if (!dirty) {
      autosaveFirstDirtyAt.current = null
      return
    }
    if (!autosaveEnabled || requiresOverwrite || saveConflict || mode !== 'Visual') return
    const now = Date.now()
    if (!autosaveFirstDirtyAt.current) autosaveFirstDirtyAt.current = now
    const elapsed = now - autosaveFirstDirtyAt.current
    const delay = elapsed >= AUTOSAVE_MAX_WAIT_MS ? 0 : Math.min(AUTOSAVE_IDLE_DELAY_MS, AUTOSAVE_MAX_WAIT_MS - elapsed)
    const timer = window.setTimeout(() => { void saveDocument(true) }, delay)
    return () => window.clearTimeout(timer)
  }, [autosaveEnabled, dirty, document, mode, requiresOverwrite, saveConflict, saveDocument])

  useBuilderKeyboardShortcuts({ dirty, selection, undo, redo, deleteNode, readOnly: isReadOnly })


  const saveComponent = useCallback(async () => {
    if (isReadOnly) return
    if (!document || !selection || selection.kind === 'column' || !componentName.trim()) return
    const node = selection.kind === 'block' ? findBlock(document.schema, selection.id)?.block : findSection(document.schema, selection.id)?.section
    if (!node) return
    try {
      const response = await sdk.saveComponent.call({ component: JSON.stringify({ component_name: componentName.trim(), category: componentCategory, component_type: selection.kind === 'section' ? 'Section' : 'Block', definition: node }) })
      await sdk.components.mutate()
      // Stamp the row so it is recognised as a saved component and offers per-row AI editing.
      if (selection.kind === 'section') {
        const savedName = response.message?.name || componentName.trim()
        commit((next) => {
          const found = findSection(next.schema, selection.id)
          if (found) found.section.saved_component = savedName
        }, false)
      }
      setModal(null)
      setComponentName('')
      notify('Saved to reusable content', 'success')
    } catch (error) { notify(getErrorMessage(error, 'Reusable content could not be saved.'), 'error') }
  }, [commit, componentCategory, componentName, document, isReadOnly, notify, sdk.components, sdk.saveComponent, selection, setComponentName, setModal])

  const requestSaveComponent = useCallback((selected: NonNullable<Selection>) => {
    if (isReadOnly) return
    if (!document) return
    setSelection(selected)
    setComponentName('')
    setComponentCategory(selected.kind === 'block' && findBlock(document.schema, selected.id)?.block.type === 'button' ? 'CTA' : 'Content')
    setModal('save-component')
  }, [document, isReadOnly, setComponentCategory, setComponentName, setModal, setSelection])

  const insertSavedComponent = useCallback(async (componentNameToInsert: string) => {
    if (isReadOnly) return
    if (!componentNameToInsert) return
    try {
      const response = await sdk.loadComponent.call({ component_name: componentNameToInsert })
      const doc = response.message
      const definition = JSON.parse(doc.definition_json) as { definition?: BuilderBlock | BuilderSection } & (BuilderBlock | BuilderSection)
      const source = definition.definition || definition
      const kind = String(doc.component_type).toLowerCase() === 'section' ? 'section' : 'block'
      const copy = cloneNode(source as BuilderBlock | BuilderSection)
      if (kind === 'section') (copy as BuilderSection).saved_component = componentNameToInsert
      commit((next) => {
        if (kind === 'section') next.schema.sections.push(copy as BuilderSection)
        else {
          let columnId = targetColumnId(next)
          if (!columnId) { const section = createSection('1'); next.schema.sections.push(section); columnId = section.columns[0].id }
          findColumn(next.schema, columnId)?.column.blocks.push(copy as BuilderBlock)
        }
      })
      select({ kind: kind as 'block' | 'section', id: copy.id })
      notify(`Inserted ${doc.component_name || doc.name}`, 'success')
    } catch (error) {
      notify(getErrorMessage(error, 'Saved content could not be inserted.'), 'error')
    }
  }, [commit, isReadOnly, notify, sdk.loadComponent, select, targetColumnId])

  useEffect(() => {
    if (modal === 'history' && !historyRequested.current) {
      historyRequested.current = true
      void mutateRevisions()
    } else if (modal !== 'history') historyRequested.current = false
  }, [modal, mutateRevisions])


  const restoreRevision = useCallback(async (name: string) => {
    if (isReadOnly) {
      setModal(saveConflict ? 'conflict' : 'visual-unlock')
      return
    }
    try {
      await sdk.restoreRevision.call({ template_name: templateName, revision_name: name, expected_modified: modified, client_id: realtime.clientId })
      setModal(null)
      initialized.current = false
      sessionStorage.removeItem(draftKey)
      documentRef.current = null
      setDocument(null)
      await sdk.load.mutate()
      notify('Revision restored', 'success')
    } catch (error) {
      if (!handleConcurrentEdit(error)) notify(getErrorMessage(error, 'Revision could not be restored.'), 'error')
    }
  }, [documentRef, draftKey, handleConcurrentEdit, isReadOnly, modified, notify, realtime.clientId, saveConflict, sdk.load, sdk.restoreRevision, setDocument, setModal, templateName])

  const components = sdk.components.data?.message ?? EMPTY_COMPONENTS
  const mergeFields = sdk.mergeFields.data?.message ?? EMPTY_MERGE_FIELDS
  const revisions = sdk.revisions.data?.message ?? EMPTY_REVISIONS
  const suggestions = useMemo(() => document ? collectBuilderSuggestions(document, mergeFields, sdk.mergeFields.isLoading, sdk.mergeFields.error) : [], [document, mergeFields, sdk.mergeFields.error, sdk.mergeFields.isLoading])
  const appClassName = `builder-app mode-${uiMode}${sidebarOpen ? ' has-sidebar' : ''}${inspectorOpen ? ' has-inspector' : ''}${exclusivePanels ? ' has-exclusive-panels' : ''}${isReadOnly ? ' is-read-only' : ''}${readOnlyReason ? ` read-only-${readOnlyReason}` : ''}`

  const addDefaultSection = useCallback(() => { addSection('1') }, [addSection])
  const addSidebarBlock = useCallback((type: BlockType) => { addBlock(type) }, [addBlock])
  const addSidebarSection = useCallback((layout: LayoutType) => { addSection(layout) }, [addSection])
  const retryMergeFields = useCallback(() => { void sdk.mergeFields.mutate() }, [sdk.mergeFields])
  const saveTemplate = useCallback(() => { void saveDocument(false) }, [saveDocument])
  const confirmOverwrite = useCallback(() => { setOverwriteConfirmationOpen(false); void saveDocument(false, true) }, [saveDocument, setOverwriteConfirmationOpen])
  const saveReusableContent = useCallback(() => { void saveComponent() }, [saveComponent])
  const retryRevisions = useCallback(() => { void mutateRevisions() }, [mutateRevisions])
  const restoreRevisionByName = useCallback((revisionName: string) => { void restoreRevision(revisionName) }, [restoreRevision])
  const previewRevisionByName = useCallback((revisionName: string) => { void openRevisionPreview(revisionName) }, [openRevisionPreview])
  const backToHistory = useCallback(() => { setModal('history') }, [setModal])
  const reloadLatest = useCallback(() => { void reloadLatestTemplate() }, [reloadLatestTemplate])


  return {
    templateName,
    sdk,
    realtime,
    document,
    mode,
    isReadOnly,
    readOnlyReason,
    visualEditingUnlocked,
    requestVisualEditing,
    confirmVisualEditing,
    dirty,
    saving,
    saveConflict,
    canUndo,
    canRedo,
    undo,
    redo,
    openHistory,
    openShortcuts,
    openSuggestions,
    retryPreview,
    openTestDialog,
    saveTemplate,
    autosaveEnabled,
    toggleAutosave,
    pendingReferenceDoctypeChange,
    cancelReferenceDoctypeChange,
    keepReferenceDependentContent,
    removeReferenceDependentFields,
    appClassName,
    setShellElement,
    sidebarOpen,
    inspectorOpen,
    sidebarTab,
    inspectorTab,
    components,
    viewport,
    uiMode,
    workspaceWidth,
    exclusivePanels,
    showStructure,
    mergeFields,
    selection,
    setSidebarTab,
    setInspectorTab,
    addSidebarBlock,
    addSidebarSection,
    select,
    deleteNode,
    insertSavedComponent,
    closePanels,
    toggleSidebar,
    toggleInspector,
    toggleStructure,
    showDesktopViewport,
    showMobileViewport,
    requestAddBlock,
    addDefaultSection,
    updateContent,
    changeColumnWidths,
    editSection,
    duplicateNode,
    requestSaveComponent,
    chooseImage,
    openTemplateInspector,
    registerTextEditor,
    closeInspector,
    updateMetadata,
    updateSetting,
    updateNode,
    changeLayout,
    uploadInspectorImage,
    imagePickerBlock,
    imagePickerScope,
    imageSearch,
    imageLibrary,
    imageLibraryLoading,
    imageLibraryLoadingMore,
    imageLibraryHasMore,
    imageLibraryError,
    optimizeImages,
    maxImageWidth,
    setOptimizeImages,
    setMaxImageWidth,
    closeImagePicker,
    changeImageScope,
    changeImageSearch,
    refreshImageLibrary,
    loadMoreImages,
    selectExistingImage,
    uploadImageFromPicker,
    retryMergeFields,
    focusTextEditor,
    prepareMergeField,
    insertMergeField,
    stateBytes,
    activeDrag,
    pendingImageBlock,
    uploadProgress,
    setActiveDrag,
    modal,
    preview,
    previewError,
    revisionPreview,
    revisionPreviewError,
    previewFormat,
    previewWidth,
    recipient,
    componentName,
    componentCategory,
    revisions,
    suggestions,
    recoveryDraft,
    overwriteConfirmationOpen,
    closeModal,
    setPreviewFormat,
    setPreviewWidth,
    setRecipient,
    setComponentName,
    setComponentCategory,
    sendTestEmail,
    saveReusableContent,
    retryRevisions,
    restoreRevisionByName,
    previewRevisionByName,
    backToHistory,
    retryRevisionPreview,
    discardRecoveryDraft,
    restoreRecoveryDraft,
    closeOverwriteConfirmation,
    confirmOverwrite,
    reloadLatest,
    sensors,
    onDragStart,
    onDragEnd,
    aiEnabled,
    aiSamplePrompts,
    saveAiSamplePrompt,
    aiPrompt,
    aiProposal,
    aiError,
    aiGenerating,
    aiScope,
    chatTurns,
    setAiPrompt,
    openAiRewrite,
    closeAiRewrite,
    generateAiRewrite,
    acceptAiProposal,
    discardAiProposal,
    applyPastProposal,
    loadProposalPreview,
    clearAiProposal,
    aiLiveStep,
    clearAiChat,
  }
}
