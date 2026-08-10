import { memo, useEffect, useMemo, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useFrappeGetCall } from 'frappe-react-sdk'
import { ArrowLeft, Braces, ChevronRight, Database, Link2, RotateCw, Search, X } from 'lucide-react'

import { API_METHODS, makeCallKey } from '../lib/api'
import { buildMergeToken } from '../lib/tokens'
import type { ApiResponse, LinkMergeFieldsResponse, MergeField } from '../types'

export type PersonalizationPickerProps = {
  fields: MergeField[]
  referenceDoctype: string
  loading?: boolean
  error?: unknown
  onConfigure: () => void
  onRetry: () => void
  mode?: 'personalization' | 'field'
  onInsert?: (token: string, field: MergeField) => void
  onSelectField?: (field: MergeField) => void
  onClose?: () => void
  compact?: boolean
}

type PersonalizationDialogProps = Omit<PersonalizationPickerProps, 'compact' | 'onClose'> & {
  onClose: () => void
}

function typeLabel(field: MergeField) {
  if (field.fieldname.endsWith('.name') || field.fieldname === 'name') return 'Record ID'
  if (field.fieldtype === 'Check') return 'Yes / No'
  if (field.fieldtype === 'Datetime') return 'Date & time'
  if (field.fieldtype === 'Link') return field.options ? `Related · ${field.options}` : 'Related record'
  return field.fieldtype || 'Text'
}

export const PersonalizationPicker = memo(function PersonalizationPicker({
  fields,
  referenceDoctype,
  loading = false,
  error,
  onConfigure,
  onRetry,
  mode = 'personalization',
  onInsert,
  onSelectField,
  onClose,
  compact = false,
}: PersonalizationPickerProps) {
  const searchRef = useRef<HTMLInputElement>(null)
  const [query, setQuery] = useState('')
  const [selectedFieldname, setSelectedFieldname] = useState('')
  const [fallback, setFallback] = useState('')
  const [linkField, setLinkField] = useState<MergeField | null>(null)

  const linkParams = useMemo(
    () => linkField ? { reference_doctype: referenceDoctype, link_fieldname: linkField.fieldname } : undefined,
    [linkField, referenceDoctype],
  )
  const linkedFields = useFrappeGetCall<ApiResponse<LinkMergeFieldsResponse>>(
    API_METHODS.linkMergeFields,
    linkParams,
    linkParams ? makeCallKey(API_METHODS.linkMergeFields, linkParams) : null,
    { shouldRetryOnError: false, revalidateOnFocus: false },
  )

  useEffect(() => {
    searchRef.current?.focus({ preventScroll: true })
  }, [])

  useEffect(() => {
    setQuery('')
    setSelectedFieldname('')
    setFallback('')
    setLinkField(null)
  }, [referenceDoctype])

  const linkedFieldRows = useMemo(() => {
    if (!linkField) return []
    const related = linkedFields.data?.message?.fields || []
    return [
      {
        ...linkField,
        // Visibility rules keep Link metadata so the value editor can use
        // Frappe's record search. Personalization only needs the record ID.
        fieldtype: mode === 'field' ? linkField.fieldtype : 'Data',
        options: mode === 'field' ? linkField.options : '',
        label: `${linkField.label} record ID`,
      },
      ...related.filter((field) => field.fieldname !== `${linkField.fieldname}.name`),
    ]
  }, [linkField, linkedFields.data?.message?.fields, mode])
  const availableFields = linkField ? linkedFieldRows : fields

  const filteredFields = useMemo(() => {
    const needle = query.trim().toLocaleLowerCase()
    if (!needle) return availableFields
    return availableFields.filter((field) =>
      `${field.label} ${field.fieldname} ${field.fieldtype} ${field.options || ''}`.toLocaleLowerCase().includes(needle),
    )
  }, [availableFields, query])

  const selectedField = availableFields.find((field) => field.fieldname === selectedFieldname)
  const displayType = (field: MergeField) => (
    linkField && field.fieldname === linkField.fieldname ? 'Record ID' : typeLabel(field)
  )
  const insert = () => {
    if (!selectedField || !onInsert) return
    onInsert(buildMergeToken(selectedField.fieldname, fallback), selectedField)
    setFallback('')
    setSelectedFieldname('')
  }
  const browseLink = (field: MergeField) => {
    setLinkField(field)
    setSelectedFieldname('')
    setFallback('')
    setQuery('')
  }
  const backToFields = () => {
    if (selectedFieldname) {
      setSelectedFieldname('')
      setFallback('')
      return
    }
    setLinkField(null)
    setQuery('')
  }
  const browsingTitle = linkField
    ? linkField.label
    : `${referenceDoctype} fields`
  const relatedLoading = Boolean(linkField && linkedFields.isLoading)
  const relatedError = linkField ? linkedFields.error : null
  const chooseField = (field: MergeField) => {
    if (!linkField && field.fieldtype === 'Link' && field.options) {
      browseLink(field)
      return
    }
    if (mode === 'field') {
      onSelectField?.(field)
      return
    }
    setSelectedFieldname(field.fieldname)
  }
  const pickerLabel = mode === 'field' ? 'Choose condition field' : 'Insert personalization'

  return (
    <section className={`personalization-picker${compact ? ' is-compact' : ''}`} aria-label={pickerLabel}>
      <header>
        <span>{mode === 'field' ? <Database size={16} /> : <Braces size={16} />}<strong>{pickerLabel}</strong></span>
        {onClose && <button type="button" className="personalization-picker__close" aria-label={`Close ${pickerLabel.toLowerCase()}`} onClick={onClose}><X size={15} /></button>}
      </header>

      {!referenceDoctype ? (
        <div className="personalization-picker__empty">
          <strong>Choose the data source first</strong>
          <span>Select a Reference DocType to use its readable fields safely.</span>
          <button type="button" className="button button--secondary" onClick={onConfigure}>Choose Reference DocType</button>
        </div>
      ) : error || relatedError ? (
        <div className="personalization-picker__empty is-error">
          {linkField && (
            <button type="button" className="personalization-picker__back" onClick={backToFields}>
              <ArrowLeft size={14} /> All {referenceDoctype} fields
            </button>
          )}
          <strong>Fields could not be loaded</strong>
          <span>Check your permission to read {linkField?.options || referenceDoctype}, then try again.</span>
          <button type="button" className="button button--secondary" onClick={() => {
            if (linkField) void linkedFields.mutate()
            else onRetry()
          }}><RotateCw size={14} /> Retry</button>
        </div>
      ) : loading || relatedLoading ? (
        <div className="personalization-picker__loading" aria-label="Loading personalization fields">
          <i /><i /><i />
        </div>
      ) : mode === 'personalization' && selectedField ? (
        <div className="personalization-picker__configure">
          <button type="button" className="personalization-picker__back" onClick={backToFields}>
            <ArrowLeft size={14} /> Choose another field
          </button>
          <div className="personalization-picker__selection">
            <span className="personalization-picker__selection-icon">
              {selectedField.fieldname.includes('.') ? <Link2 size={16} /> : <Database size={16} />}
            </span>
            <span>
              <strong>{selectedField.label}</strong>
              <small>{selectedField.fieldname.includes('.') ? `${linkField?.label} → ${selectedField.label}` : `${referenceDoctype} → ${selectedField.label}`}</small>
            </span>
            <em>{displayType(selectedField)}</em>
          </div>
          <div className="personalization-picker__token">
            <span>Token</span>
            <code>{`{{ ${selectedField.fieldname} }}`}</code>
          </div>
          <label className="personalization-picker__fallback-field">
            <span>Fallback value <small>Recommended</small></span>
            <input
              autoFocus
              value={fallback}
              placeholder={`Used when ${selectedField.label} is empty`}
              onChange={(event) => setFallback(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault()
                  insert()
                }
              }}
            />
          </label>
          <button type="button" className="button button--primary personalization-picker__insert" onClick={insert}>Insert personalization</button>
        </div>
      ) : (
        <>
          {linkField && (
            <button type="button" className="personalization-picker__back" onClick={backToFields}>
              <ArrowLeft size={14} /> All {referenceDoctype} fields
            </button>
          )}
          <div className="personalization-picker__context">
            <span>{linkField ? <Link2 size={14} /> : <Database size={14} />}</span>
            <div>
              <strong>{browsingTitle}</strong>
              <small>{linkField ? `Choose a field from the linked ${linkField.options} record` : 'Current email record'}</small>
            </div>
          </div>
          <label className="personalization-picker__search">
            <Search size={15} />
            <input
              ref={searchRef}
              value={query}
              placeholder={`Search ${browsingTitle}`}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>

          <div className="personalization-picker__fields" role="listbox" aria-label={browsingTitle}>
            {filteredFields.map((field) => (
              <button
                type="button"
                role="option"
                aria-selected={selectedFieldname === field.fieldname}
                className={[
                  selectedFieldname === field.fieldname ? 'is-selected' : '',
                  !linkField && field.fieldtype === 'Link' && field.options ? 'is-related' : '',
                ].filter(Boolean).join(' ')}
                key={field.fieldname}
                title={`${field.label} (${field.fieldname})`}
                onClick={() => chooseField(field)}
              >
                <span><strong>{field.label}</strong><small>{field.fieldname}</small></span>
                <span className="personalization-picker__field-meta">
                  <em>{displayType(field)}</em>
                  {!linkField && field.fieldtype === 'Link' && field.options && (
                    <span className="personalization-picker__field-arrow" aria-hidden="true">
                      <ChevronRight size={14} />
                    </span>
                  )}
                </span>
              </button>
            ))}
            {!filteredFields.length && <div className="personalization-picker__no-results">No fields match “{query}”.</div>}
          </div>
        </>
      )}
    </section>
  )
})

export const PersonalizationDialog = memo(function PersonalizationDialog({
  onClose,
  ...props
}: PersonalizationDialogProps) {
  useEffect(() => {
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key !== 'Escape') return
      event.preventDefault()
      onClose()
    }
    document.addEventListener('keydown', closeOnEscape)
    return () => document.removeEventListener('keydown', closeOnEscape)
  }, [onClose])

  return createPortal(
    <div
      className="personalization-dialog-backdrop"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="personalization-dialog" role="dialog" aria-modal="true" aria-label={props.mode === 'field' ? 'Choose condition field' : 'Insert personalization'}>
        <PersonalizationPicker {...props} compact onClose={onClose} />
      </div>
    </div>,
    document.body,
  )
})
