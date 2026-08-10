import { memo, useEffect, useLayoutEffect, useMemo, useRef, useState, type ChangeEvent, type FormEvent, type KeyboardEvent, type ReactNode } from 'react'
                                                                                                                                                                                                                                                                      import { AlignCenter, AlignLeft, AlignRight, Braces, Check, ChevronDown, ChevronUp, Copy, Database, GripVertical, Link2, Loader2, Monitor, Plus, Search, Smartphone, Trash2, Unlink2, Upload, X } from 'lucide-react'

import { useFrappeGetCall, useFrappePostCall } from 'frappe-react-sdk'

import { BLOCKS, findSelected, LAYOUTS, normalizeColumnWidths, rebalanceColumnWidths } from '../lib/builder'
import { API_METHODS, makeCallKey } from '../lib/api'
import { conditionFieldOptions, conditionNeedsValue, conditionOperatorOptions, defaultConditionOperator, defaultConditionValue, isCheckField, isMultiSelectField, isSelectField, normalizeConditionForField } from '../lib/conditionFields'
import { getErrorMessage } from '../lib/errors'
import { insertLineBreakAtSelection } from '../lib/editorDom'
import type { ApiResponse, BuilderBlock, BuilderDocument, BuilderSection, InspectorTab, LayoutType, LinkMergeFieldsResponse, MergeField, NodeStyle, Selection, Spacing, Visibility, VisibilityCondition } from '../types'
import { PersonalizationDialog } from './PersonalizationPicker'


type InspectorProps = {
  open: boolean
  document: BuilderDocument
  selection: Selection
  tab: InspectorTab
  uploading: boolean
  uploadProgress: number
  mergeFields: MergeField[]
  mergeFieldsLoading: boolean
  mergeFieldsError: unknown
  onTab: (tab: InspectorTab) => void
  onClose: () => void
  onMetadata: (key: keyof BuilderDocument['metadata'], value: BuilderDocument['metadata'][keyof BuilderDocument['metadata']]) => void
  onSetting: (key: keyof BuilderDocument['schema']['settings'], value: string | number) => void
  onNode: (selection: NonNullable<Selection>, path: string, value: unknown) => void
  onLayout: (sectionId: string, layout: LayoutType) => void
  onColumnWidths: (sectionId: string, widths: number[]) => void
  onUploadImage: (blockId: string, file: File) => void
  onChooseImage: (blockId: string) => void
  onConfigurePersonalization: () => void
  onRetryMergeFields: () => void
  onFocusText: (blockId: string) => void
  onPrepareMergeField: (blockId: string) => void
  onInsertMergeField: (blockId: string, token: string) => boolean
  onDuplicate: (selection: NonNullable<Selection>) => void
  onDelete: (selection: NonNullable<Selection>) => void
  onAiRewriteSection?: (sectionId: string) => void
  aiEnabled?: boolean
  readOnly?: boolean
}

function Group({ title, children }: { title: string; children: ReactNode }) {
  return <section className="inspector-group"><h3>{title}</h3>{children}</section>
}

function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return <label className="field"><span>{label}</span>{children}{hint && <small>{hint}</small>}</label>
}

function TextInput({ value, onChange, placeholder = '' }: { value: unknown; onChange: (value: string) => void; placeholder?: string }) {
  return <input value={String(value ?? '')} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
}

function escapeHtmlText(value: string) {
  return value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
}

function PersonalizedTextField({
  label,
  value,
  onChange,
  props,
  placeholder = '',
  multiline = false,
}: {
  label: string
  value: unknown
  onChange: (value: string) => void
  props: InspectorProps
  placeholder?: string
  multiline?: boolean
}) {
  const controlRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null)
  const selectionRef = useRef({ start: String(value ?? '').length, end: String(value ?? '').length })
  const [open, setOpen] = useState(false)
  const source = String(value ?? '')
  const captureSelection = () => {
    const control = controlRef.current
    if (!control) return
    selectionRef.current = {
      start: control.selectionStart ?? source.length,
      end: control.selectionEnd ?? source.length,
    }
  }
  const insert = (token: string) => {
    const start = Math.min(selectionRef.current.start, source.length)
    const end = Math.min(Math.max(start, selectionRef.current.end), source.length)
    const next = `${source.slice(0, start)}${token}${source.slice(end)}`
    onChange(next)
    setOpen(false)
    requestAnimationFrame(() => {
      const control = controlRef.current
      if (!control) return
      const caret = start + token.length
      control.focus({ preventScroll: true })
      control.setSelectionRange(caret, caret)
      selectionRef.current = { start: caret, end: caret }
    })
  }
  const common = {
    ref: controlRef as never,
    value: source,
    placeholder,
    disabled: props.readOnly,
    onChange: (event: ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => onChange(event.target.value),
    onSelect: captureSelection,
    onKeyUp: captureSelection,
    onClick: captureSelection,
  }
  return <div className={`field personalized-field${multiline ? ' is-multiline' : ''}`}>
    <span>{label}</span>
    <div className="personalized-field__control">
      {multiline ? <textarea {...common} rows={3} /> : <input {...common} />}
      <button
        type="button"
        disabled={props.readOnly}
        title={`Personalize ${label}`}
        aria-label={`Personalize ${label}`}
        aria-expanded={open}
        onMouseDown={captureSelection}
        onClick={() => setOpen((current) => !current)}
      ><Braces size={14} /><span>Personalize</span></button>
    </div>
    {open && <PersonalizationDialog
      fields={props.mergeFields}
      referenceDoctype={String(props.document.metadata.reference_doctype || '')}
      loading={props.mergeFieldsLoading}
      error={props.mergeFieldsError}
      onConfigure={() => {
        setOpen(false)
        props.onConfigurePersonalization()
      }}
      onRetry={props.onRetryMergeFields}
      onInsert={(token) => insert(token)}
      onClose={() => setOpen(false)}
    />}
  </div>
}

type LinkSearchResult = { value: string; label?: string; description?: string }
type LinkSearchResponse = { message: LinkSearchResult[] }

type FrappeLinkInputProps = {
  doctype: string
  value: string
  placeholder?: string
  disabled?: boolean
  filters?: Record<string, unknown>
  onChange: (value: string) => void
  onValidSelect?: (value: string) => void
}

function FrappeLinkInput({ doctype, value, placeholder, disabled = false, filters, onChange, onValidSelect }: FrappeLinkInputProps) {
  const wrapperRef = useRef<HTMLDivElement>(null)
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState(value)
  const [options, setOptions] = useState<LinkSearchResult[]>([])
  const [highlighted, setHighlighted] = useState(0)
  const [error, setError] = useState('')
  const search = useFrappePostCall<LinkSearchResponse>('frappe.desk.search.search_link')
  const validate = useFrappePostCall<{ message?: Record<string, unknown> }>('frappe.client.validate_link_and_fetch')
  const searchCallRef = useRef(search.call)
  const validateCallRef = useRef(validate.call)
  const activeSearchRef = useRef(0)
  const filtersJson = useMemo(() => filters ? JSON.stringify(filters) : '{}', [filters])
  const searchText = query.trim()
  const needsMoreCharacters = open && !disabled && Boolean(doctype) && searchText.length < 2

  useEffect(() => { searchCallRef.current = search.call }, [search.call])
  useEffect(() => { validateCallRef.current = validate.call }, [validate.call])
  useEffect(() => { if (!open) setQuery(value) }, [open, value])

  useEffect(() => {
    if (!open || disabled || !doctype || searchText.length < 2) {
      activeSearchRef.current += 1
      setOptions([])
      setHighlighted(0)
      if (searchText.length < 2) setError('')
      return
    }
    const requestId = activeSearchRef.current + 1
    activeSearchRef.current = requestId
    const timer = window.setTimeout(async () => {
      try {
        const response = await searchCallRef.current({
          doctype,
          txt: searchText,
          page_length: 8,
          filters: filtersJson,
        })
        if (requestId !== activeSearchRef.current) return
        setOptions(Array.isArray(response.message) ? response.message : [])
        setHighlighted(0)
        setError('')
      } catch (err) {
        if (requestId !== activeSearchRef.current) return
        setOptions([])
        setError(getErrorMessage(err, 'Could not search records.'))
      }
    }, 320)
    return () => window.clearTimeout(timer)
  }, [disabled, doctype, filtersJson, open, searchText])

  useEffect(() => {
    if (!open) return
    const close = (event: MouseEvent) => {
      if (!wrapperRef.current?.contains(event.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', close)
    return () => document.removeEventListener('mousedown', close)
  }, [open])

  const commit = async (next: string, validateValue = true) => {
    const clean = next.trim()
    setQuery(clean)
    setOpen(false)
    setError('')
    if (clean === value.trim()) return
    if (!clean || !validateValue || !doctype) {
      onChange(clean)
      onValidSelect?.(clean)
      return
    }
    try {
      const response = await validateCallRef.current({ doctype, docname: clean, filters: filtersJson })
      if (!response.message || Object.keys(response.message).length === 0) {
        setError(`${clean} was not found or is not permitted.`)
        setQuery(value)
        return
      }
      onChange(clean)
      onValidSelect?.(clean)
    } catch (err) {
      setError(getErrorMessage(err, `${clean} could not be validated.`))
      setQuery(value)
    }
  }

  const choose = (option: LinkSearchResult) => { void commit(option.value) }
  const onKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (!open && ['ArrowDown', 'ArrowUp'].includes(event.key)) setOpen(true)
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      setHighlighted((current) => Math.min(current + 1, Math.max(options.length - 1, 0)))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      setHighlighted((current) => Math.max(current - 1, 0))
    } else if (event.key === 'Enter') {
      event.preventDefault()
      const option = options[highlighted]
      void commit(option?.value || query)
    } else if (event.key === 'Escape') {
      setOpen(false)
    }
  }

  return <div className={`frappe-link-input${open ? ' is-open' : ''}${error ? ' has-error' : ''}`} ref={wrapperRef}>
    <span className="frappe-link-input__control">
      <Search size={14} />
      <input
        value={query}
        disabled={disabled}
        placeholder={placeholder}
        autoComplete="off"
        onFocus={() => setOpen(true)}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); setError('') }}
        onBlur={() => { void commit(query) }}
        onKeyDown={onKeyDown}
      />
      {(search.loading || validate.loading) ? <Loader2 className="frappe-link-input__spinner" size={14} /> : value ? <Check size={14} /> : null}
    </span>
    {open && !disabled && <div className="frappe-link-menu" role="listbox">
      {error && <div className="frappe-link-message is-error">{error}</div>}
      {!error && needsMoreCharacters && <div className="frappe-link-message">Type at least 2 characters</div>}
      {!error && !needsMoreCharacters && search.loading && <div className="frappe-link-message">Searching…</div>}
      {!error && !needsMoreCharacters && !search.loading && options.length === 0 && <div className="frappe-link-message">No matches found</div>}
      {!error && !needsMoreCharacters && options.map((option, index) => <button
        type="button"
        role="option"
        aria-selected={highlighted === index}
        key={option.value}
        className={highlighted === index ? 'is-highlighted' : ''}
        onMouseDown={(event) => event.preventDefault()}
        onMouseEnter={() => setHighlighted(index)}
        onClick={() => choose(option)}
      >
        <strong>{option.label || option.value}</strong>
        {option.description && <small>{option.description}</small>}
      </button>)}
    </div>}
    {!open && error && <small className="frappe-link-error">{error}</small>}
  </div>
}

function NumberInput({ value, onChange, min = 0, max = 2000, suffix }: { value: unknown; onChange: (value: number) => void; min?: number; max?: number; suffix?: string }) {
  return <span className="number-field"><input type="number" value={Number(value || 0)} min={min} max={max} onChange={(event) => onChange(Number(event.target.value))} />{suffix && <small>{suffix}</small>}</span>
}

function SelectInput({ value, onChange, options }: { value: unknown; onChange: (value: string) => void; options: Array<[string, string]> }) {
  return <select value={String(value ?? '')} onChange={(event) => onChange(event.target.value)}>{options.map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select>
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (checked: boolean) => void }) {
  return <label className="toggle-field"><span>{label}</span><input type="checkbox" checked={checked} onChange={(event) => onChange(event.target.checked)} /><i /></label>
}

function sanitizeInspectorRichHtml(value: unknown) {
  const source = String(value ?? '<p>Write your message here</p>')
  const parsed = new DOMParser().parseFromString(source, 'text/html')
  parsed.querySelectorAll('script,style,iframe,object,embed,form').forEach((node) => node.remove())
  parsed.querySelectorAll('*').forEach((node) => {
    Array.from(node.attributes).forEach((attribute) => {
      const name = attribute.name.toLowerCase()
      if (name.startsWith('on')) node.removeAttribute(attribute.name)
      if (['href', 'src'].includes(name) && /^\s*(?:javascript|data):/i.test(attribute.value)) node.removeAttribute(attribute.name)
    })
  })
  return parsed.body.innerHTML
}

function stopInspectorTextShortcut(event: KeyboardEvent<HTMLDivElement>) {
  if (event.key === 'Delete' || event.key === 'Backspace') event.stopPropagation()
}

function insertInspectorLineBreak(event: KeyboardEvent<HTMLDivElement>) {
  stopInspectorTextShortcut(event)
  if (event.key !== 'Enter') return
  event.preventDefault()
  insertLineBreakAtSelection()
}

function SidebarTextEditor({ value, readOnly = false, onChange }: { value: unknown; readOnly?: boolean; onChange: (value: string) => void }) {
  const editorRef = useRef<HTMLDivElement>(null)
  const externalHtml = useMemo(() => sanitizeInspectorRichHtml(value), [value])

  useLayoutEffect(() => {
    const editor = editorRef.current
    if (!editor || document.activeElement === editor || editor.innerHTML === externalHtml) return
    editor.innerHTML = externalHtml
  }, [externalHtml])

  const commit = () => {
    const editor = editorRef.current
    if (!editor) return
    const clean = sanitizeInspectorRichHtml(editor.innerHTML)
    if (editor.innerHTML !== clean) editor.innerHTML = clean
    if (clean !== String(value || '')) onChange(clean)
  }

  const updateLive = (event: FormEvent<HTMLDivElement>) => {
    onChange((event.currentTarget as HTMLDivElement).innerHTML)
  }

  return <div
    ref={editorRef}
    className={`inspector-rich-text-editor${readOnly ? ' is-read-only' : ''}`}
    contentEditable={!readOnly}
    role="textbox"
    aria-label="Text content"
    aria-multiline="true"
    suppressContentEditableWarning
    onInput={readOnly ? undefined : updateLive}
    onBlur={readOnly ? undefined : commit}
    onKeyDown={readOnly ? undefined : insertInspectorLineBreak}
  />
}

function ColorField({ label, value, onChange }: { label: string; value: unknown; onChange: (value: string) => void }) {
  const color = String(value || '#ffffff')
  return <Field label={label}><span className="color-field"><input type="color" value={/^#[0-9a-f]{6}$/i.test(color) ? color : '#ffffff'} onChange={(event) => onChange(event.target.value)} /><input value={color} onChange={(event) => onChange(event.target.value)} /></span></Field>
}

function AppearanceColorField({ label, value, onChange }: { label: string; value: unknown; onChange: (value: string) => void }) {
  const color = String(value || '#ffffff')
  const safeColor = /^#[0-9a-f]{6}$/i.test(color) ? color : '#ffffff'
  return <label className="appearance-color-field">
    <span>{label}</span>
    <span className="appearance-color-value">
      <input aria-label={`${label} color picker`} type="color" value={safeColor} onChange={(event) => onChange(event.target.value)} />
      <input aria-label={`${label} color value`} value={color} onChange={(event) => onChange(event.target.value)} />
    </span>
  </label>
}

function AlignmentControl({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const options = [
    ['left', 'Align left', AlignLeft],
    ['center', 'Align center', AlignCenter],
    ['right', 'Align right', AlignRight],
  ] as const
  return <div className="appearance-control">
    <span>Alignment</span>
    <div className="alignment-control" role="group" aria-label="Text alignment">
      {options.map(([option, label, Icon]) => <button type="button" key={option} className={value === option ? 'is-active' : ''} onClick={() => onChange(option)} title={label} aria-label={label}><Icon size={16} /></button>)}
    </div>
  </div>
}

type LengthUnit = 'px' | '%' | 'em' | 'rem' | 'pt'

function lengthParts(value: unknown, fallback = '0px') {
  const source = String(value ?? fallback).trim() || fallback
  const match = source.match(/^([0-9]{1,4}(?:\.[0-9]{0,2})?)(px|%|em|rem|pt)?$/i)
  return {
    amount: match?.[1] || '0',
    unit: (match?.[2]?.toLowerCase() || 'px') as LengthUnit,
  }
}

function LengthInput({ value, onChange, min = 0, max = 2000, fallback = '0px', units = ['px', '%', 'em', 'rem', 'pt'] as LengthUnit[] }: {
  value: unknown
  onChange: (value: string) => void
  min?: number
  max?: number
  fallback?: string
  units?: LengthUnit[]
}) {
  const current = lengthParts(value, fallback)
  const setAmount = (amount: string) => onChange(amount === '' ? '' : `${amount}${current.unit}`)
  const setUnit = (unit: string) => onChange(`${current.amount}${unit}`)
  return <span className="length-input">
    <input type="number" min={min} max={max} step="0.5" value={current.amount} onChange={(event) => setAmount(event.target.value)} />
    <select aria-label="Unit" value={current.unit} onChange={(event) => setUnit(event.target.value)}>{units.map((unit) => <option key={unit} value={unit}>{unit}</option>)}</select>
  </span>
}

const SPACING_SIDES = [['top', 'Top'], ['right', 'Right'], ['bottom', 'Bottom'], ['left', 'Left']] as const

function spacingValue(value: Spacing = {}) {
  return value.top || value.right || value.bottom || value.left || '0px'
}

function hasIndependentSpacing(value: Spacing = {}) {
  const first = spacingValue(value)
  return SPACING_SIDES.some(([side]) => (value[side] || '0px') !== first)
}

function SpacingEditor({ label, value = {}, onChange }: { label: string; value?: Spacing; onChange: (value: Spacing) => void }) {
  const [individual, setIndividual] = useState(() => hasIndependentSpacing(value))
  const allValue = spacingValue(value)
  const setAll = (next: string) => onChange({ top: next, right: next, bottom: next, left: next })
  const toggleMode = () => {
    // Moving back to one value is intentional: use the current first value
    // for every side so the control never silently keeps hidden differences.
    if (individual) setAll(allValue)
    setIndividual((current) => !current)
  }
  return <div className="spacing-editor">
    <div className="spacing-editor__heading">
      <strong>{label}</strong>
      <button type="button" className="spacing-mode-button" onClick={toggleMode} title={individual ? 'Use one value for all sides' : 'Set each side separately'}>
        {individual ? <Link2 size={13} /> : <Unlink2 size={13} />}<span>{individual ? 'Link sides' : 'Edit sides'}</span>
      </button>
    </div>
    {individual ? <div className="spacing-side-grid">{SPACING_SIDES.map(([side, sideLabel]) => <label key={side}><span>{sideLabel}</span><LengthInput value={value[side] || '0px'} onChange={(next) => onChange({ ...value, [side]: next })} max={600} /></label>)}</div> : <label className="spacing-all-control"><span>All sides</span><LengthInput value={allValue} onChange={setAll} max={600} /></label>}
  </div>
}

function PersonalizationPreview({ props }: { props: InspectorProps }) {
  const { metadata } = props.document
  return <Group title="Personalization preview">
    <p className="helper-text">Choose a sample record to preview dynamic fields with real values.</p>
    <div className="personalization-preview-fields">
      <Field label="Reference DocType"><FrappeLinkInput doctype="DocType" value={metadata.reference_doctype} onChange={(value) => props.onMetadata('reference_doctype', value)} placeholder="Customer" filters={{ issingle: 0, istable: 0 }} /></Field>
      <Field label="Preview document"><FrappeLinkInput doctype={metadata.reference_doctype} value={metadata.preview_document} onChange={(value) => props.onMetadata('preview_document', value)} placeholder={metadata.reference_doctype ? `Select ${metadata.reference_doctype}` : 'Choose Reference DocType first'} disabled={!metadata.reference_doctype} /></Field>
      <label className="toggle-field validation-toggle"><span>Validate dynamic fields{!metadata.reference_doctype ? <small>Off keeps this template generic. Turn on only when a Reference DocType is selected.</small> : <small>Checks merge fields and visibility rules against readable {metadata.reference_doctype} fields.</small>}</span><input type="checkbox" checked={Boolean(metadata.validate_dynamic_fields)} onChange={(event) => props.onMetadata('validate_dynamic_fields', event.target.checked)} /><i /></label>
    </div>
  </Group>
}

function TemplateInspector({ props }: { props: InspectorProps }) {
  const { metadata } = props.document
  const settings = props.document.schema.settings
  return <>
    <Group title="Inbox content">
      <PersonalizedTextField label="Subject line" value={metadata.subject} onChange={(value) => props.onMetadata('subject', value)} props={props} placeholder="Email subject" />
      <PersonalizedTextField label="Preview text" value={metadata.preheader} onChange={(value) => props.onMetadata('preheader', value)} props={props} placeholder="Shown after the subject in inboxes" multiline />
    </Group>
    <PersonalizationPreview props={props} />
    <Group title="Email design">
      <div className="design-width-control">
        <div className="design-width-heading"><span>Content width</span><strong>{settings.content_width}px</strong></div>
        <div className="design-width-row">
          <input type="range" min="320" max="900" value={settings.content_width} onChange={(event) => props.onSetting('content_width', Number(event.target.value))} />
          <label className="design-width-value"><input aria-label="Content width" type="number" min="320" max="900" value={settings.content_width} onChange={(event) => props.onSetting('content_width', Number(event.target.value))} /><small>px</small></label>
        </div>
        <div className="design-width-limits"><span>320px</span><span>900px</span></div>
      </div>
      <div className="design-type-grid">
        <Field label="Font family"><SelectInput value={settings.font_family} onChange={(value) => props.onSetting('font_family', value)} options={[
          ['Arial, Helvetica, sans-serif', 'Arial'],
          ['Helvetica, Arial, sans-serif', 'Helvetica'],
          ['Georgia, Times New Roman, serif', 'Georgia'],
          ['Tahoma, Arial, sans-serif', 'Tahoma'],
          ['Verdana, Arial, sans-serif', 'Verdana'],
        ]} /></Field>
        <Field label="Base size"><LengthInput value={settings.font_size || '16px'} onChange={(value) => props.onSetting('font_size', value)} max={72} units={['px', 'pt']} /></Field>
      </div>
      <div className="appearance-color-grid template-color-grid">
        <AppearanceColorField label="Email background" value={settings.body_background} onChange={(value) => props.onSetting('body_background', value)} />
        <AppearanceColorField label="Content background" value={settings.content_background} onChange={(value) => props.onSetting('content_background', value)} />
        <AppearanceColorField label="Text color" value={settings.text_color} onChange={(value) => props.onSetting('text_color', value)} />
        <AppearanceColorField label="Link color" value={settings.link_color} onChange={(value) => props.onSetting('link_color', value)} />
      </div>
    </Group>
    <Group title="Button defaults">
      <div className="appearance-color-grid button-default-color-grid">
        <AppearanceColorField label="Button fill" value={settings.button_background} onChange={(value) => props.onSetting('button_background', value)} />
        <AppearanceColorField label="Button text" value={settings.button_text_color} onChange={(value) => props.onSetting('button_text_color', value)} />
      </div>
      <Field label="Corner radius"><LengthInput value={settings.button_radius || '4px'} onChange={(value) => props.onSetting('button_radius', value)} max={100} units={['px']} /></Field>
    </Group>
  </>
}

function DynamicFieldPicker({ block, props }: { block: BuilderBlock; props: InspectorProps }) {
  const [open, setOpen] = useState(false)
  const referenceDoctype = String(props.document.metadata.reference_doctype || '').trim()
  return <Group title="Dynamic fields">
    <p className="helper-text">Personalize this text with a readable field and an optional fallback value.</p>
    <button
      type="button"
      className="personalization-trigger"
      disabled={props.readOnly}
      onPointerDown={() => props.onPrepareMergeField(block.id)}
      onMouseDown={() => props.onPrepareMergeField(block.id)}
      onClick={() => setOpen((current) => !current)}
    ><Braces size={15} /><span>{referenceDoctype ? `Personalize with ${referenceDoctype}` : 'Set up personalization'}</span></button>
    {open && <PersonalizationDialog
      fields={props.mergeFields}
      referenceDoctype={referenceDoctype}
      loading={props.mergeFieldsLoading}
      error={props.mergeFieldsError}
      onConfigure={() => {
        setOpen(false)
        props.onConfigurePersonalization()
      }}
      onRetry={props.onRetryMergeFields}
      onInsert={(token) => {
        if (!props.onInsertMergeField(block.id, token)) {
          const current = String(block.content.html || '')
          const safeToken = escapeHtmlText(token)
          props.onNode({ kind: 'block', id: block.id }, 'content.html', current ? `${current} ${safeToken}` : `<p>${safeToken}</p>`)
        }
        setOpen(false)
      }}
      onClose={() => setOpen(false)}
    />}
  </Group>
}

function BlockContent({ block, props }: { block: BuilderBlock; props: InspectorProps }) {
  const update = (key: string, value: unknown) => props.onNode({ kind: 'block', id: block.id }, `content.${key}`, value)
  const content = block.content
  if (block.type === 'text') return <>
    <Group title="Text content">
      <p className="helper-text">Edit text here for quick copy changes, or use the canvas toolbar for headings, fonts, links, alignment, and lists.</p>
      <SidebarTextEditor value={content.html} readOnly={props.readOnly} onChange={(value) => update('html', value)} />
      <button type="button" className="secondary-button" onClick={() => props.onFocusText(block.id)}>Edit on canvas</button>
    </Group>
    <PersonalizationPreview props={props} />
    <DynamicFieldPicker block={block} props={props} />
  </>
  if (block.type === 'image') return <>
    <Group title="Image source">
      <div className="image-source-actions">
        <button type="button" className="button button--secondary" disabled={props.uploading} onClick={() => props.onChooseImage(block.id)}>Choose image</button>
        <label className="upload-control is-compact"><Upload size={16} /><span><strong>{props.uploading ? `Uploading ${props.uploadProgress}%` : 'Quick upload'}</strong><small>Optimized public upload</small>{props.uploading && <i className="upload-control-progress"><b style={{ width: `${props.uploadProgress}%` }} /></i>}</span><input type="file" accept="image/*" disabled={props.uploading} onChange={(event: ChangeEvent<HTMLInputElement>) => { const file = event.target.files?.[0]; if (file) props.onUploadImage(block.id, file); event.target.value = '' }} /></label>
      </div>
      <Field label="Image URL"><TextInput value={content.src} onChange={(value) => update('src', value)} placeholder="/files/image.png" /></Field>
      <PersonalizedTextField label="Alternative text" value={content.alt} onChange={(value) => update('alt', value)} props={props} />
      <Toggle label="Decorative image" checked={Boolean(content.decorative)} onChange={(value) => update('decorative', value)} />
      <PersonalizedTextField label="Click-through URL" value={content.href} onChange={(value) => update('href', value)} props={props} placeholder="https://example.com" />
    </Group>
    <Group title="Image size">
      <Toggle label="Fill available width" checked={!content.width} onChange={(value) => update('width', value ? undefined : 600)} />
      {!content.width && <p className="helper-text">The image scales to the column width. Any white border visible inside the picture is part of the uploaded image file.</p>}
      {Boolean(content.width) && <Field label="Image width"><NumberInput value={content.width} min={1} max={2000} suffix="px" onChange={(value) => update('width', value || undefined)} /></Field>}
      <Toggle label="Keep natural proportions" checked={content.preserve_aspect_ratio !== false} onChange={(value) => update('preserve_aspect_ratio', value)} />
      {content.preserve_aspect_ratio === false
        ? <Field label="Fixed height"><NumberInput value={content.height || 0} min={0} max={2000} suffix="px" onChange={(value) => update('height', value || undefined)} /></Field>
        : <p className="helper-text">Height is automatic while natural proportions are kept.</p>}
    </Group>
  </>
  if (block.type === 'button') return <Group title="Button action">
    <PersonalizedTextField label="Button text" value={content.text} onChange={(value) => update('text', value)} props={props} />
    <Field label="Action type"><SelectInput value={content.action || 'url'} onChange={(value) => update('action', value)} options={[['url', 'URL'], ['email', 'Email'], ['file', 'Public file'], ['telephone', 'Telephone'], ['sms', 'SMS']]} /></Field>
    <PersonalizedTextField label="Action value" value={content.href} onChange={(value) => update('href', value)} props={props} placeholder="https://example.com" />
    <Toggle label="Full-width button" checked={Boolean(content.full_width)} onChange={(value) => update('full_width', value)} />
  </Group>
  if (block.type === 'divider') return <Group title="Divider"><Field label="Line style"><SelectInput value={content.style || 'solid'} onChange={(value) => update('style', value)} options={[['solid', 'Solid'], ['dotted', 'Dotted'], ['dashed', 'Dashed']]} /></Field><Field label="Thickness"><NumberInput value={content.thickness || 1} min={1} max={20} suffix="px" onChange={(value) => update('thickness', value)} /></Field></Group>
  if (block.type === 'spacer') return <Group title="Spacer"><Field label="Height"><span className="range-row"><input type="range" min="1" max="300" value={Number(content.height || 24)} onChange={(event) => update('height', Number(event.target.value))} /><NumberInput value={content.height || 24} min={1} max={300} suffix="px" onChange={(value) => update('height', value)} /></span></Field></Group>
  if (block.type === 'preview_url') return <Group title="Browser view"><Field label="Link text"><TextInput value={content.text} onChange={(value) => update('text', value)} /></Field><p className="helper-text">The compiler hides this block when a preview URL is unavailable.</p></Group>
  if (block.type === 'code') return <Group title="Restricted HTML"><Field label="Email-safe HTML"><textarea className="code-input" rows={12} value={String(content.html || '')} onChange={(event) => update('html', event.target.value)} /></Field><p className="helper-text">Scripts, forms, iframes, external CSS, and unsafe URLs are removed server-side.</p></Group>
  const items = Array.isArray(content.items) ? content.items as Array<{ platform: string; href: string; label?: string }> : []
  const display = String(content.display || 'icon')
  const changeItem = (index: number, values: Partial<(typeof items)[number]>) => {
    update('items', items.map((current, itemIndex) => itemIndex === index ? { ...current, ...values } : current))
  }
  const reorderItem = (index: number, target: number) => {
    if (index < 0 || target < 0 || index >= items.length || target >= items.length || index === target) return
    const reordered = [...items]
    const [moved] = reordered.splice(index, 1)
    reordered.splice(target, 0, moved)
    update('items', reordered)
  }
  const moveItem = (index: number, offset: number) => reorderItem(index, index + offset)
  return <Group title="Social profiles">
    <p className="helper-text">Add up to 12 profiles. Their order here is the order recipients see.</p>
    <div className="eb-channel-editor">
      {items.map((item, index) => <article
        className="eb-channel-editor__item"
        key={`${item.platform}-${index}`}
        onDragOver={(event) => { event.preventDefault(); event.currentTarget.classList.add('is-drag-target') }}
        onDragLeave={(event) => event.currentTarget.classList.remove('is-drag-target')}
        onDrop={(event) => {
          event.preventDefault()
          event.currentTarget.classList.remove('is-drag-target')
          const source = event.dataTransfer.getData('application/x-email-builder-social-index')
          if (source !== '') reorderItem(Number(source), index)
        }}
      >
        <div className="eb-channel-editor__heading">
          <strong>{item.label || item.platform || `Profile ${index + 1}`}</strong>
          <span>
            <button type="button" className="eb-channel-drag" title="Drag to reorder" aria-label="Drag social profile to reorder" draggable onDragStart={(event) => {
              event.dataTransfer.effectAllowed = 'move'
              event.dataTransfer.setData('application/x-email-builder-social-index', String(index))
            }}><GripVertical size={13} /></button>
            <button type="button" title="Move up" aria-label="Move social profile up" disabled={index === 0} onClick={() => moveItem(index, -1)}><ChevronUp size={14} /></button>
            <button type="button" title="Move down" aria-label="Move social profile down" disabled={index === items.length - 1} onClick={() => moveItem(index, 1)}><ChevronDown size={14} /></button>
            <button type="button" title="Duplicate" aria-label="Duplicate social profile" disabled={items.length >= 12} onClick={() => update('items', [...items.slice(0, index + 1), { ...item }, ...items.slice(index + 1)])}><Copy size={13} /></button>
            <button type="button" className="is-danger" title="Delete" aria-label="Delete social profile" onClick={() => update('items', items.filter((_, itemIndex) => itemIndex !== index))}><Trash2 size={13} /></button>
          </span>
        </div>
        <div className="eb-channel-editor__fields">
          <Field label="Network"><SelectInput value={item.platform} onChange={(platform) => changeItem(index, { platform, label: !item.label || item.label === item.platform ? platform : item.label })} options={['Facebook', 'Instagram', 'LinkedIn', 'YouTube', 'X', 'TikTok', 'WhatsApp', 'Website'].map((name) => [name, name])} /></Field>
          {(display === 'text' || display === 'both') && <Field label="Label"><TextInput value={item.label || item.platform} onChange={(label) => changeItem(index, { label })} /></Field>}
          <Field label="Profile URL"><TextInput value={item.href} onChange={(href) => changeItem(index, { href })} placeholder="https://" /></Field>
        </div>
      </article>)}
      {!items.length && <div className="eb-channel-editor__empty">No social profiles yet.</div>}
    </div>
    <button type="button" className="secondary-button" disabled={items.length >= 12} onClick={() => update('items', [...items, { platform: 'LinkedIn', href: 'https://', label: 'LinkedIn' }])}><Plus size={14} /> Add social profile</button>
  </Group>
}

function StyleInspector({ selection, style = {}, blockType, props }: { selection: NonNullable<Selection>; style?: NodeStyle; blockType?: string; props: InspectorProps }) {
  const set = (key: string, value: unknown) => props.onNode(selection, `style.${key}`, value)
  const isBlock = selection.kind === 'block'
  const type = isBlock ? blockType : undefined
  const hasBorder = Boolean(style.border_width && !['0', '0px'].includes(style.border_width))

  const spacingGroup = <Group title="Spacing">
    <SpacingEditor key={`${selection.kind}:${selection.id}:padding`} label="Padding" value={style.padding} onChange={(value) => set('padding', value)} />
    <SpacingEditor key={`${selection.kind}:${selection.id}:margin`} label="Margin" value={style.margin} onChange={(value) => set('margin', value)} />
  </Group>

  const widthField = (label = 'Width', fallback = '100%') => <Field label={label} hint="Use 100% to fill the available column."><LengthInput value={style.width || fallback} onChange={(value) => set('width', value)} fallback={fallback} units={['%', 'px']} /></Field>
  const radiusField = (label = 'Corner radius') => <Field label={label}><LengthInput value={style.radius || '0px'} onChange={(value) => set('radius', value)} max={500} /></Field>
  const borderGroup = <Group title="Border">
    <Toggle label="Show border" checked={hasBorder} onChange={(visible) => set('border_width', visible ? '1px' : '')} />
    {hasBorder && <div className="border-controls">
      <Field label="Thickness"><LengthInput value={style.border_width} onChange={(value) => set('border_width', value)} max={40} units={['px']} /></Field>
      <Field label="Style"><SelectInput value={style.border_style || 'solid'} onChange={(value) => set('border_style', value)} options={[["solid", "Solid"], ["dashed", "Dashed"], ["dotted", "Dotted"]]} /></Field>
      <ColorField label="Color" value={style.border_color || '#d1d5db'} onChange={(value) => set('border_color', value)} />
    </div>}
  </Group>
  const typographyFields = <div className="appearance-type-grid">
    <Field label="Font size"><LengthInput value={style.font_size || props.document.schema.settings.font_size || '16px'} onChange={(value) => set('font_size', value)} max={144} /></Field>
    <Field label="Weight"><SelectInput value={style.font_weight || 'normal'} onChange={(value) => set('font_weight', value)} options={[["normal", "Regular"], ["500", "Medium"], ["600", "Semibold"], ["bold", "Bold"]]} /></Field>
  </div>

  if (type === 'divider') return <>
    <Group title="Line appearance">
      <div className="appearance-color-grid is-single">
        <AppearanceColorField label="Line color" value={style.border_color || props.document.schema.settings.link_color} onChange={(value) => set('border_color', value)} />
      </div>
      <AlignmentControl value={style.align || 'center'} onChange={(value) => set('align', value)} />
      {widthField('Line width', '100%')}
    </Group>
    {spacingGroup}
  </>

  if (type === 'image') return <>
    <Group title="Image frame">
      <div className="appearance-color-grid is-single">
        <AppearanceColorField label="Background" value={style.background || '#ffffff'} onChange={(value) => set('background', value)} />
      </div>
      <p className="helper-text">Background is visible around the image when padding or a smaller image width leaves breathing room.</p>
      <AlignmentControl value={style.align || 'left'} onChange={(value) => set('align', value)} />
      {widthField('Frame width', '100%')}
      {radiusField('Image corner radius')}
    </Group>
    {spacingGroup}
    {borderGroup}
  </>

  if (type === 'spacer') return <>
    <Group title="Frame">
      <div className="appearance-color-grid is-single">
        <AppearanceColorField label="Background" value={style.background || '#ffffff'} onChange={(value) => set('background', value)} />
      </div>
    </Group>
    {spacingGroup}
  </>

  if (type === 'social') {
    const useOfficialColors = !style.color
    const content = findSelected(props.document.schema, selection) as BuilderBlock | null
    const display = String(content?.content.display || 'icon')
    const setContent = (key: string, value: unknown) => props.onNode(selection, `content.${key}`, value)
    return <>
      <Group title="Display">
        <Field label="Show"><SelectInput value={display} onChange={(value) => setContent('display', value)} options={[['icon', 'Icons'], ['text', 'Text'], ['both', 'Icons and text']]} /></Field>
        {display !== 'text' && <>
          <Field label="Icon shape"><SelectInput value={content?.content.icon_shape || 'circle'} onChange={(value) => setContent('icon_shape', value)} options={[['circle', 'Circle'], ['rounded', 'Rounded square'], ['square', 'Square']]} /></Field>
          <Field label="Icon size">
            <span className="range-row"><input type="range" min="12" max="64" value={Number(content?.content.icon_size || 24)} onChange={(event) => setContent('icon_size', Number(event.target.value))} /><NumberInput value={content?.content.icon_size || 24} min={12} max={64} suffix="px" onChange={(value) => setContent('icon_size', value)} /></span>
          </Field>
        </>}
        <Field label="Profile spacing"><NumberInput value={content?.content.item_spacing ?? 8} min={0} max={40} suffix="px" onChange={(value) => setContent('item_spacing', value)} /></Field>
      </Group>
      {display !== 'text' && <Group title="Icon colors">
        <Toggle label="Use official platform colors" checked={useOfficialColors} onChange={(value) => set('color', value ? '' : '#2563eb')} />
        {!useOfficialColors && <div className="appearance-color-grid is-single">
          <AppearanceColorField label="Icon color" value={style.color || '#2563eb'} onChange={(value) => set('color', value)} />
        </div>}
        <p className="helper-text">Turn this off only when every social icon should use one shared brand color.</p>
      </Group>}
      <Group title="Placement">
        <AlignmentControl value={style.align || 'left'} onChange={(value) => set('align', value)} />
        {display !== 'icon' && <div className="appearance-color-grid is-single">
          <AppearanceColorField label="Text color" value={style.font_color || props.document.schema.settings.link_color} onChange={(value) => set('font_color', value)} />
        </div>}
      </Group>
      {spacingGroup}
    </>
  }

  if (type === 'button') return <>
    <Group title="Button appearance">
      <div className="appearance-color-grid">
        <AppearanceColorField label="Button fill" value={style.button_background || props.document.schema.settings.button_background} onChange={(value) => set('button_background', value)} />
        <AppearanceColorField label="Button text" value={style.button_text_color || props.document.schema.settings.button_text_color} onChange={(value) => set('button_text_color', value)} />
      </div>
      <AlignmentControl value={style.align || 'left'} onChange={(value) => set('align', value)} />
      {typographyFields}
    </Group>
    {spacingGroup}
    <Group title="Button shape">
      <p className="helper-text">To make the button fill the column, use Content → Full-width button.</p>
      <Field label="Corner style">
        <span style={{ display: 'flex', gap: '4px' }}>
          <SelectInput
            value={['0px', '4px', '9999px', ''].includes(style.radius ?? '') ? (style.radius || '') : 'custom'}
            onChange={(value) => set('radius', value === 'custom' ? '8px' : value)}
            options={[["", "Default"], ["0px", "Square"], ["4px", "Rounded"], ["9999px", "Pill"], ["custom", "Custom"]]}
          />
          {!['0px', '4px', '9999px', ''].includes(style.radius ?? '') && <TextInput value={style.radius || ''} onChange={(value) => set('radius', value)} placeholder="8px" />}
        </span>
      </Field>
    </Group>
    {borderGroup}
  </>

  if (type === 'code') return <>
    <Group title="HTML block frame">
      <div className="appearance-color-grid is-single">
        <AppearanceColorField label="Background" value={style.background || '#ffffff'} onChange={(value) => set('background', value)} />
      </div>
      <AlignmentControl value={style.align || 'left'} onChange={(value) => set('align', value)} />
      {widthField('Block width', '100%')}
      {radiusField()}
    </Group>
    {spacingGroup}
    {borderGroup}
  </>

  return <>
    <Group title="Appearance">
      <div className="appearance-color-grid">
        <AppearanceColorField label="Background" value={style.background || '#ffffff'} onChange={(value) => set('background', value)} />
        <AppearanceColorField label="Text color" value={style.color || style.font_color || '#1f2937'} onChange={(value) => set('color', value)} />
      </div>
      <AlignmentControl value={style.align || 'left'} onChange={(value) => set('align', value)} />
      {typographyFields}
    </Group>
    {spacingGroup}
    {isBlock && <>
      <Group title="Size">
        {widthField()}
        {radiusField()}
      </Group>
      {borderGroup}
    </>}
  </>
}

function DeviceVisibilityControl({ value, onChange }: { value: Visibility['device']; onChange: (value: Visibility['device']) => void }) {
  const options: Array<{ value: Visibility['device']; label: string; icon: ReactNode }> = [
    { value: 'both', label: 'All devices', icon: <span className="device-icon-pair"><Monitor size={15} /><Smartphone size={12} /></span> },
    { value: 'desktop', label: 'Desktop', icon: <Monitor size={16} /> },
    { value: 'mobile', label: 'Mobile', icon: <Smartphone size={16} /> },
  ]
  return <div className="device-visibility-field">
    <span>Show on</span>
    <div className="device-visibility-control" role="group" aria-label="Device visibility">
      {options.map((option) => <button type="button" key={option.value} className={value === option.value ? 'is-active' : ''} aria-pressed={value === option.value} onClick={() => onChange(option.value)}><i>{option.icon}</i><span>{option.label}</span></button>)}
    </div>
  </div>
}

function ConditionValueControl({ condition, field, onChange }: { condition: VisibilityCondition; field?: MergeField; onChange: (value: string) => void }) {
  const operator = condition.operator || defaultConditionOperator(field)
  if (!conditionNeedsValue(operator)) {
    return <div className="condition-rule__value condition-rule__value--static"><span>Value</span><strong>No value needed</strong></div>
  }

  const options = conditionFieldOptions(field)
  if (isCheckField(field)) {
    return <label className="condition-rule__value"><span>Value</span><select value={condition.value || '1'} onChange={(event) => onChange(event.target.value)}>
      <option value="1">Checked / Yes</option>
      <option value="0">Unchecked / No</option>
    </select></label>
  }

  if ((isSelectField(field) || isMultiSelectField(field)) && options.length) {
    const value = condition.value || ''
    const includeCurrentValue = value && !options.some((option) => option.value === value)
    return <label className="condition-rule__value"><span>Value</span><select value={value} onChange={(event) => onChange(event.target.value)}>
      <option value="" disabled>Choose value</option>
      {includeCurrentValue && <option value={value}>{value}</option>}
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select></label>
  }

  if (field?.fieldtype === 'Link' && field.options) {
    return <div className="condition-rule__value"><span>Value</span><FrappeLinkInput
      doctype={field.options}
      value={condition.value || ''}
      placeholder={`Select ${field.label}`}
      onChange={onChange}
    /></div>
  }

  return <label className="condition-rule__value"><span>Value</span><input value={condition.value || ''} placeholder={isMultiSelectField(field) ? 'Value contained in list' : 'Value to match'} onChange={(event) => onChange(event.target.value)} /></label>
}

type ConditionRuleEditorProps = {
  condition: VisibilityCondition
  index: number
  referenceDoctype: string
  rootFields: MergeField[]
  fieldsLoading: boolean
  fieldsError: unknown
  inspector: InspectorProps
  onUpdate: (index: number, patch: Partial<VisibilityCondition>, field?: MergeField) => void
  onRemove: (index: number) => void
}

function ConditionRuleEditor({
  condition,
  index,
  referenceDoctype,
  rootFields,
  fieldsLoading,
  fieldsError,
  inspector,
  onUpdate,
  onRemove,
}: ConditionRuleEditorProps) {
  const [pickerOpen, setPickerOpen] = useState(false)
  const path = String(condition.fieldname || '').trim()
  const [rootFieldname, relatedFieldname] = path.split('.')
  const rootField = rootFields.find((field) => field.fieldname === rootFieldname)
  const relatedParams = relatedFieldname && rootField?.fieldtype === 'Link'
    ? { reference_doctype: referenceDoctype, link_fieldname: rootFieldname }
    : undefined
  const relatedFields = useFrappeGetCall<ApiResponse<LinkMergeFieldsResponse>>(
    API_METHODS.linkMergeFields,
    relatedParams,
    relatedParams ? makeCallKey(API_METHODS.linkMergeFields, relatedParams) : null,
    { shouldRetryOnError: false, revalidateOnFocus: false },
  )
  const selectedField = relatedFieldname
    ? relatedFields.data?.message?.fields.find((field) => field.fieldname === path)
    : rootField
  const normalized = normalizeConditionForField(condition, selectedField)
  const operatorOptions = conditionOperatorOptions(selectedField)
  const needsValue = conditionNeedsValue(normalized.operator)
  const resolvingRelated = Boolean(relatedParams && relatedFields.isLoading)
  const missingField = Boolean(path)
    && !fieldsLoading
    && !resolvingRelated
    && (!selectedField || Boolean(relatedFields.error))
  const missingValue = needsValue && !String(normalized.value || '').trim()
  const relatedLabel = relatedFieldname && rootField && selectedField
    ? `${rootField.label} → ${selectedField.label}`
    : selectedField?.label

  return <div className={[
    'condition-rule',
    missingField || missingValue ? 'has-warning' : '',
    missingField ? 'has-missing-field' : '',
    missingValue ? 'has-missing-value' : '',
  ].filter(Boolean).join(' ')}>
    <div className="condition-rule__field">
      <span><b>Field</b>{selectedField && <small className="condition-field-meta">{selectedField.fieldtype}</small>}</span>
      <button
        type="button"
        className="condition-field-trigger"
        disabled={inspector.readOnly || fieldsLoading || Boolean(fieldsError)}
        aria-haspopup="dialog"
        aria-expanded={pickerOpen}
        onClick={() => setPickerOpen(true)}
        title={relatedLabel || path || 'Choose condition field'}
      >
        <i>{relatedFieldname ? <Link2 size={14} /> : <Database size={14} />}</i>
        <span>
          <strong>{relatedLabel || (resolvingRelated ? 'Loading related field…' : path || 'Choose field')}</strong>
          <small>{path || 'Select a readable field'}</small>
        </span>
        <ChevronDown size={14} />
      </button>
      {pickerOpen && <PersonalizationDialog
        mode="field"
        fields={rootFields}
        referenceDoctype={referenceDoctype}
        loading={fieldsLoading}
        error={fieldsError}
        onConfigure={() => {
          setPickerOpen(false)
          inspector.onConfigurePersonalization()
        }}
        onRetry={inspector.onRetryMergeFields}
        onSelectField={(field) => {
          onUpdate(index, { fieldname: field.fieldname }, field)
          setPickerOpen(false)
        }}
        onClose={() => setPickerOpen(false)}
      />}
    </div>
    <label className="condition-rule__operator"><span><b>Operator</b></span><select value={normalized.operator} disabled={inspector.readOnly || resolvingRelated} onChange={(event) => onUpdate(index, { operator: event.target.value as VisibilityCondition['operator'] }, selectedField)}>
      {operatorOptions.map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select></label>
    <ConditionValueControl condition={normalized} field={selectedField} onChange={(value) => onUpdate(index, { value }, selectedField)} />
    <button type="button" className="condition-remove" disabled={inspector.readOnly} onClick={() => onRemove(index)} title="Remove condition" aria-label="Remove condition"><Trash2 size={14} /></button>
    {(missingField || missingValue) && <small className="condition-rule-warning">{missingField ? 'This field path is unavailable or not readable for the selected Reference DocType.' : 'Choose a value or use an empty/not-empty operator.'}</small>}
  </div>
}

function RecordConditionsEditor({ selection, visibility, props }: { selection: NonNullable<Selection>; visibility: Visibility; props: InspectorProps }) {
  const referenceDoctype = String(props.document.metadata.reference_doctype || '').trim()
  const conditions = Array.isArray(visibility.conditions) ? visibility.conditions : []
  const readableFields = props.mergeFields
  const setConditions = (next: VisibilityCondition[]) => props.onNode(selection, 'visibility.conditions', next)
  const setMatch = (next: string) => props.onNode(selection, 'visibility.match', next)
  const updateCondition = (index: number, patch: Partial<VisibilityCondition>, selectedField?: MergeField) => {
    const next = conditions.map((condition, currentIndex) => {
      if (currentIndex !== index) return condition
      const resolvedField = selectedField || readableFields.find((field) => field.fieldname === String(patch.fieldname ?? condition.fieldname ?? ''))
      const base = patch.fieldname
        ? { ...condition, fieldname: patch.fieldname, operator: defaultConditionOperator(resolvedField), value: defaultConditionValue(resolvedField) }
        : { ...condition, ...patch }
      return normalizeConditionForField(base, resolvedField)
    })
    setConditions(next)
  }
  const removeCondition = (index: number) => setConditions(conditions.filter((_, currentIndex) => currentIndex !== index))
  const addCondition = () => {
    const firstField = readableFields[0]
    if (!firstField || conditions.length >= 5) return
    setConditions([...conditions, { fieldname: firstField.fieldname, operator: defaultConditionOperator(firstField), value: defaultConditionValue(firstField) }])
  }
  const canAdd = Boolean(referenceDoctype) && !props.mergeFieldsLoading && !Boolean(props.mergeFieldsError) && readableFields.length > 0 && conditions.length < 5

  return <Group title="Record conditions">
    <p className="helper-text">Show this {selection.kind === 'section' ? 'row' : 'block'} only when the selected record matches your rules. Up to five rules are compiled into safe Jinja.</p>
    <Field label="Rule matching"><SelectInput value={visibility.match} onChange={setMatch} options={[['all', 'Match all rules'], ['any', 'Match any rule']]} /></Field>
    {!referenceDoctype && <div className="condition-empty-state">Choose a <strong>Reference DocType</strong> in Template settings before adding record conditions.</div>}
    {referenceDoctype && Boolean(props.mergeFieldsError) && <div className="condition-empty-state is-error">Could not load readable fields from <strong>{referenceDoctype}</strong>. {getErrorMessage(props.mergeFieldsError, 'Please retry.')}</div>}
    {referenceDoctype && props.mergeFieldsLoading && <div className="condition-empty-state">Loading readable fields from <strong>{referenceDoctype}</strong>…</div>}
    {referenceDoctype && !props.mergeFieldsLoading && !Boolean(props.mergeFieldsError) && readableFields.length === 0 && <div className="condition-empty-state">No readable scalar fields are available for <strong>{referenceDoctype}</strong>.</div>}
    {conditions.length > 0 && <div className="condition-list">
      {conditions.map((condition, index) => <ConditionRuleEditor
        key={`${condition.fieldname}-${index}`}
        condition={condition}
        index={index}
        referenceDoctype={referenceDoctype}
        rootFields={readableFields}
        fieldsLoading={props.mergeFieldsLoading}
        fieldsError={props.mergeFieldsError}
        inspector={props}
        onUpdate={updateCondition}
        onRemove={removeCondition}
      />)}
    </div>}
    {conditions.length === 0 && referenceDoctype && !props.mergeFieldsLoading && !Boolean(props.mergeFieldsError) && readableFields.length > 0 && <div className="condition-summary">No record conditions yet. Add one to make this content conditional.</div>}
    <div className="condition-footer"><button type="button" className="secondary-button condition-add" onClick={addCondition} disabled={!canAdd}><Plus size={14} /> Add condition</button><span>{conditions.length}/5 rules</span></div>
  </Group>
}

function VisibilityInspector({ selection, visibility, props }: { selection: NonNullable<Selection>; visibility?: Visibility; props: InspectorProps }) {
  const value = visibility || { device: 'both', match: 'all', conditions: [] }
  const set = (key: string, next: unknown) => props.onNode(selection, `visibility.${key}`, next)
  return <>
    <Group title="Device visibility"><DeviceVisibilityControl value={value.device} onChange={(next) => set('device', next)} /></Group>
    <RecordConditionsEditor selection={selection} visibility={value} props={props} />
  </>
}

function ColumnWidthEditor({ section, props }: { section: BuilderSection; props: InspectorProps }) {
  const layout = LAYOUTS.find((item) => item.value === section.layout) || LAYOUTS[0]
  const widths = normalizeColumnWidths(section.column_widths, section.columns.length, layout.widths)
  if (widths.length < 2) return null
  return <div className="column-width-editor">
    <div className="column-width-heading"><span>Column widths</span><button type="button" onClick={() => props.onColumnWidths(section.id, normalizeColumnWidths(layout.widths, layout.widths.length))}>Reset</button></div>
    <p className="helper-text">Drag a divider on the canvas or enter an exact percentage. Other columns rebalance automatically.</p>
    <div className="column-width-grid">
      {widths.map((width, index) => <label key={section.columns[index].id}><span>Column {index + 1}</span><span><input type="number" min={8} max={100 - 8 * (widths.length - 1)} step={1} value={Number(width.toFixed(1))} onChange={(event) => props.onColumnWidths(section.id, rebalanceColumnWidths(widths, index, Number(event.target.value)))} /><small>%</small></span></label>)}
    </div>
  </div>
}

function LayoutPicker({ section, onChange }: { section: BuilderSection; onChange: (layout: LayoutType) => void }) {
  return <div className="layout-picker" role="radiogroup" aria-label="Row columns">
    {LAYOUTS.map((layout) => <button type="button" role="radio" aria-checked={section.layout === layout.value} key={layout.value} className={section.layout === layout.value ? 'is-active' : ''} onClick={() => onChange(layout.value)} title={layout.label}>
      <span className="layout-picker-diagram">{layout.widths.map((width, index) => <i key={index} style={{ flexGrow: width }} />)}</span>
      <small>{layout.label}</small>
    </button>)}
  </div>
}

export const Inspector = memo(function Inspector(props: InspectorProps) {
  const selected = findSelected(props.document.schema, props.selection)
  const block = props.selection?.kind === 'block' ? selected as BuilderBlock : null
  const title = !props.selection ? 'Template settings' : props.selection.kind === 'block' ? BLOCKS.find((item) => item.type === block?.type)?.label || 'Content block' : props.selection.kind === 'section' ? 'Row settings' : 'Column settings'
  return (
    <aside className={`builder-inspector${props.open ? ' is-open' : ''}${props.selection ? ' has-selection' : ''}${props.readOnly ? ' is-read-only' : ''}${props.selection && props.selection.kind !== 'column' && !props.readOnly ? ' has-actions' : ''}`}>
      <header className="inspector-header"><div><small>{!props.selection ? 'Email' : props.selection.kind}</small><strong>{title}</strong></div><button type="button" className="icon-button" onClick={props.onClose} aria-label="Close inspector"><X size={17} /></button></header>
      {props.readOnly && <div className="read-only-inspector-note"><strong>Read-only</strong><span>Inspect settings safely. Unlock visual editing before making changes.</span></div>}
      {!props.selection ? <div className="inspector-scroll"><fieldset className="inspector-fieldset" disabled={props.readOnly}><TemplateInspector props={props} /></fieldset></div> : <>
        <nav className="inspector-tabs">{(['content', 'style', 'visibility'] as InspectorTab[]).map((tab) => <button type="button" key={tab} className={props.tab === tab ? 'is-active' : ''} onClick={() => props.onTab(tab)}>{tab}</button>)}</nav>
        <div className="inspector-scroll"><fieldset className="inspector-fieldset" disabled={props.readOnly}>
          {props.tab === 'content' && block && <BlockContent block={block} props={props} />}
          {props.tab === 'content' && props.selection.kind === 'section' && selected && 'layout' in selected && <Group title="Row structure"><p className="helper-text">Choose a structure at any time. Existing content is preserved when columns are added or removed.</p><LayoutPicker section={selected} onChange={(layout) => props.onLayout(selected.id, layout)} /><ColumnWidthEditor section={selected} props={props} /><Field label="Vertical alignment"><SelectInput value={selected.vertical_align} onChange={(value) => props.onNode(props.selection!, 'vertical_align', value)} options={[['top', 'Top'], ['middle', 'Middle'], ['bottom', 'Bottom']]} /></Field><Field label="Mobile stacking"><SelectInput value={selected.mobile_stack} onChange={(value) => props.onNode(props.selection!, 'mobile_stack', value)} options={[['stack', 'Left on top'], ['reverse', 'Right on top'], ['none', 'Keep columns']]} /></Field></Group>}
          {props.tab === 'content' && props.selection.kind === 'column' && <Group title="Column"><p className="helper-text">Drop modules here, or select this column before clicking a module in the library.</p></Group>}
          {props.tab === 'style' && selected && <StyleInspector selection={props.selection} style={selected.style} blockType={block?.type} props={props} />}
          {props.tab === 'visibility' && selected && 'visibility' in selected && <VisibilityInspector selection={props.selection} visibility={selected.visibility} props={props} />}
        </fieldset></div>
        {!props.readOnly && props.selection.kind !== 'column' && <footer className="inspector-actions"><button type="button" className="button button--secondary" onClick={() => props.onDuplicate(props.selection!)}><Copy size={15} /> Duplicate</button><button type="button" className="button button--danger" onClick={() => props.onDelete(props.selection!)}><Trash2 size={15} /> Delete</button></footer>}
      </>}
    </aside>
  )
})

export type { InspectorTab }
