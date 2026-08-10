import { memo, useCallback, useEffect, useLayoutEffect, useMemo, useReducer, useRef, useState, type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent as ReactPointerEvent } from 'react'
import { useDroppable, type DraggableAttributes, type DraggableSyntheticListeners } from '@dnd-kit/core'
import { SortableContext, useSortable, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { AlignCenter, AlignLeft, AlignRight, Bold, Bookmark, Braces, Copy, EyeOff, GripVertical, ImagePlus, Italic, Link, List, ListOrdered, Pencil, Plus, RemoveFormatting, Sparkles, Trash2, Underline } from 'lucide-react'

import { BLOCKS, findBlock, LAYOUTS, nodeCss, normalizeColumnWidths, normalizeLength } from '../lib/builder'
import { insertLineBreakAtSelection, insertTextAtSelection, runLegacyEditorCommand } from '../lib/editorDom'
import { isValidMergeToken } from '../lib/tokens'
import type { BuilderBlock, BuilderColumn, BuilderMetadata, BuilderSchema, BuilderSection, MergeField, Selection, Viewport } from '../types'
import { PersonalizationDialog } from './PersonalizationPicker'

export type TextEditorController = {
  blockId: string
  focus: () => void
  captureSelection: () => void
  insertDynamicField: (token: string) => boolean
}

type CanvasProps = {
  schema: BuilderSchema
  metadata: BuilderMetadata
  selection: Selection
  viewport: Viewport
  showStructure: boolean
  onSelect: (selection: Selection) => void
  onAddBlock: (columnId: string) => void
  onAddSection: () => void
  onUpdateContent: (blockId: string, key: string, value: unknown) => void
  onUpdateNode: (selection: NonNullable<Selection>, path: string, value: unknown) => void
  onResizeColumns: (sectionId: string, widths: number[]) => void
  onEditSection: (sectionId: string, tab: 'content' | 'visibility') => void
  onAiRewriteSection?: (sectionId: string) => void
  aiEnabled?: boolean
  onDuplicate: (selection: NonNullable<Selection>) => void
  onDelete: (selection: NonNullable<Selection>) => void
  onSaveComponent: (selection: NonNullable<Selection>) => void
  onPickImage: (blockId: string) => void
  onEditTemplate: () => void
  mergeFields: MergeField[]
  mergeFieldsLoading: boolean
  mergeFieldsError: unknown
  onRetryMergeFields: () => void
  onTextEditorController: (controller: TextEditorController | null, blockId?: string) => void
  readOnly?: boolean
}

function safeRichHtml(value: unknown) {
  const source = String(value ?? '<p>Write your message here</p>')
  const document = new DOMParser().parseFromString(source, 'text/html')
  document.querySelectorAll('script,style,iframe,object,embed,form').forEach((node) => node.remove())
  document.querySelectorAll('*').forEach((node) => {
    Array.from(node.attributes).forEach((attribute) => {
      if (attribute.name.toLowerCase().startsWith('on')) node.removeAttribute(attribute.name)
      if (['href', 'src'].includes(attribute.name.toLowerCase()) && /^\s*(?:javascript|data):/i.test(attribute.value)) node.removeAttribute(attribute.name)
    })
  })
  const isEditorBlank = (node: Element) => {
    if (!['P', 'DIV'].includes(node.tagName) || node.attributes.length || node.textContent?.trim()) return false
    return Array.from(node.childNodes).every((child) => child.nodeType === Node.ELEMENT_NODE && (child as Element).tagName === 'BR')
  }
  Array.from(document.body.children).filter(isEditorBlank).forEach((node) => node.remove())
  return document.body.innerHTML
}

function stopShortcutPropagation(event: KeyboardEvent<HTMLElement>) {
  if (event.key === 'Delete' || event.key === 'Backspace') event.stopPropagation()
}

function insertCompactLineBreak(event: KeyboardEvent<HTMLDivElement>) {
  stopShortcutPropagation(event)
  if (event.key !== 'Enter') return
  event.preventDefault()
  insertLineBreakAtSelection()
}

function RichTextEditor({ block, onUpdate, onRegisterController, readOnly = false }: { block: BuilderBlock; onUpdate: CanvasProps['onUpdateContent']; onRegisterController: CanvasProps['onTextEditorController']; readOnly?: boolean }) {
  const editorRef = useRef<HTMLDivElement>(null)
  const savedSelection = useRef<TextSelectionBookmark | null>(null)
  const externalHtml = useMemo(() => safeRichHtml(block.content.html), [block.content.html])

  useLayoutEffect(() => {
    const editor = editorRef.current
    if (!editor || document.activeElement === editor || editor.innerHTML === externalHtml) return
    editor.innerHTML = externalHtml
  }, [block.id, externalHtml])

  const captureSelection = useCallback(() => {
    const editor = editorRef.current
    const selection = document.getSelection()
    if (!editor || !selection?.rangeCount || !selection.anchorNode || !editor.contains(selection.anchorNode)) return
    const bookmark = createSelectionBookmark(editor, selection.getRangeAt(0))
    if (bookmark) savedSelection.current = bookmark
  }, [])

  const restoreSelection = useCallback((editor: HTMLElement) => {
    const selection = document.getSelection()
    if (!selection) return false
    const range = restoreBookmark(editor, savedSelection.current)
    const fallback = document.createRange()
    if (!range) {
      fallback.selectNodeContents(editor)
      fallback.collapse(false)
    }
    try {
      selection.removeAllRanges()
      selection.addRange(range || fallback)
      return true
    } catch {
      return false
    }
  }, [])

  const commit = useCallback(() => {
    const editor = editorRef.current
    if (!editor) return
    const value = safeRichHtml(editor.innerHTML)
    if (editor.innerHTML !== value) editor.innerHTML = value
    if (value !== String(block.content.html || '')) onUpdate(block.id, 'html', value)
  }, [block.content.html, block.id, onUpdate])

  const insertDynamicField = useCallback((token: string) => {
    if (readOnly || !isValidMergeToken(token)) return false
    const editor = editorRef.current
    if (!editor) return false
    editor.focus({ preventScroll: true })
    restoreSelection(editor)
    if (!insertTextAtSelection(token)) return false
    captureSelection()
    commit()
    return true
  }, [captureSelection, commit, readOnly, restoreSelection])

  const focus = useCallback(() => {
    editorRef.current?.focus({ preventScroll: false })
  }, [])

  useEffect(() => {
    onRegisterController({ blockId: block.id, focus, captureSelection, insertDynamicField })
    return () => onRegisterController(null, block.id)
  }, [block.id, captureSelection, focus, insertDynamicField, onRegisterController])

  return <div ref={editorRef} className="rich-text" contentEditable={!readOnly} suppressContentEditableWarning onKeyDown={readOnly ? undefined : insertCompactLineBreak} onKeyUp={readOnly ? undefined : captureSelection} onMouseUp={readOnly ? undefined : captureSelection} onInput={readOnly ? undefined : captureSelection} onBlur={readOnly ? undefined : commit} />
}

function PlainTextEditor({ block, className, style, fallback, onUpdate, onFocus, readOnly = false }: {
  block: BuilderBlock
  className: string
  style?: CSSProperties
  fallback: string
  onUpdate: CanvasProps['onUpdateContent']
  onFocus?: () => void
  readOnly?: boolean
  onSelectBlock?: () => void
}) {
  const editorRef = useRef<HTMLSpanElement>(null)
  const externalText = String(block.content.text || fallback)

  useLayoutEffect(() => {
    const editor = editorRef.current
    if (!editor || document.activeElement === editor || editor.textContent === externalText) return
    editor.textContent = externalText
  }, [block.id, externalText])

  const commit = () => {
    const editor = editorRef.current
    if (!editor) return
    const value = editor.textContent || ''
    if (value !== String(block.content.text || '')) onUpdate(block.id, 'text', value)
  }

  return <span ref={editorRef} className={className} style={style} contentEditable={!readOnly} suppressContentEditableWarning onFocus={onFocus} onKeyDown={readOnly ? undefined : stopShortcutPropagation} onBlur={readOnly ? undefined : commit} />
}

type TextFormatState = {
  block: 'p' | 'h1' | 'h2' | 'h3'
  font: string
  size: string
  color: string
  bold: boolean
  italic: boolean
  underline: boolean
  align: 'left' | 'center' | 'right'
  unorderedList: boolean
  orderedList: boolean
}

const DEFAULT_TEXT_FORMAT: TextFormatState = {
  block: 'p', font: 'Arial', size: '3', color: '#1f2937', bold: false, italic: false, underline: false,
  align: 'left', unorderedList: false, orderedList: false,
}

function normalizeCommandColor(value: string) {
  const source = String(value || '').trim()
  if (/^#[0-9a-f]{6}$/i.test(source)) return source.toLowerCase()
  const rgb = source.match(/^rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)$/i)
  return rgb ? `#${rgb.slice(1).map((part) => Number(part).toString(16).padStart(2, '0')).join('')}` : DEFAULT_TEXT_FORMAT.color
}

function normalizeBlockCommand(value: string): TextFormatState['block'] {
  const match = String(value || '').toLowerCase().match(/(?:p|h1|h2|h3)/)
  return (match?.[0] as TextFormatState['block']) || 'p'
}

function normalizeFontCommand(value: string) {
  const font = String(value || '').replace(/["']/g, '').split(',')[0].trim()
  return ['Arial', 'Helvetica', 'Georgia', 'Tahoma', 'Verdana'].includes(font) ? font : DEFAULT_TEXT_FORMAT.font
}

type TextSelectionBookmark = {
  range: Range
  start: number
  end: number
}

function isRangeInside(editor: HTMLElement, range: Range) {
  return editor.contains(range.startContainer) && editor.contains(range.endContainer)
}

function textOffset(editor: HTMLElement, node: Node, offset: number) {
  const range = document.createRange()
  range.selectNodeContents(editor)
  range.setEnd(node, offset)
  return range.toString().length
}

function createSelectionBookmark(editor: HTMLElement, range: Range): TextSelectionBookmark | null {
  if (!isRangeInside(editor, range)) return null
  try {
    return {
      range: range.cloneRange(),
      start: textOffset(editor, range.startContainer, range.startOffset),
      end: textOffset(editor, range.endContainer, range.endOffset),
    }
  } catch {
    return null
  }
}

function textPoint(editor: HTMLElement, requestedOffset: number) {
  const walker = document.createTreeWalker(editor, NodeFilter.SHOW_TEXT)
  let remaining = Math.max(0, requestedOffset)
  let current = walker.nextNode() as Text | null
  let last: Text | null = null
  while (current) {
    if (remaining <= current.data.length) return { node: current, offset: remaining }
    remaining -= current.data.length
    last = current
    current = walker.nextNode() as Text | null
  }
  return last ? { node: last, offset: last.data.length } : { node: editor, offset: editor.childNodes.length }
}

function restoreBookmark(editor: HTMLElement, bookmark: TextSelectionBookmark | null) {
  if (!bookmark) return null
  if (isRangeInside(editor, bookmark.range)) return bookmark.range.cloneRange()
  try {
    const start = textPoint(editor, bookmark.start)
    const end = textPoint(editor, Math.max(bookmark.start, bookmark.end))
    const range = document.createRange()
    range.setStart(start.node, start.offset)
    range.setEnd(end.node, end.offset)
    return range
  } catch {
    return null
  }
}

function isSameTextFormat(left: TextFormatState, right: TextFormatState) {
  return left.block === right.block && left.font === right.font && left.size === right.size && left.color === right.color
    && left.bold === right.bold && left.italic === right.italic && left.underline === right.underline
    && left.align === right.align && left.unorderedList === right.unorderedList && left.orderedList === right.orderedList
}

type RichTextToolbarState = {
  linkOpen: boolean
  linkValue: string
  format: TextFormatState
}

type RichTextToolbarAction =
  | { type: 'reset-format' }
  | { type: 'sync-format'; format: TextFormatState }
  | { type: 'open-link-editor' }
  | { type: 'close-link-editor' }
  | { type: 'set-link-value'; value: string }

const INITIAL_RICH_TEXT_TOOLBAR_STATE: RichTextToolbarState = {
  linkOpen: false,
  linkValue: 'https://',
  format: DEFAULT_TEXT_FORMAT,
}

function richTextToolbarReducer(state: RichTextToolbarState, action: RichTextToolbarAction): RichTextToolbarState {
  if (action.type === 'reset-format') {
    return isSameTextFormat(state.format, DEFAULT_TEXT_FORMAT) ? state : { ...state, format: DEFAULT_TEXT_FORMAT }
  }
  if (action.type === 'sync-format') {
    return isSameTextFormat(state.format, action.format) ? state : { ...state, format: action.format }
  }
  if (action.type === 'open-link-editor') return { ...state, linkOpen: true, linkValue: 'https://' }
  if (action.type === 'close-link-editor') return state.linkOpen ? { ...state, linkOpen: false } : state
  return state.linkValue === action.value ? state : { ...state, linkValue: action.value }
}

type ColumnResizeState = {
  previewWidths: number[]
  resizingIndex: number | null
}

type ColumnResizeAction =
  | { type: 'sync-widths'; widths: number[] }
  | { type: 'start'; index: number }
  | { type: 'preview'; widths: number[] }
  | { type: 'stop' }

function createColumnResizeState(widths: number[]): ColumnResizeState {
  return { previewWidths: widths, resizingIndex: null }
}

function sameNumberArray(left: number[], right: number[]) {
  return left.length === right.length && left.every((value, index) => value === right[index])
}

function columnResizeReducer(state: ColumnResizeState, action: ColumnResizeAction): ColumnResizeState {
  if (action.type === 'sync-widths') {
    return sameNumberArray(state.previewWidths, action.widths) ? state : { ...state, previewWidths: action.widths }
  }
  if (action.type === 'start') return { ...state, resizingIndex: action.index }
  if (action.type === 'preview') return sameNumberArray(state.previewWidths, action.widths) ? state : { ...state, previewWidths: action.widths }
  return state.resizingIndex === null ? state : { ...state, resizingIndex: null }
}


function textSizeOption(value: unknown) {
  const size = String(value || '').trim()
  if (/^1[12]px$/.test(size)) return '2'
  if (/^(15|16)px$/.test(size)) return '3'
  if (/^18px$/.test(size)) return '4'
  if (/^24px$/.test(size)) return '5'
  if (/^32px$/.test(size)) return '6'
  return '3'
}

function textSizeValue(value: string) {
  return ({ '2': '12px', '3': '15px', '4': '18px', '5': '24px', '6': '32px' } as Record<string, string>)[value] || '15px'
}

function ButtonTextToolbar({ block, settings, onUpdateNode }: {                                                                                                                                                                                       
  block: BuilderBlock
  settings: BuilderSchema['settings']
  onUpdateNode: CanvasProps['onUpdateNode']
}) {
  const style = block.style || {}
  const selected: NonNullable<Selection> = { kind: 'block', id: block.id }
  const setStyle = useCallback((path: string, value: unknown) => onUpdateNode(selected, path, value), [onUpdateNode, selected])
  const font = style.font_family || settings.font_family || 'Arial'
  const size = textSizeOption(style.font_size || settings.font_size)
  const isBold = ['600', '700', 'bold'].includes(String(style.font_weight || '').toLowerCase())
  const isItalic = style.font_style === 'italic'
  const isUnderline = style.text_decoration === 'underline'
  const align = style.align || 'left'
  const keepSelection = (event: MouseEvent<HTMLButtonElement>) => event.preventDefault()
  return (
    <div className="rich-text-toolbar button-text-toolbar" role="toolbar" aria-label="Button text formatting" onClick={(event) => event.stopPropagation()}>
      <select aria-label="Button font family" value={font} onChange={(event) => setStyle('style.font_family', event.target.value)}><option value="Arial">Arial</option><option value="Helvetica">Helvetica</option><option value="Georgia">Georgia</option><option value="Tahoma">Tahoma</option><option value="Verdana">Verdana</option></select>
      <select aria-label="Button font size" value={size} onChange={(event) => setStyle('style.font_size', textSizeValue(event.target.value))}><option value="2">12px</option><option value="3">15px</option><option value="4">18px</option><option value="5">24px</option><option value="6">32px</option></select>
      <span className="rich-text-toolbar__group">
        <button type="button" className={isBold ? 'is-active' : ''} aria-pressed={isBold} aria-label="Bold" title="Bold" onMouseDown={keepSelection} onClick={() => setStyle('style.font_weight', isBold ? 'normal' : 'bold')}><Bold size={15} /></button>
        <button type="button" className={isItalic ? 'is-active' : ''} aria-pressed={isItalic} aria-label="Italic" title="Italic" onMouseDown={keepSelection} onClick={() => setStyle('style.font_style', isItalic ? '' : 'italic')}><Italic size={15} /></button>
        <button type="button" className={isUnderline ? 'is-active' : ''} aria-pressed={isUnderline} aria-label="Underline" title="Underline" onMouseDown={keepSelection} onClick={() => setStyle('style.text_decoration', isUnderline ? '' : 'underline')}><Underline size={15} /></button>
      </span>
      <label className="rich-text-color" title="Button text color"><span>A</span><input type="color" aria-label="Button text color" value={String(style.button_text_color || settings.button_text_color || '#ffffff')} onChange={(event) => setStyle('style.button_text_color', event.target.value)} /></label>
      <span className="rich-text-toolbar__group">
        <button type="button" className={align === 'left' ? 'is-active' : ''} aria-pressed={align === 'left'} aria-label="Align left" title="Align left" onMouseDown={keepSelection} onClick={() => setStyle('style.align', 'left')}><AlignLeft size={15} /></button>
        <button type="button" className={align === 'center' ? 'is-active' : ''} aria-pressed={align === 'center'} aria-label="Align center" title="Align center" onMouseDown={keepSelection} onClick={() => setStyle('style.align', 'center')}><AlignCenter size={15} /></button>
        <button type="button" className={align === 'right' ? 'is-active' : ''} aria-pressed={align === 'right'} aria-label="Align right" title="Align right" onMouseDown={keepSelection} onClick={() => setStyle('style.align', 'right')}><AlignRight size={15} /></button>
      </span>
    </div>
  )
}

function RichTextToolbar({
  block,
  onUpdate,
  referenceDoctype,
  mergeFields,
  mergeFieldsLoading,
  mergeFieldsError,
  onConfigurePersonalization,
  onRetryMergeFields,
}: {
  block: BuilderBlock
  onUpdate: CanvasProps['onUpdateContent']
  referenceDoctype: string
  mergeFields: MergeField[]
  mergeFieldsLoading: boolean
  mergeFieldsError: unknown
  onConfigurePersonalization: () => void
  onRetryMergeFields: () => void
}) {
  const savedSelection = useRef<TextSelectionBookmark | null>(null)
  const selectionFrame = useRef<number | null>(null)
  const linkInputRef = useRef<HTMLInputElement>(null)
  const [toolbarState, dispatchToolbar] = useReducer(richTextToolbarReducer, INITIAL_RICH_TEXT_TOOLBAR_STATE)
  const [personalizationOpen, setPersonalizationOpen] = useState(false)
  const { format, linkOpen, linkValue } = toolbarState
  const getEditor = useCallback(() => document.querySelector(`[data-block-id="${block.id}"] .rich-text`) as HTMLElement | null, [block.id])

  const syncFormat = useCallback(() => {
    const editor = getEditor()
    const selection = document.getSelection()
    if (!editor || !selection?.rangeCount || !selection.anchorNode || !editor.contains(selection.anchorNode)) return
    const commandState = (command: string) => document.queryCommandState(command)
    const commandValue = (command: string) => String(document.queryCommandValue(command) || '')
    const size = commandValue('fontSize')
    const next: TextFormatState = {
      block: normalizeBlockCommand(commandValue('formatBlock')),
      font: normalizeFontCommand(commandValue('fontName')),
      size: ['2', '3', '4', '5', '6'].includes(size) ? size : DEFAULT_TEXT_FORMAT.size,
      color: normalizeCommandColor(commandValue('foreColor')),
      bold: commandState('bold'),
      italic: commandState('italic'),
      underline: commandState('underline'),
      align: commandState('justifyCenter') ? 'center' : commandState('justifyRight') ? 'right' : 'left',
      unorderedList: commandState('insertUnorderedList'),
      orderedList: commandState('insertOrderedList'),
    }
    dispatchToolbar({ type: 'sync-format', format: next })
  }, [getEditor])

  const scheduleFormatSync = useCallback(() => {
    if (selectionFrame.current !== null) cancelAnimationFrame(selectionFrame.current)
    selectionFrame.current = requestAnimationFrame(() => {
      selectionFrame.current = null
      syncFormat()
    })
  }, [syncFormat])

  const captureSelection = useCallback(() => {
    const editor = getEditor()
    const selection = document.getSelection()
    if (!editor || !selection?.rangeCount || !selection.anchorNode || !editor.contains(selection.anchorNode)) return
    const bookmark = createSelectionBookmark(editor, selection.getRangeAt(0))
    if (!bookmark) return
    savedSelection.current = bookmark
    scheduleFormatSync()
  }, [getEditor, scheduleFormatSync])

  useEffect(() => {
    document.addEventListener('selectionchange', captureSelection)
    return () => {
      document.removeEventListener('selectionchange', captureSelection)
      if (selectionFrame.current !== null) cancelAnimationFrame(selectionFrame.current)
    }
  }, [captureSelection])

  useLayoutEffect(() => {
    savedSelection.current = null
    dispatchToolbar({ type: 'reset-format' })
    captureSelection()
  }, [block.id, captureSelection])

  useEffect(() => {
    if (linkOpen) linkInputRef.current?.focus({ preventScroll: true })
  }, [linkOpen])

  const restoreSelection = useCallback((editor: HTMLElement) => {
    const selection = document.getSelection()
    if (!selection) return false
    const range = restoreBookmark(editor, savedSelection.current)
    const fallback = document.createRange()
    if (!range) {
      fallback.selectNodeContents(editor)
      fallback.collapse(false)
    }
    try {
      selection.removeAllRanges()
      selection.addRange(range || fallback)
      return true
    } catch {
      return false
    }
  }, [])

  const apply = useCallback((command: string, value?: string) => {
    const editor = getEditor()
    if (!editor) return
    editor.focus({ preventScroll: true })
    restoreSelection(editor)
    const before = editor.innerHTML
    runLegacyEditorCommand(command, value)
    if (editor.innerHTML !== before) onUpdate(block.id, 'html', editor.innerHTML)
    captureSelection()
  }, [block.id, captureSelection, getEditor, onUpdate, restoreSelection])

  const openLinkEditor = () => {
    dispatchToolbar({ type: 'open-link-editor' })
  }

  const applyLink = () => {
    const href = linkValue.trim()
    if (!href) return
    apply('createLink', href)
    dispatchToolbar({ type: 'close-link-editor' })
  }

  const insertPersonalization = useCallback((token: string) => {
    const editor = getEditor()
    if (!editor) return
    editor.focus({ preventScroll: true })
    restoreSelection(editor)
    insertTextAtSelection(token)
    onUpdate(block.id, 'html', safeRichHtml(editor.innerHTML))
    captureSelection()
    setPersonalizationOpen(false)
  }, [block.id, captureSelection, getEditor, onUpdate, restoreSelection])

  const keepSelection = (event: MouseEvent<HTMLButtonElement>) => event.preventDefault()
  const selectCommand = (command: string, value: string) => apply(command, command === 'formatBlock' ? `<${value}>` : value)

  return (
    <div className="rich-text-toolbar" role="toolbar" aria-label="Text formatting" onPointerDownCapture={captureSelection} onClick={(event) => event.stopPropagation()}>
      <select aria-label="Text style" value={format.block} onChange={(event) => selectCommand('formatBlock', event.target.value)}><option value="p">Paragraph</option><option value="h1">Heading 1</option><option value="h2">Heading 2</option><option value="h3">Heading 3</option></select>
      <select aria-label="Font family" value={format.font} onChange={(event) => selectCommand('fontName', event.target.value)}><option value="Arial">Arial</option><option value="Helvetica">Helvetica</option><option value="Georgia">Georgia</option><option value="Tahoma">Tahoma</option><option value="Verdana">Verdana</option></select>
      <select aria-label="Font size" value={format.size} onChange={(event) => selectCommand('fontSize', event.target.value)}><option value="2">12px</option><option value="3">15px</option><option value="4">18px</option><option value="5">24px</option><option value="6">32px</option></select>
      <span className="rich-text-toolbar__group">
        <button type="button" className={format.bold ? 'is-active' : ''} aria-pressed={format.bold} aria-label="Bold" title="Bold" onMouseDown={keepSelection} onClick={() => apply('bold')}><Bold size={15} /></button>
        <button type="button" className={format.italic ? 'is-active' : ''} aria-pressed={format.italic} aria-label="Italic" title="Italic" onMouseDown={keepSelection} onClick={() => apply('italic')}><Italic size={15} /></button>
        <button type="button" className={format.underline ? 'is-active' : ''} aria-pressed={format.underline} aria-label="Underline" title="Underline" onMouseDown={keepSelection} onClick={() => apply('underline')}><Underline size={15} /></button>
      </span>
      <label className="rich-text-color" title="Text color"><span>A</span><input type="color" aria-label="Text color" value={format.color} onChange={(event) => apply('foreColor', event.target.value)} /></label>
      <span className="rich-text-toolbar__group">
        <button type="button" className={format.align === 'left' ? 'is-active' : ''} aria-pressed={format.align === 'left'} aria-label="Align left" title="Align left" onMouseDown={keepSelection} onClick={() => apply('justifyLeft')}><AlignLeft size={15} /></button>
        <button type="button" className={format.align === 'center' ? 'is-active' : ''} aria-pressed={format.align === 'center'} aria-label="Align center" title="Align center" onMouseDown={keepSelection} onClick={() => apply('justifyCenter')}><AlignCenter size={15} /></button>
        <button type="button" className={format.align === 'right' ? 'is-active' : ''} aria-pressed={format.align === 'right'} aria-label="Align right" title="Align right" onMouseDown={keepSelection} onClick={() => apply('justifyRight')}><AlignRight size={15} /></button>
      </span>
      <span className="rich-text-toolbar__group">
        <button type="button" className={format.unorderedList ? 'is-active' : ''} aria-pressed={format.unorderedList} aria-label="Bulleted list" title="Bulleted list" onMouseDown={keepSelection} onClick={() => apply('insertUnorderedList')}><List size={15} /></button>
        <button type="button" className={format.orderedList ? 'is-active' : ''} aria-pressed={format.orderedList} aria-label="Numbered list" title="Numbered list" onMouseDown={keepSelection} onClick={() => apply('insertOrderedList')}><ListOrdered size={15} /></button>
      </span>
      <button type="button" className={linkOpen ? 'is-active' : ''} aria-label="Insert link" aria-expanded={linkOpen} title="Insert link" onMouseDown={keepSelection} onClick={openLinkEditor}><Link size={15} /></button>
      {linkOpen && <form className="rich-link-editor" onSubmit={(event) => { event.preventDefault(); applyLink() }}>
        <input ref={linkInputRef} type="url" value={linkValue} aria-label="Link URL" placeholder="https://example.com" onChange={(event) => dispatchToolbar({ type: 'set-link-value', value: event.target.value })} onKeyDown={(event) => { if (event.key === 'Escape') { event.preventDefault(); dispatchToolbar({ type: 'close-link-editor' }) } }} />
        <button type="submit" className="rich-link-editor__apply" disabled={!linkValue.trim()}>Apply</button>
        <button type="button" aria-label="Cancel link" title="Cancel" onClick={() => dispatchToolbar({ type: 'close-link-editor' })}>×</button>
      </form>}
      <button type="button" aria-label="Clear formatting" title="Clear formatting" onMouseDown={keepSelection} onClick={() => apply('removeFormat')}><RemoveFormatting size={15} /></button>
      <button type="button" className={`rich-text-toolbar__personalize${personalizationOpen ? ' is-active' : ''}`} aria-label="Personalize" aria-expanded={personalizationOpen} title="Insert personalization" onMouseDown={keepSelection} onClick={() => setPersonalizationOpen((current) => !current)}><Braces size={15} /><span>Personalize</span></button>
      {personalizationOpen && <PersonalizationDialog
        fields={mergeFields}
        referenceDoctype={referenceDoctype}
        loading={mergeFieldsLoading}
        error={mergeFieldsError}
        onConfigure={() => {
          setPersonalizationOpen(false)
          onConfigurePersonalization()
        }}
        onRetry={onRetryMergeFields}
        onInsert={(token) => insertPersonalization(token)}
        onClose={() => setPersonalizationOpen(false)}
      />}
    </div>
  )
}

function NodeToolbar({ selection, listeners, attributes, onEdit, onVisibility, onAiRewrite, aiEligible, onDuplicate, onDelete, onSave }: {
  selection: NonNullable<Selection>
  listeners?: DraggableSyntheticListeners
  attributes?: DraggableAttributes
  onEdit?: () => void
  onVisibility?: () => void
  onAiRewrite?: () => void
  aiEligible?: boolean
  onDuplicate: () => void
  onDelete: () => void
  onSave: () => void
}) {
  return (
    <div className={`node-toolbar node-toolbar--${selection.kind}`} onClick={(event) => event.stopPropagation()}>
      {selection.kind === 'section' ? (
        <>
          <button type="button" title="Edit row" aria-label="Edit row" onClick={onEdit}><Pencil size={13} /></button>
          <button type="button" title="Visibility" aria-label="Edit row visibility" onClick={onVisibility}><EyeOff size={13} /></button>
          <button type="button" title="Duplicate" aria-label="Duplicate row" onClick={onDuplicate}><Copy size={14} /></button>
          {aiEligible && onAiRewrite && <button type="button" className="node-toolbar__ai" title="Rewrite row with AI" aria-label="Rewrite row with AI" onClick={onAiRewrite}><Sparkles size={13} /></button>}
          <button type="button" title="Save to library" aria-label="Save to library" onClick={onSave}><Bookmark size={14} /></button>
          <button type="button" className="node-delete" title="Delete" aria-label="Delete row" onClick={onDelete}><Trash2 size={14} /></button>
        </>
      ) : (
        <>
          <button type="button" className="drag-handle" title="Drag" aria-label="Drag content" {...attributes} {...listeners}><GripVertical size={15} /></button>
          <button type="button" title="Duplicate" aria-label="Duplicate content" onClick={onDuplicate}><Copy size={14} /></button>
          {selection.kind !== 'column' && <button type="button" title="Save to library" aria-label="Save to library" onClick={onSave}><Bookmark size={14} /></button>}
          <button type="button" className="node-delete" title="Delete" aria-label="Delete content" onClick={onDelete}><Trash2 size={14} /></button>
        </>
      )}
    </div>
  )
}

const SOCIAL_PLATFORMS: Record<string, { label: string; path: string; color: string; viewBox?: string }> = {
  Facebook: { label: 'Facebook', color: '#1877f2', viewBox: '0 0 320 512', path: 'M279.14 288l14.22-92.66h-88.91v-60.13c0-25.35 12.42-50.06 52.24-50.06H297V6.26S260.43 0 225.36 0C152.14 0 104.14 44.38 104.14 124.72v70.62H22.89V288h81.25v224h100.31V288z' },
  Instagram: { label: 'Instagram', color: '#e1306c', viewBox: '0 0 448 512', path: 'M224.1 141c-63.6 0-114.9 51.3-114.9 114.9S160.5 370.8 224.1 370.8 339 319.5 339 255.9 287.7 141 224.1 141zm0 189.6c-41.1 0-74.7-33.5-74.7-74.7s33.5-74.7 74.7-74.7 74.7 33.5 74.7 74.7-33.6 74.7-74.7 74.7zm146.4-194.3c0 14.9-12 26.8-26.8 26.8-14.9 0-26.8-12-26.8-26.8s12-26.8 26.8-26.8 26.8 12 26.8 26.8zm76.1 27.2c-1.7-35.9-9.9-67.7-36.2-93.9S352.4 35 316.5 33.3c-37-2.1-147.9-2.1-184.9 0-35.8 1.7-67.6 9.9-93.9 36.1S3.1 127.6 1.4 163.5c-2.1 37-2.1 147.9 0 184.9 1.7 35.9 9.9 67.7 36.2 93.9s58 34.5 93.9 36.2c37 2.1 147.9 2.1 184.9 0 35.9-1.7 67.7-9.9 93.9-36.2s34.5-58 36.2-93.9c2.1-37 2.1-147.8.1-184.9zM398.8 388c-7.8 19.6-22.9 34.7-42.6 42.6-29.5 11.7-99.5 9-132.1 9s-102.7 2.6-132.1-9c-19.6-7.8-34.7-22.9-42.6-42.6-11.7-29.5-9-99.5-9-132.1s-2.6-102.7 9-132.1c7.8-19.6 22.9-34.7 42.6-42.6 29.5-11.7 99.5-9 132.1-9s102.7-2.6 132.1 9c19.6 7.8 34.7 22.9 42.6 42.6 11.7 29.5 9 99.5 9 132.1s2.7 102.7-9 132.1z' },
  LinkedIn: { label: 'LinkedIn', color: '#0a66c2', viewBox: '0 0 448 512', path: 'M100.28 448H7.4V148.9h92.88zM53.79 108.1C24.09 108.1 0 83.5 0 53.8A53.8 53.8 0 0 1 53.79 0c29.7 0 53.79 24.1 53.79 53.8 0 29.7-24.09 54.3-53.79 54.3zM447.9 448h-92.68V302.4c0-34.7-.7-79.2-48.29-79.2-48.3 0-55.69 37.7-55.69 76.7V448h-92.78V148.9h89.08v40.8h1.3c12.4-23.5 42.69-48.3 87.88-48.3 94 0 111.28 61.9 111.28 142.3V448z' },
  YouTube: { label: 'YouTube', color: '#ff0000', viewBox: '0 0 576 512', path: 'M549.7 124.1c-6.3-23.7-24.9-42.3-48.6-48.6C458.2 64 288 64 288 64S117.8 64 74.9 75.5c-23.7 6.3-42.3 24.9-48.6 48.6C14.8 167 14.8 256 14.8 256s0 89 11.5 131.9c6.3 23.7 24.9 42.3 48.6 48.6C117.8 448 288 448 288 448s170.2 0 213.1-11.5c23.7-6.3 42.3-24.9 48.6-48.6C561.2 345 561.2 256 561.2 256s0-89-11.5-131.9zM232 337.6V174.4L374.6 256 232 337.6z' },
  X: { label: 'X', color: '#111827', viewBox: '0 0 512 512', path: 'M389.2 48h70.6L305.6 224.2 487 464H345L233.7 318.6 106.5 464H35.8L200.7 275.5 26.8 48H172.4L272.9 180.9 389.2 48zM364.4 421.8h39.1L151.1 88h-42z' },
  TikTok: { label: 'TikTok', color: '#111827', viewBox: '0 0 24 24', path: 'M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 1 1-2.89-2.89c.3 0 .59.05.86.14V9.4a6.32 6.32 0 0 0-.86-.06 6.34 6.34 0 1 0 6.34 6.34V8.75a8.16 8.16 0 0 0 4.77 1.53z' },
  WhatsApp: { label: 'WhatsApp', color: '#25d366', viewBox: '0 0 24 24', path: 'M17.47 14.38c-.3-.15-1.76-.87-2.03-.97-.27-.1-.47-.15-.67.15-.2.3-.77.97-.94 1.16-.17.2-.35.22-.64.08-.3-.15-1.26-.46-2.39-1.48-.88-.79-1.48-1.76-1.65-2.06-.17-.3-.02-.46.13-.61.13-.13.3-.35.45-.52.15-.17.2-.3.3-.5.1-.2.05-.37-.03-.52-.07-.15-.67-1.61-.92-2.21-.24-.58-.49-.5-.67-.51h-.57c-.2 0-.52.07-.79.37-.27.3-1.04 1.02-1.04 2.48s1.07 2.88 1.21 3.07c.15.2 2.1 3.2 5.08 4.49.71.31 1.26.49 1.69.63.71.23 1.36.2 1.87.12.57-.09 1.76-.72 2.01-1.41.25-.69.25-1.29.17-1.41-.07-.13-.27-.2-.57-.35zM12.05 21.79h-.01a9.87 9.87 0 0 1-5.03-1.38l-.36-.21-3.74.98 1-3.65-.24-.37a9.86 9.86 0 0 1-1.51-5.26c0-5.45 4.44-9.88 9.89-9.88 2.64 0 5.12 1.03 6.99 2.9a9.83 9.83 0 0 1 2.89 6.99c0 5.45-4.44 9.88-9.88 9.88zM20.46 3.49A11.82 11.82 0 0 0 12.05 0C5.5 0 .16 5.34.16 11.89c0 2.1.55 4.14 1.59 5.95L.06 24l6.31-1.65a11.88 11.88 0 0 0 5.68 1.45h.01c6.55 0 11.89-5.34 11.89-11.89 0-3.18-1.24-6.16-3.49-8.42z' },
  Website: { label: 'Website', color: '#475569', viewBox: '0 0 24 24', path: 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20zm6.93 6h-3.04a15.54 15.54 0 0 0-1.1-3.02A8.04 8.04 0 0 1 18.93 8zM12 4.04c.83 1.2 1.48 2.53 1.88 3.96h-3.76A13.7 13.7 0 0 1 12 4.04zM4.26 14a8.2 8.2 0 0 1 0-4h3.43a16.8 16.8 0 0 0 0 4zm.81 2h3.04c.27 1.07.64 2.08 1.1 3.02A8.04 8.04 0 0 1 5.07 16zm3.04-8H5.07a8.04 8.04 0 0 1 4.14-3.02A15.54 15.54 0 0 0 8.11 8zM12 19.96A13.7 13.7 0 0 1 10.12 16h3.76A13.7 13.7 0 0 1 12 19.96zM14.31 14H9.69a14.7 14.7 0 0 1 0-4h4.62a14.7 14.7 0 0 1 0 4zm.48 5.02c.46-.94.83-1.95 1.1-3.02h3.04a8.04 8.04 0 0 1-4.14 3.02zM16.31 14a16.8 16.8 0 0 0 0-4h3.43a8.2 8.2 0 0 1 0 4z' },
}

function socialPlatform(platform: unknown) {
  const key = String(platform || 'Website')
  return SOCIAL_PLATFORMS[key] || SOCIAL_PLATFORMS.Website
}

function SocialIcon({ platform, size, color, shape = 'circle' }: { platform: unknown; size: number; color?: string; shape?: string }) {
  const meta = socialPlatform(platform)
  const iconSize = Math.max(12, size)
  const radius = shape === 'circle' ? '50%' : shape === 'rounded' ? `${Math.max(3, Math.round(iconSize * 0.22))}px` : '0'
  return (
    <span
      className="eb-channel-mark"
      title={meta.label}
      aria-label={meta.label}
      data-eb-channel={meta.label}
      style={{
        display: 'inline-flex',
        width: `${iconSize}px`,
        height: `${iconSize}px`,
        minWidth: `${iconSize}px`,
        minHeight: `${iconSize}px`,
        flex: `0 0 ${iconSize}px`,
        alignItems: 'center',
        justifyContent: 'center',
        overflow: 'hidden',
        borderRadius: radius,
        backgroundColor: color || meta.color,
        color: '#ffffff',
      }}
    >
      <svg
        viewBox={meta.viewBox || '0 0 24 24'}
        width="56%"
        height="56%"
        fill="currentColor"
        aria-hidden="true"
        focusable="false"
        style={{ display: 'block', flex: '0 0 auto' }}
      >
        <path d={meta.path} fill="currentColor" />
      </svg>
    </span>
  )
}


function imageStyle(content: BuilderBlock['content'], style: BuilderBlock['style']): CSSProperties {
  const explicitWidth = content.width ? `${Number(content.width)}px` : undefined
  const wrapperWidth = style.width ? '100%' : undefined
  const height = content.height && content.preserve_aspect_ratio === false ? `${Number(content.height)}px` : 'auto'
  const align = style.align || 'left'
  return {
    display: 'block',
    width: explicitWidth || wrapperWidth || '100%',
    maxWidth: '100%',
    height,
    marginLeft: align === 'center' || align === 'right' ? 'auto' : undefined,
    marginRight: align === 'center' ? 'auto' : align === 'right' ? 0 : undefined,
    borderRadius: style.radius ? normalizeLength(style.radius) : undefined,
  }
}

function imageWrapStyle(style: BuilderBlock['style']): CSSProperties {
  const css = { ...nodeCss(style), display: 'block', textAlign: style.align || 'left', overflow: style.radius ? 'hidden' : undefined } as CSSProperties
  if (style.width && (style.align === 'center' || style.align === 'right')) css.marginLeft = 'auto'
  if (style.width && style.align === 'center') css.marginRight = 'auto'
  if (style.width && style.align === 'right') css.marginRight = 0
  return css
}

function dividerWrapStyle(style: BuilderBlock['style']): CSSProperties {
  const css = { ...nodeCss(style), display: 'block' } as CSSProperties
  delete css.width
  delete css.height
  delete css.textAlign
  delete css.maxWidth
  delete css.marginLeft
  delete css.marginRight
  return css
}

function dividerStyle(block: BuilderBlock, settings: BuilderSchema['settings']): CSSProperties {
  const align = block.style.align || 'center'
  return {
    display: 'block',
    border: 0,
    borderTop: `${Number(block.content.thickness || 1)}px ${String(block.content.style || 'solid')} ${block.style.border_color || settings.link_color}`,
    width: block.style.width || '100%',
    marginTop: 0,
    marginBottom: 0,
    marginLeft: align === 'center' || align === 'right' ? 'auto' : 0,
    marginRight: align === 'center' ? 'auto' : align === 'right' ? 0 : 'auto',
  }
}

function BlockContent({ block, settings, onUpdateContent, onPickImage, onRegisterTextEditor, readOnly = false, onSelectBlock }: {
  block: BuilderBlock
  settings: BuilderSchema['settings']
  onUpdateContent: CanvasProps['onUpdateContent']
  onPickImage: CanvasProps['onPickImage']
  onRegisterTextEditor: CanvasProps['onTextEditorController']
  readOnly?: boolean
  onSelectBlock?: () => void
}) {
  const content = block.content
  const style = nodeCss(block.style)
  if (block.type === 'text') {
    return <div style={style}><RichTextEditor block={block} onUpdate={onUpdateContent} onRegisterController={onRegisterTextEditor} readOnly={readOnly} /></div>
  }
  if (block.type === 'image') {
    const src = String(content.src || '')
    if (!src) return <button type="button" className="image-placeholder" disabled={readOnly} onClick={(event) => { event.stopPropagation(); if (!readOnly) onPickImage(block.id) }}><ImagePlus size={24} /><strong>Add an image</strong><small>Upload a public file</small></button>
    return <div className="image-wrap" style={imageWrapStyle(block.style)}><img className="email-image" src={src} alt={String(content.alt || '')} style={imageStyle(content, block.style)} /></div>
  }
  if (block.type === 'button') {
    const fullWidth = Boolean(content.full_width)
    return <div className="button-wrap" style={{ ...style, textAlign: block.style.align || 'left' }}><PlainTextEditor block={block} onUpdate={onUpdateContent} onFocus={() => undefined} fallback="Call to action" className="email-button" readOnly={readOnly} style={{ display: fullWidth ? 'block' : 'inline-block', width: fullWidth ? '100%' : undefined, background: block.style.button_background || settings.button_background, color: block.style.button_text_color || settings.button_text_color, borderColor: block.style.border_color || 'transparent', borderWidth: normalizeLength(block.style.border_width, '1px'), borderStyle: block.style.border_style || 'solid', borderRadius: normalizeLength(block.style.radius, settings.button_radius), padding: `${normalizeLength(block.style.button_padding_y, '12px')} ${normalizeLength(block.style.button_padding_x, '22px')}`, fontFamily: block.style.font_family || settings.font_family, fontSize: normalizeLength(block.style.font_size, settings.font_size || '16px'), fontStyle: block.style.font_style || undefined, textDecoration: block.style.text_decoration || undefined, fontWeight: block.style.font_weight || '600' }} /></div>
  }
  if (block.type === 'divider') return <div className="divider-wrap" style={dividerWrapStyle(block.style)}><hr style={dividerStyle(block, settings)} /></div>
  if (block.type === 'spacer') return <div className="spacer-block" style={{ height: `${Number(content.height || 24)}px` }}><span>{Number(content.height || 24)} px</span></div>
  if (block.type === 'social') {
    const items = Array.isArray(content.items) ? content.items as Array<{ platform?: string; href?: string; label?: string }> : []
    const display = ['icon', 'text', 'both'].includes(String(content.display)) ? String(content.display) : 'icon'
    const shape = ['circle', 'rounded', 'square'].includes(String(content.icon_shape)) ? String(content.icon_shape) : 'circle'
    const iconSize = Math.max(12, Number(content.icon_size || 24))
    const itemSpacing = Math.max(0, Number(content.item_spacing ?? 8))
    const overrideColor = block.style.color
    return (
      <div
        className="eb-channel-list"
        data-eb-item-count={items.length}
        style={{
          ...style,
          display: 'flex',
          flexWrap: 'wrap',
          gap: `${itemSpacing}px`,
          alignItems: 'center',
          minHeight: display === 'text' ? '1em' : `${iconSize}px`,
          color: block.style.font_color || settings.link_color,
          justifyContent: block.style.align === 'right' ? 'flex-end' : block.style.align === 'center' ? 'center' : 'flex-start',
        }}
        onClick={(event) => {
          event.stopPropagation()
          onSelectBlock?.()
        }}
      >
        {items.length
          ? items.map((item, index) => {
            const meta = socialPlatform(item.platform)
            const label = String(item.label || meta.label)
            return <span className="eb-channel-entry" key={`${item.platform}-${item.href}-${index}`} title={label}>
              {display !== 'text' && <SocialIcon platform={item.platform} size={iconSize} color={overrideColor} shape={shape} />}
              {display !== 'icon' && <span className="eb-channel-label">{label}</span>}
            </span>
          })
          : <small>Add social profiles in the inspector</small>}
      </div>
    )
  }
  if (block.type === 'preview_url') return <div className="preview-link" style={style}>{String(content.text || 'View this email in your browser')}</div>
  return <div className="code-preview"><span>&lt;/&gt;</span><div><strong>Custom HTML</strong><small>{String(content.html || '').slice(0, 80).replace(/<[^>]+>/g, ' ') || 'Empty HTML block'}</small></div></div>
}

function SortableBlock({ block, columnId, props }: { block: BuilderBlock; columnId: string; props: CanvasProps }) {
  const sortable = useSortable({ id: `block:${block.id}`, data: { kind: 'block', blockId: block.id, columnId } })
  const selected = props.selection?.kind === 'block' && props.selection.id === block.id
  const hidden = block.visibility?.device !== 'both' && block.visibility?.device !== props.viewport
  const transform = sortable.transform ? CSS.Transform.toString(sortable.transform) : undefined
  return (
    <article
      ref={sortable.setNodeRef}
      className={`canvas-block${selected ? ' is-selected' : ''}${sortable.isDragging ? ' is-dragging' : ''}${hidden ? ' is-device-hidden' : ''}`}
      style={{ transform, transition: sortable.transition }}
      onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'block', id: block.id }) }}
      data-block-id={block.id}
    >
      {props.showStructure && <span className="node-label">{BLOCKS.find((item) => item.type === block.type)?.label}</span>}
      {!props.readOnly && <NodeToolbar selection={{ kind: 'block', id: block.id }} listeners={sortable.listeners} attributes={sortable.attributes} onDuplicate={() => props.onDuplicate({ kind: 'block', id: block.id })} onDelete={() => props.onDelete({ kind: 'block', id: block.id })} onSave={() => props.onSaveComponent({ kind: 'block', id: block.id })} />}
      <BlockContent block={block} settings={props.schema.settings} onUpdateContent={props.onUpdateContent} onPickImage={props.onPickImage} onRegisterTextEditor={props.onTextEditorController} readOnly={props.readOnly} onSelectBlock={() => props.onSelect({ kind: 'block', id: block.id })} />
    </article>
  )
}

function Column({ column, props }: { column: BuilderColumn; props: CanvasProps }) {
  const { setNodeRef, isOver } = useDroppable({ id: `column:${column.id}`, data: { kind: 'column', columnId: column.id } })
  const selected = props.selection?.kind === 'column' && props.selection.id === column.id
  const active = selected || (props.selection?.kind === 'block' && column.blocks.some((block) => block.id === props.selection?.id))
  return (
    <div ref={setNodeRef} className={`canvas-column${selected ? ' is-selected' : ''}${isOver ? ' is-over' : ''}`} style={nodeCss(column.style)} onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'column', id: column.id }) }}>
      <SortableContext items={column.blocks.map((block) => `block:${block.id}`)} strategy={verticalListSortingStrategy}>
        {column.blocks.map((block) => <SortableBlock key={block.id} block={block} columnId={column.id} props={props} />)}
      </SortableContext>
      {!column.blocks.length && <button type="button" className="empty-column" disabled={props.readOnly} onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'column', id: column.id }); if (!props.readOnly) props.onAddBlock(column.id) }}><span><Plus size={16} /></span><strong>{props.readOnly ? 'Empty column' : 'Add content'}</strong><small>{props.readOnly ? 'Unlock visual editing to insert modules' : 'Drop or click to insert'}</small></button>}
      {column.blocks.length > 0 && active && !props.readOnly && <button type="button" className="column-add" title="Add content" onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'column', id: column.id }); if (!props.readOnly) props.onAddBlock(column.id) }}><Plus size={13} /><span>Add content</span></button>}
    </div>
  )
}

function SortableSection({ section, props }: { section: BuilderSection; props: CanvasProps }) {
  const sortable = useSortable({ id: `section:${section.id}`, data: { kind: 'section', sectionId: section.id } })
  const selected = props.selection?.kind === 'section' && props.selection.id === section.id
  const layout = LAYOUTS.find((item) => item.value === section.layout) || LAYOUTS[0]
  const resolvedWidths = useMemo(() => normalizeColumnWidths(section.column_widths, section.columns.length, layout.widths), [layout.widths, section.column_widths, section.columns.length])
  const [resizeState, dispatchResize] = useReducer(columnResizeReducer, resolvedWidths, createColumnResizeState)
  const resizeCleanup = useRef<(() => void) | null>(null)
  useEffect(() => dispatchResize({ type: 'sync-widths', widths: resolvedWidths }), [resolvedWidths])
  useEffect(() => () => resizeCleanup.current?.(), [])
  const { previewWidths, resizingIndex } = resizeState
  const displayWidths = previewWidths.length === section.columns.length ? previewWidths : resolvedWidths
  const mobile = props.viewport === 'mobile'
  const gridTemplateColumns = mobile && section.mobile_stack !== 'none' ? '1fr' : displayWidths.map((width) => `${width}fr`).join(' ')
  const transform = sortable.transform ? CSS.Transform.toString(sortable.transform) : undefined
  const explicitSectionPadding = Object.values(section.style.padding || {}).some((value) => !['', '0', '0px'].includes(String(value || '')))
  const sectionStyle = {
    ...nodeCss(section.style),
    padding: explicitSectionPadding ? nodeCss(section.style).padding : normalizeLength(props.schema.settings.section_padding),
  }
  const alignItems = section.vertical_align === 'middle' ? 'center' : section.vertical_align === 'bottom' ? 'end' : 'start'
  const startResize = (event: ReactPointerEvent<HTMLButtonElement>, index: number) => {
    event.preventDefault()
    event.stopPropagation()
    const container = event.currentTarget.parentElement
    if (!container) return
    const rect = container.getBoundingClientRect()
    const startX = event.clientX
    const start = [...previewWidths]
    const pairTotal = start[index] + start[index + 1]
    const minimum = Math.min(8, Math.max(5, pairTotal / 2 - 0.01))
    let latest = start
    dispatchResize({ type: 'start', index })
    document.body.classList.add('is-resizing-columns')
    const move = (moveEvent: PointerEvent) => {
      const delta = ((moveEvent.clientX - startX) / Math.max(1, rect.width)) * 100
      const left = Math.max(minimum, Math.min(pairTotal - minimum, start[index] + delta))
      latest = [...start]
      latest[index] = Number(left.toFixed(3))
      latest[index + 1] = Number((pairTotal - left).toFixed(3))
      dispatchResize({ type: 'preview', widths: latest })
    }
    const stop = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', stop)
      window.removeEventListener('pointercancel', stop)
      document.body.classList.remove('is-resizing-columns')
      resizeCleanup.current = null
      dispatchResize({ type: 'stop' })
      props.onResizeColumns(section.id, latest)
    }
    resizeCleanup.current?.()
    resizeCleanup.current = stop
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', stop, { once: true })
    window.addEventListener('pointercancel', stop, { once: true })
  }
  return (
    <section
      ref={sortable.setNodeRef}
      className={`canvas-section${selected ? ' is-selected' : ''}${sortable.isDragging ? ' is-dragging' : ''}`}
      style={{ ...sectionStyle, transform, transition: sortable.transition }}
      onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'section', id: section.id }) }}
    >
      {props.showStructure && <span className="section-label">Row · {displayWidths.map((width) => Math.round(width) + '%').join(' / ')}</span>}
      <button type="button" className="row-drag-rail" title="Drag row" aria-label="Drag row" onClick={(event) => { event.stopPropagation(); props.onSelect({ kind: 'section', id: section.id }) }} {...sortable.attributes} {...sortable.listeners}><GripVertical size={15} /></button>
      {!props.readOnly && <NodeToolbar selection={{ kind: 'section', id: section.id }} onEdit={() => props.onEditSection(section.id, 'content')} onAiRewrite={() => props.onAiRewriteSection?.(section.id)} aiEligible={props.aiEnabled} onVisibility={() => props.onEditSection(section.id, 'visibility')} onDuplicate={() => props.onDuplicate({ kind: 'section', id: section.id })} onDelete={() => props.onDelete({ kind: 'section', id: section.id })} onSave={() => props.onSaveComponent({ kind: 'section', id: section.id })} />}
      <div className={`canvas-columns${mobile && section.mobile_stack === 'reverse' ? ' is-reverse' : ''}`} style={{ gridTemplateColumns, alignItems }}>
        {section.columns.map((column) => <Column key={column.id} column={column} props={props} />)}
        {!mobile && displayWidths.slice(0, -1).map((width, index) => {
          const boundary = displayWidths.slice(0, index + 1).reduce((sum, value) => sum + value, 0)
          if (props.readOnly) return null
          return <button key={`${section.id}:resize:${index}`} type="button" className={'column-resizer' + (resizingIndex === index ? ' is-resizing' : '')} style={{ left: boundary + '%' }} aria-label={'Resize columns ' + (index + 1) + ' and ' + (index + 2)} onClick={(clickEvent) => clickEvent.stopPropagation()} onPointerDown={(pointerEvent) => startResize(pointerEvent, index)}><i /><span>{Math.round(width)}% / {Math.round(displayWidths[index + 1])}%</span></button>
        })}
      </div>
    </section>
  )
}

function selectedEditorBlockId() {
  const selection = document.getSelection()
  if (!selection?.rangeCount || selection.isCollapsed || !selection.toString().trim()) return null
  const endpointElement = (node: Node | null) => node instanceof Element ? node : node?.parentElement || null
  const anchor = endpointElement(selection.anchorNode)
  const focus = endpointElement(selection.focusNode)
  const anchorEditor = anchor?.closest('[data-block-id] .rich-text, [data-block-id] .email-button') as HTMLElement | null
  const focusEditor = focus?.closest('[data-block-id] .rich-text, [data-block-id] .email-button') as HTMLElement | null
  if (!anchorEditor || !focusEditor || anchorEditor !== focusEditor) return null
  const block = anchorEditor.closest('[data-block-id]') as HTMLElement | null
  return block?.dataset.blockId || null
}

export const Canvas = memo(function Canvas(props: CanvasProps) {
  const { setNodeRef, isOver } = useDroppable({ id: 'email-canvas', data: { kind: 'canvas' } })
  const [textToolbarBlockId, setTextToolbarBlockId] = useState<string | null>(null)

  useEffect(() => {
    const syncTextSelection = () => {
      const blockId = selectedEditorBlockId()
      setTextToolbarBlockId((current) => current === blockId ? current : blockId)
      if (blockId && (props.selection?.kind !== 'block' || props.selection.id !== blockId)) props.onSelect({ kind: 'block', id: blockId })
    }
    document.addEventListener('selectionchange', syncTextSelection)
    window.addEventListener('mouseup', syncTextSelection)
    window.addEventListener('keyup', syncTextSelection)
    return () => {
      document.removeEventListener('selectionchange', syncTextSelection)
      window.removeEventListener('mouseup', syncTextSelection)
      window.removeEventListener('keyup', syncTextSelection)
    }
  }, [props.onSelect, props.selection])

  useEffect(() => {
    if (!textToolbarBlockId || findBlock(props.schema, textToolbarBlockId)?.block) return
    setTextToolbarBlockId(null)
  }, [props.schema, textToolbarBlockId])

  const selectedText = textToolbarBlockId ? findBlock(props.schema, textToolbarBlockId)?.block : undefined
  const frameStyle = {
    width: props.viewport === 'mobile' ? 375 : props.schema.settings.content_width,
    maxWidth: '100%',
    background: props.schema.settings.content_background,
    color: props.schema.settings.text_color,
    fontFamily: props.schema.settings.font_family,
    fontSize: props.schema.settings.font_size,
    '--email-link-color': props.schema.settings.link_color,
    '--email-link-decoration': props.schema.settings.link_decoration,
  } as CSSProperties
  return (
    <div className="canvas-stage" onClick={() => props.onSelect(null)}>
      {selectedText?.type === 'text' && <RichTextToolbar
        block={selectedText}
        onUpdate={props.onUpdateContent}
        referenceDoctype={String(props.metadata.reference_doctype || '')}
        mergeFields={props.mergeFields}
        mergeFieldsLoading={props.mergeFieldsLoading}
        mergeFieldsError={props.mergeFieldsError}
        onConfigurePersonalization={props.onEditTemplate}
        onRetryMergeFields={props.onRetryMergeFields}
      />}
      {selectedText?.type === 'button' && !props.readOnly && <ButtonTextToolbar block={selectedText} settings={props.schema.settings} onUpdateNode={props.onUpdateNode} />}
      <button type="button" className="inbox-card" onClick={(event: MouseEvent) => { event.stopPropagation(); props.onEditTemplate() }}>
        <span><small>Subject</small><strong>{props.metadata.subject || 'Add a subject line'}</strong></span>
        <span><small>Preheader</small><strong>{props.metadata.preheader || 'Add preview text'}</strong></span>
        <span className="edit-inbox">Edit</span>
      </button>
      <div className="email-shell" style={{ width: frameStyle.width, maxWidth: '100%', background: props.schema.settings.body_background }}>
        <div ref={setNodeRef} className={`email-canvas${props.schema.sections.length ? ' has-sections' : ''}${isOver ? ' is-over' : ''}`} style={frameStyle}>
          <SortableContext items={props.schema.sections.map((section) => `section:${section.id}`)} strategy={verticalListSortingStrategy}>
            {props.schema.sections.map((section) => <SortableSection key={section.id} section={section} props={props} />)}
          </SortableContext>
          {!props.schema.sections.length && <button type="button" className="empty-canvas" disabled={props.readOnly} onClick={(event) => { event.stopPropagation(); if (!props.readOnly) props.onAddSection() }}><span><Plus size={20} /></span><strong>Start with a row</strong><small>Click here or drag a row from the library</small></button>}
          {props.schema.sections.length > 0 && !props.readOnly && <button type="button" className="add-row-button" onClick={(event) => { event.stopPropagation(); props.onAddSection() }}><Plus size={14} /> Add row</button>}
        </div>
      </div>
    </div>
  )
})
