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
