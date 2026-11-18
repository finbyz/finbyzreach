import type {
  BlockType,
  BuilderBlock,
  BuilderColumn,
  BuilderDocument,
  BuilderSchema,
  BuilderSection,
  BuilderSettings,
  LayoutType,
  NodeStyle,
  Selection,
  Visibility,
} from '../types'

export const LAYOUTS: Array<{ value: LayoutType; label: string; widths: number[] }> = [
  { value: '1', label: '1 column', widths: [1] },
  { value: '1/2:1/2', label: '1/2 + 1/2', widths: [1, 1] },
  { value: '1/3:1/3:1/3', label: '1/3 + 1/3 + 1/3', widths: [1, 1, 1] },
  { value: '1/3:2/3', label: '1/3 + 2/3', widths: [1, 2] },
  { value: '2/3:1/3', label: '2/3 + 1/3', widths: [2, 1] },
  { value: '1/4:1/4:1/4:1/4', label: '1/4 + 1/4 + 1/4 + 1/4', widths: [1, 1, 1, 1] },
  { value: '1/4:3/4', label: '1/4 + 3/4', widths: [1, 3] },
  { value: '3/4:1/4', label: '3/4 + 1/4', widths: [3, 1] },
]

export const BLOCKS: Array<{ type: BlockType; label: string; description: string; group: string }> = [
  { type: 'text', label: 'Text', description: 'Rich text and headings', group: 'Content' },
  { type: 'image', label: 'Image', description: 'Public image or GIF', group: 'Media' },
  { type: 'button', label: 'Button', description: 'Call to action', group: 'Content' },
  { type: 'divider', label: 'Divider', description: 'Horizontal separator', group: 'Structure' },
  { type: 'spacer', label: 'Spacer', description: 'Vertical breathing room', group: 'Structure' },
  { type: 'social', label: 'Social', description: 'Social profile links', group: 'Content' },
  { type: 'preview_url', label: 'View online', description: 'Browser preview link', group: 'Utility' },
  { type: 'unsubscribe_link', label: 'Unsubscribe link', description: 'Recipient-specific unsubscribe link', group: 'Utility' },
  { type: 'preference_center_link', label: 'Preference center link', description: 'Recipient-specific preference center link', group: 'Utility' },
  { type: 'code', label: 'HTML', description: 'Restricted email-safe HTML', group: 'Advanced' },
]

export const DEFAULT_SETTINGS: BuilderSettings = {
  content_width: 600,
  body_background: '#f5f7fa',
  content_background: '#ffffff',
  font_family: 'Arial, Helvetica, sans-serif',
  font_size: '16px',
  text_color: '#1f2937',
  link_color: '#2563eb',
  link_decoration: 'underline',
  button_background: '#2563eb',
  button_text_color: '#ffffff',
  button_radius: '4px',
  section_padding: '0px',
}

export const EMPTY_VISIBILITY = (): Visibility => ({ device: 'both', match: 'all', conditions: [] })

export const uid = (prefix: string) => `${prefix}_${crypto.randomUUID().replaceAll('-', '').slice(0, 16)}`

export const clone = <T,>(value: T): T => structuredClone(value)

export function createBlock(type: BlockType): BuilderBlock {
  const content: Record<BlockType, Record<string, unknown>> = {
    text: { html: '<p>Write your message here</p>', tag: 'p' },
    image: { src: '', alt: '', decorative: false, href: '', preserve_aspect_ratio: true },
    button: { text: 'Call to action', action: 'url', href: 'https://example.com', full_width: false },
    divider: { style: 'solid', thickness: 1 },
    spacer: { height: 24 },
    social: {
      items: [],
      display: 'icon',
      icon_shape: 'circle',
      icon_size: 24,
      item_spacing: 8,
    },
    preview_url: { text: 'View this email in your browser' },
    compliance_links: { unsubscribe_text: 'Unsubscribe', preference_text: 'Email preference center' },
    unsubscribe_link: { text: 'Unsubscribe' },
    preference_center_link: { text: 'Email preference center' },
    code: { html: '<p>Custom HTML</p>' },
  }
  return { id: uid('block'), type, content: clone(content[type]), style: {}, visibility: EMPTY_VISIBILITY() }
}

export function createSection(layout: LayoutType = '1'): BuilderSection {
  const definition = LAYOUTS.find((item) => item.value === layout) ?? LAYOUTS[0]
  return {
    id: uid('section'),
    layout: definition.value,
    column_widths: normalizeColumnWidths(definition.widths, definition.widths.length),
    vertical_align: 'top',
    mobile_stack: 'stack',
    style: {},
    visibility: EMPTY_VISIBILITY(),
    columns: definition.widths.map(() => ({ id: uid('column'), style: {}, blocks: [] })),
  }
}

export function emptyDocument(): BuilderDocument {
  return {
    schema: { version: 1, settings: clone(DEFAULT_SETTINGS), sections: [] },
    metadata: { subject: '', preheader: '', reference_doctype: '', preview_document: '', validate_dynamic_fields: false },
  }
}

export function findBlock(schema: BuilderSchema, id: string) {
  for (let sectionIndex = 0; sectionIndex < schema.sections.length; sectionIndex += 1) {
    const section = schema.sections[sectionIndex]
    for (let columnIndex = 0; columnIndex < section.columns.length; columnIndex += 1) {
      const column = section.columns[columnIndex]
      const blockIndex = column.blocks.findIndex((block) => block.id === id)
      if (blockIndex >= 0) return { section, sectionIndex, column, columnIndex, block: column.blocks[blockIndex], blockIndex }
    }
  }
  return null
}

export function findColumn(schema: BuilderSchema, id: string) {
  for (let sectionIndex = 0; sectionIndex < schema.sections.length; sectionIndex += 1) {
    const section = schema.sections[sectionIndex]
    const columnIndex = section.columns.findIndex((column) => column.id === id)
    if (columnIndex >= 0) return { section, sectionIndex, column: section.columns[columnIndex], columnIndex }
  }
  return null
}

export function findSection(schema: BuilderSchema, id: string) {
  const sectionIndex = schema.sections.findIndex((section) => section.id === id)
  return sectionIndex >= 0 ? { section: schema.sections[sectionIndex], sectionIndex } : null
}

export function findSelected(schema: BuilderSchema, selection: Selection): BuilderSection | BuilderColumn | BuilderBlock | null {
  if (!selection) return null
  if (selection.kind === 'section') return findSection(schema, selection.id)?.section ?? null
  if (selection.kind === 'column') return findColumn(schema, selection.id)?.column ?? null
  return findBlock(schema, selection.id)?.block ?? null
}

export function resizeSection(section: BuilderSection, layout: LayoutType) {
  const definition = LAYOUTS.find((item) => item.value === layout) ?? LAYOUTS[0]
  const count = definition.widths.length
  if (section.columns.length < count) {
    while (section.columns.length < count) section.columns.push({ id: uid('column'), style: {}, blocks: [] })
  } else if (section.columns.length > count) {
    const retained = section.columns.slice(0, count)
    const overflow = section.columns.slice(count).flatMap((column) => column.blocks)
    retained[count - 1].blocks.push(...overflow)
    section.columns = retained
  }
  section.layout = layout
  section.column_widths = normalizeColumnWidths(definition.widths, count)
}

export function normalizeColumnWidths(widths: number[] | undefined, count: number, fallback?: number[]) {
  if (count <= 0) return []
  const source = widths?.length === count && widths.every((width) => Number.isFinite(width) && width > 0)
    ? widths
    : fallback?.length === count
      ? fallback
      : Array.from({ length: count }, () => 1)
  const total = source.reduce((sum, width) => sum + width, 0) || count
  const normalized = source.map((width) => Number(((width / total) * 100).toFixed(3)))
  normalized[normalized.length - 1] = Number((normalized.at(-1)! + 100 - normalized.reduce((sum, width) => sum + width, 0)).toFixed(3))
  return normalized
}

export function moveSection(schema: BuilderSchema, sectionId: string, targetSectionId: string) {
  const sourceIndex = schema.sections.findIndex((section) => section.id === sectionId)
  const targetIndex = schema.sections.findIndex((section) => section.id === targetSectionId)
  if (sourceIndex < 0 || targetIndex < 0 || sourceIndex === targetIndex) return false
  const [section] = schema.sections.splice(sourceIndex, 1)
  schema.sections.splice(targetIndex, 0, section)
  return true
}

export const TEXT_STYLES = [['h1', 'Heading 1'], ['h2', 'Heading 2'], ['h3', 'Heading 3'], ['p', 'Paragraph']] as const
const FONT_FAMILY_PATTERN = /^[A-Za-z0-9 ,'"-]{1,160}$/
const FONT_SIZE_PATTERN = /^\d+(?:\.\d+)?(?:px|pt|em|rem|%)?$/
const FONT_WEIGHTS = new Set(['normal', '500', '600', '700', 'bold'])

/** EM-14: CSS that shows the canvas text in the fonts chosen for headings and paragraphs. Only safe values are used. */
export function typographyCss(settings: Record<string, unknown>, scope = '.canvas-stage .rich-text') {
  const rules: string[] = []
  for (const [tag] of TEXT_STYLES) {
    const declarations: string[] = []
    const family = String(settings[`${tag}_font_family`] || '').trim()
    const size = String(settings[`${tag}_font_size`] || '').trim()
    const weight = String(settings[`${tag}_font_weight`] || '').trim().toLowerCase()
    if (family && FONT_FAMILY_PATTERN.test(family)) declarations.push(`font-family:${family}`)
    if (size && FONT_SIZE_PATTERN.test(size) && parseFloat(size) > 0) declarations.push(`font-size:${/\d$/.test(size) ? size + 'px' : size}`)
    if (weight && FONT_WEIGHTS.has(weight)) declarations.push(`font-weight:${weight}`)
    if (declarations.length) rules.push(`${scope} ${tag}{${declarations.join(';')}}`)
  }
  return rules.join('\n')
}

/** EM-06: what is wrong with the value of a button action, or '' when it is fine. Mirrors the checks made when the email is saved. */
export function buttonActionIssue(action: string, value: unknown) {
  const text = String(value ?? '').trim()
  if (!text || text.includes('{{')) return ''
  switch (action) {
    case 'email':
      return /^(?:mailto:)?[^\s@]+@[^\s@]+\.[^\s@]+(?:\?.*)?$/i.test(text) ? '' : 'Enter an email address like name@company.ch.'
    case 'telephone':
      return /^(?:tel:)?\+?[0-9(). -]{3,40}$/i.test(text) ? '' : 'Enter a phone number like +41 44 123 45 67.'
    case 'sms':
      return /^(?:sms:)?\+?[0-9(). -]{3,40}(?:[?&]body=[^\s{}<>"']{0,300})?$/i.test(text) ? '' : 'Enter a mobile number like +41 79 123 45 67. Add ?body=Your text to fill in the message.'
    case 'file':
      return /^\/private\//.test(text) || /\/private\/files\//.test(text) ? 'Choose a public file. Private files cannot be opened by recipients.' : /^(?:\/files\/|https?:\/\/)/i.test(text) ? '' : 'Use a public file address that starts with /files/ or https://.'
    default:
      return /^https?:\/\//i.test(text) || /^[\w-]+(?:\.[\w-]+)+(?:[/?#].*)?$/.test(text) ? '' : 'Enter a web address like https://megasol.ch.'
  }
}

export const BUTTON_ACTION_PLACEHOLDERS: Record<string, string> = {
  url: 'https://example.com',
  email: 'name@company.ch',
  file: '/files/brochure.pdf',
  telephone: '+41 44 123 45 67',
  sms: '+41 79 123 45 67',
}

export const SHARED_CATEGORIES = ['Header', 'Footer']

/** Header and footer: is this row linked to a shared saved Header or Footer block? */
export function sharedSectionState(section: { saved_component?: string; saved_component_category?: string; component_customised?: boolean }) {
  if (!section.saved_component || !SHARED_CATEGORIES.includes(String(section.saved_component_category))) return null
  return { name: section.saved_component, category: section.saved_component_category as 'Header' | 'Footer', customised: Boolean(section.component_customised) }
}

/** Header and footer: a change to a linked row means this email now has its own version; return the rows that changed. */
export function markCustomisedSharedSections(before: BuilderSchema, next: BuilderSchema) {
  const content = (section: BuilderSection) => JSON.stringify({ ...section, component_customised: undefined })
  const previous = new Map(before.sections.map((section) => [section.id, section]))
  const marked: string[] = []
  for (const section of next.sections) {
    const old = previous.get(section.id)
    const state = sharedSectionState(section)
    if (!old || !state || state.customised || sharedSectionState(old)?.customised) continue
    if (content(old) !== content(section)) { section.component_customised = true; marked.push(section.id) }
  }
  return marked
}

/** EM-02: move a block (within its column) or a row one place up (-1) or down (+1). */
export function shiftNode(schema: BuilderSchema, kind: 'block' | 'section', id: string, delta: -1 | 1) {
  const list: Array<{ id: string }> | undefined = kind === 'section'
    ? schema.sections
    : findBlock(schema, id)?.column.blocks
  if (!list) return false
  const index = list.findIndex((item) => item.id === id)
  const target = index + delta
  if (index < 0 || target < 0 || target >= list.length) return false
  const [item] = list.splice(index, 1)
  list.splice(target, 0, item)
  return true
}

/** EM-13: does this block or row show only for some recipients? */
export function visibilitySummary(visibility: { match?: string; conditions?: unknown[]; segment_conditions?: unknown[] } | undefined) {
  const rules = (visibility?.conditions?.length || 0) + (visibility?.segment_conditions?.length || 0)
  if (!rules) return null
  const joiner = visibility?.match === 'any' ? 'any' : 'all'
  return { rules, label: rules === 1 ? 'Conditional' : `Conditional · ${rules}`, title: `Shown only when ${rules === 1 ? 'the condition is met' : joiner === 'any' ? 'any of the ' + rules + ' conditions is met' : 'all ' + rules + ' conditions are met'}` }
}

export function moveBlock(schema: BuilderSchema, blockId: string, destinationColumnId: string, targetBlockId?: string) {
  const source = findBlock(schema, blockId)
  const destination = findColumn(schema, destinationColumnId)
  if (!source || !destination) return false
  const target = targetBlockId ? findBlock(schema, targetBlockId) : null
  if (targetBlockId && (!target || target.column.id !== destinationColumnId)) return false
  if (source.column.id === destinationColumnId && target) {
    if (source.block.id === target.block.id) return false
    const [block] = source.column.blocks.splice(source.blockIndex, 1)
    source.column.blocks.splice(target.blockIndex, 0, block)
    return true
  }
  const [block] = source.column.blocks.splice(source.blockIndex, 1)
  const refreshedDestination = findColumn(schema, destinationColumnId)?.column
  if (!refreshedDestination) {
    source.column.blocks.splice(source.blockIndex, 0, block)
    return false
  }
  const refreshedTarget = targetBlockId ? findBlock(schema, targetBlockId) : null
  const index = refreshedTarget?.column.id === destinationColumnId ? refreshedTarget.blockIndex : refreshedDestination.blocks.length
  refreshedDestination.blocks.splice(index, 0, block)
  return true
}

export function rebalanceColumnWidths(widths: number[], changedIndex: number, requested: number, minimum = 8) {
  const normalized = normalizeColumnWidths(widths, widths.length)
  if (normalized.length < 2) return normalized
  if (!Number.isFinite(requested)) return normalized
  const target = Math.max(minimum, Math.min(100 - minimum * (normalized.length - 1), requested))
  const others = normalized.map((width, index) => index === changedIndex ? 0 : Math.max(0, width - minimum))
  const flexibleTotal = others.reduce((sum, width) => sum + width, 0)
  const flexibleSpace = Math.max(0, 100 - target - minimum * (normalized.length - 1))
  const next = normalized.map((_, index) => {
    if (index === changedIndex) return target
    const share = flexibleTotal ? others[index] / flexibleTotal : 1 / (normalized.length - 1)
    return minimum + flexibleSpace * share
  })
  return normalizeColumnWidths(next, next.length)
}

export function cloneNode<T extends BuilderBlock | BuilderSection>(node: T): T {
  const copy = clone(node)
  if ('columns' in copy) {
    copy.id = uid('section')
    copy.columns.forEach((column) => {
      column.id = uid('column')
      column.blocks.forEach((block) => { block.id = uid('block') })
    })
  } else {
    copy.id = uid('block')
  }
  return copy
}

export function normalizeLength(value: unknown, fallback = '0px') {
  const text = String(value ?? '').trim()
  if (!text) return fallback
  return /^\d+(?:\.\d+)?$/.test(text) ? `${text}px` : text
}

export function nodeCss(style: NodeStyle = {}) {
  const spacing = (value?: { top?: string; right?: string; bottom?: string; left?: string }) =>
    `${normalizeLength(value?.top)} ${normalizeLength(value?.right)} ${normalizeLength(value?.bottom)} ${normalizeLength(value?.left)}`
  return {
    background: style.background || undefined,
    color: style.color || style.font_color || undefined,
    padding: style.padding ? spacing(style.padding) : undefined,
    margin: style.margin ? spacing(style.margin) : undefined,
    textAlign: style.align || undefined,
    fontFamily: style.font_family || undefined,
    fontSize: style.font_size ? normalizeLength(style.font_size) : undefined,
    lineHeight: style.line_height ? normalizeLength(style.line_height) : undefined,
    fontWeight: style.font_weight || undefined,
    fontStyle: style.font_style || undefined,
    textDecoration: style.text_decoration || undefined,
    width: style.width ? normalizeLength(style.width) : undefined,
    height: style.height ? normalizeLength(style.height) : undefined,
    borderWidth: style.border_width ? normalizeLength(style.border_width) : undefined,
    borderColor: style.border_color || undefined,
    borderStyle: style.border_style || undefined,
    borderRadius: style.radius ? normalizeLength(style.radius) : undefined,
  } as const
}

export function safeJson(value: unknown) {
  return JSON.stringify(value)
}
