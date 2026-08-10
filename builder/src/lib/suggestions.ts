import type { BuilderBlock, BuilderDocument, BuilderSection, MergeField } from '../types'
import { getDynamicFieldValidation } from './tokens.ts'

export type BuilderSuggestionSeverity = 'error' | 'warning' | 'info'
export type BuilderSuggestionCategory = 'Inbox' | 'Dynamic fields' | 'Images' | 'Links' | 'Content'

export type BuilderSuggestion = {
  id: string
  severity: BuilderSuggestionSeverity
  category: BuilderSuggestionCategory
  title: string
  message: string
  nodeId?: string
  fields?: string[]
}

function walkBlocks(document: BuilderDocument, visit: (block: BuilderBlock, section: BuilderSection) => void) {
  document.schema.sections.forEach((section) => {
    section.columns.forEach((column) => column.blocks.forEach((block) => visit(block, section)))
  })
}

function textValue(value: unknown) {
  return String(value ?? '').trim()
}

function pushUnique(target: BuilderSuggestion[], suggestion: BuilderSuggestion) {
  if (!target.some((item) => item.id === suggestion.id)) target.push(suggestion)
}

export function collectBuilderSuggestions(document: BuilderDocument, mergeFields: MergeField[], mergeFieldsLoading: boolean, mergeFieldsError: unknown): BuilderSuggestion[] {
  const suggestions: BuilderSuggestion[] = []
  const metadata = document.metadata

  if (!textValue(metadata.subject)) {
    pushUnique(suggestions, {
      id: 'inbox:missing-subject',
      severity: 'error',
      category: 'Inbox',
      title: 'Subject line is required',
      message: 'Add a clear subject before previewing or sending this template.',
    })
  }

  const dynamicValidation = getDynamicFieldValidation(document, mergeFields, mergeFieldsLoading, mergeFieldsError)
  dynamicValidation.issues.forEach((issue) => {
    pushUnique(suggestions, {
      id: `dynamic:${issue.code}`,
      severity: issue.code === 'missing_reference_doctype' ? 'warning' : 'error',
      category: 'Dynamic fields',
      title: issue.code === 'missing_reference_doctype' ? 'Reference DocType needed' : 'Fix dynamic field syntax',
      message: issue.message,
      fields: issue.fields,
    })
  })

  if (metadata.validate_dynamic_fields && dynamicValidation.invalidFields.length) {
    pushUnique(suggestions, {
      id: `dynamic:invalid-fields:${dynamicValidation.invalidFields.join(',')}`,
      severity: 'error',
      category: 'Dynamic fields',
      title: metadata.reference_doctype ? `Fields not valid for ${metadata.reference_doctype}` : 'Choose a Reference DocType',
      message: 'Remove these fields, choose another Reference DocType, or turn off validation for a generic template.',
      fields: dynamicValidation.invalidFields,
    })
  }

  if (!document.schema.sections.length) {
    pushUnique(suggestions, {
      id: 'content:empty-template',
      severity: 'info',
      category: 'Content',
      title: 'Template is empty',
      message: 'Add a row and content block to start building the email.',
    })
  }

  walkBlocks(document, (block) => {
    if (block.type === 'image') {
      const src = textValue(block.content.src)
      const alt = textValue(block.content.alt)
      const decorative = Boolean(block.content.decorative)
      if (!src) {
        pushUnique(suggestions, {
          id: `image:${block.id}:missing-src`,
          severity: 'warning',
          category: 'Images',
          title: 'Choose an image before sending',
          message: 'This image block has no public image selected yet.',
          nodeId: block.id,
        })
      }
      if (src && !alt && !decorative) {
        pushUnique(suggestions, {
          id: `image:${block.id}:missing-alt`,
          severity: 'warning',
          category: 'Images',
          title: 'Image alt text is missing',
          message: 'Add alt text or mark the image as decorative for better accessibility.',
          nodeId: block.id,
        })
      }
    }

    if (block.type === 'button') {
      const href = textValue(block.content.href)
      const action = textValue(block.content.action || 'url')
      if (!href && action !== 'none') {
        pushUnique(suggestions, {
          id: `link:${block.id}:missing-button-url`,
          severity: 'warning',
          category: 'Links',
          title: 'Button action is empty',
          message: 'Add a URL, email, phone, SMS, or file link for this button.',
          nodeId: block.id,
        })
      }
    }

    if (block.type === 'preview_url' && !textValue(block.content.text)) {
      pushUnique(suggestions, {
        id: `content:${block.id}:empty-preview-url-label`,
        severity: 'info',
        category: 'Content',
        title: 'Preview link label is empty',
        message: 'Add text such as “View this email in your browser”.',
        nodeId: block.id,
      })
    }
  })

  const severityOrder = { error: 0, warning: 1, info: 2 }
  return suggestions.sort((left, right) => severityOrder[left.severity] - severityOrder[right.severity] || left.category.localeCompare(right.category) || left.title.localeCompare(right.title))
}
