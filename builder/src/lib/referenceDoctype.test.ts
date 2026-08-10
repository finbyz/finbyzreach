import assert from 'node:assert/strict'
import test from 'node:test'

import { createBlock, createSection, emptyDocument } from './builder.ts'
import { analyzeReferenceDoctypeUsage, removeReferenceDependentContent } from './referenceDoctype.ts'

test('analyzeReferenceDoctypeUsage counts merge tokens and record conditions separately', () => {
  const document = emptyDocument()
  document.metadata.subject = 'Hello {{ lead_name }}'
  document.metadata.preheader = '{{ company_name|default("there", true) }}'
  document.metadata.preview_document = 'CRM-LEAD-0001'
  document.metadata.validate_dynamic_fields = true

  const section = createSection('1')
  section.visibility.conditions = [{ fieldname: 'status', operator: 'equals', value: 'Open' }]
  const block = createBlock('text')
  block.content.html = '<p>{{ email_id }}</p>'
  block.visibility.conditions = [{ fieldname: 'source', operator: 'not_empty', value: '' }]
  section.columns[0].blocks = [block]
  document.schema.sections = [section]

  const usage = analyzeReferenceDoctypeUsage(document)
  assert.equal(usage.mergeTokenCount, 3)
  assert.equal(usage.conditionCount, 2)
  assert.equal(usage.hasPreviewDocument, true)
  assert.equal(usage.validationEnabled, true)
  assert.equal(usage.hasReferenceDependentContent, true)
})

test('removeReferenceDependentContent strips tokens and clears visibility conditions', () => {
  const document = emptyDocument()
  document.metadata.subject = 'Hello {{ lead_name }}'
  document.metadata.preheader = 'Preview {{ company_name }}'

  const section = createSection('1')
  section.visibility.match = 'any'
  section.visibility.conditions = [{ fieldname: 'status', operator: 'equals', value: 'Open' }]
  const block = createBlock('button')
  block.content.text = 'Visit {{ company_name }}'
  block.content.href = 'https://example.com/{{ lead_name }}'
  block.visibility.match = 'any'
  block.visibility.conditions = [{ fieldname: 'source', operator: 'contains', value: 'Web' }]
  section.columns[0].blocks = [block]
  document.schema.sections = [section]

  const cleaned = removeReferenceDependentContent(document)

  assert.equal(cleaned.metadata.subject, 'Hello ')
  assert.equal(cleaned.metadata.preheader, 'Preview ')
  assert.equal(cleaned.schema.sections[0].visibility.match, 'all')
  assert.deepEqual(cleaned.schema.sections[0].visibility.conditions, [])
  assert.equal(cleaned.schema.sections[0].columns[0].blocks[0].content.text, 'Visit ')
  assert.equal(cleaned.schema.sections[0].columns[0].blocks[0].content.href, 'https://example.com/')
  assert.equal(cleaned.schema.sections[0].columns[0].blocks[0].visibility.match, 'all')
  assert.deepEqual(cleaned.schema.sections[0].columns[0].blocks[0].visibility.conditions, [])

  assert.equal(document.schema.sections[0].visibility.conditions.length, 1)
})
