import type { BuilderDocument, BuilderSchema } from '../types'

const MERGE_TOKEN_RE = /{{[\s\S]*?}}/g

export type ReferenceDoctypeUsage = {
  mergeTokenCount: number
  conditionCount: number
  hasPreviewDocument: boolean
  validationEnabled: boolean
  hasReferenceDependentContent: boolean
}

export type PendingReferenceDoctypeChange = ReferenceDoctypeUsage & {
  previousValue: string
  nextValue: string
}

function countMergeTokens(value: unknown): number {
  if (typeof value === 'string') return value.match(MERGE_TOKEN_RE)?.length ?? 0
  if (Array.isArray(value)) return value.reduce((total, item) => total + countMergeTokens(item), 0)
  if (!value || typeof value !== 'object') return 0
  return Object.values(value as Record<string, unknown>).reduce<number>((total, item) => total + countMergeTokens(item), 0)
}

export function countVisibilityConditions(schema: BuilderSchema): number {
  return schema.sections.reduce((total, section) => {
    const sectionConditions = section.visibility?.conditions?.length ?? 0
    const blockConditions = section.columns.reduce((columnTotal, column) => {
      return columnTotal + column.blocks.reduce((blockTotal, block) => blockTotal + (block.visibility?.conditions?.length ?? 0), 0)
    }, 0)
    return total + sectionConditions + blockConditions
  }, 0)
}

export function analyzeReferenceDoctypeUsage(document: BuilderDocument): ReferenceDoctypeUsage {
  const mergeTokenCount = countMergeTokens({
    schema: document.schema,
    subject: document.metadata.subject,
    preheader: document.metadata.preheader,
  })
  const conditionCount = countVisibilityConditions(document.schema)
  return {
    mergeTokenCount,
    conditionCount,
    hasPreviewDocument: Boolean(document.metadata.preview_document),
    validationEnabled: Boolean(document.metadata.validate_dynamic_fields),
    hasReferenceDependentContent: mergeTokenCount > 0 || conditionCount > 0,
  }
}

function stripMergeTokens(value: unknown): unknown {
  if (typeof value === 'string') return value.replace(MERGE_TOKEN_RE, '').replace(/[ \t]{2,}/g, ' ')
  if (Array.isArray(value)) return value.map((item) => stripMergeTokens(item))
  if (!value || typeof value !== 'object') return value
  return Object.fromEntries(Object.entries(value as Record<string, unknown>).map(([key, item]) => [key, stripMergeTokens(item)]))
}

export function removeReferenceDependentContent(document: BuilderDocument): BuilderDocument {
  const next = structuredClone(document)
  next.metadata.subject = stripMergeTokens(next.metadata.subject) as string
  next.metadata.preheader = stripMergeTokens(next.metadata.preheader) as string
  next.schema = stripMergeTokens(next.schema) as BuilderSchema

  next.schema.sections.forEach((section) => {
    if (section.visibility) {
      section.visibility.conditions = []
      section.visibility.match = 'all'
    }
    section.columns.forEach((column) => {
      column.blocks.forEach((block) => {
        if (block.visibility) {
          block.visibility.conditions = []
          block.visibility.match = 'all'
        }
      })
    })
  })

  return next
}
