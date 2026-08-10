import assert from 'node:assert/strict'
import test from 'node:test'

import { buildMergeToken, collectDynamicFields, getDynamicFieldValidation, isValidMergeToken, validateMergeTokenSyntax } from './tokens.ts'
import type { BuilderDocument, MergeField } from '../types.ts'

function documentWith(html: string, validateDynamicFields = true): BuilderDocument {
  return {
    metadata: {
      subject: 'Hello {{ first_name }}',
      preheader: '',
      reference_doctype: 'Customer',
      preview_document: 'CUST-0001',
      validate_dynamic_fields: validateDynamicFields,
    },
    schema: {
      version: 1,
      settings: {
        content_width: 600,
        body_background: '#f5f7fa',
        content_background: '#ffffff',
        font_family: 'Arial',
        font_size: '16px',
        text_color: '#1f2937',
        link_color: '#2563eb',
        link_decoration: 'underline',
        button_background: '#2563eb',
        button_text_color: '#ffffff',
        button_radius: '4px',
        section_padding: '0px',
      },
      sections: [{
        id: 'section-1',
        layout: '1',
        vertical_align: 'top',
        mobile_stack: 'stack',
        style: {},
        visibility: { device: 'both', match: 'all', conditions: [{ fieldname: 'status', operator: 'equals', value: 'Open' }] },
        columns: [{
          id: 'column-1',
          style: {},
          blocks: [{
            id: 'block-1',
            type: 'text',
            content: { html },
            style: {},
            visibility: { device: 'both', match: 'all', conditions: [] },
          }],
        }],
      }],
    },
  }
}

const readableFields: MergeField[] = [
  { fieldname: 'first_name', label: 'First Name', fieldtype: 'Data' },
  { fieldname: 'status', label: 'Status', fieldtype: 'Select' },
  { fieldname: 'lead_owner', label: 'Lead Owner', fieldtype: 'Link', options: 'User' },
]

test('buildMergeToken creates safe tokens with optional escaped fallbacks', () => {
  assert.equal(buildMergeToken('first_name'), '{{ first_name }}')
  assert.equal(
    buildMergeToken('first_name', 'Friend "from sales"'),
    '{{ first_name|default("Friend \\"from sales\\"", true) }}',
  )
  assert.throws(() => buildMergeToken('first-name'), /Invalid dynamic field name/)
  assert.equal(buildMergeToken('lead_owner.full_name', 'Team'), '{{ lead_owner.full_name|default("Team", true) }}')
  assert.throws(() => buildMergeToken('lead_owner.profile.full_name'), /Invalid dynamic field name/)
})

test('canvas token validation accepts linked fields and their fallbacks', () => {
  assert.equal(isValidMergeToken('{{ lead_owner.full_name }}'), true)
  assert.equal(isValidMergeToken('{{ lead_owner.full_name|default("Sales owner", true) }}'), true)
  assert.equal(isValidMergeToken('{{ lead_owner.profile.full_name }}'), false)
  assert.equal(isValidMergeToken('{{ lead-owner.full_name }}'), false)
})

test('collectDynamicFields reads valid tokens and visibility fields only', () => {
  const fields = collectDynamicFields(documentWith('<p>{{ first_name }} {{ last_name|default("Friend", true) }}</p>').schema)
  assert.deepEqual(Array.from(fields).sort(), ['first_name', 'last_name', 'status'])
})

test('validateMergeTokenSyntax flags empty tokens', () => {
  const issues = validateMergeTokenSyntax('<p>Hello {{ }}</p>')
  assert.equal(issues[0]?.code, 'empty_dynamic_field')
})

test('validateMergeTokenSyntax flags unsupported jinja and invalid filters', () => {
  assert.equal(validateMergeTokenSyntax('{% if doc %}Hi{% endif %}')[0]?.code, 'unsupported_jinja')
  assert.equal(validateMergeTokenSyntax('Hello {{ first_name|upper }}')[0]?.code, 'invalid_dynamic_field_syntax')
  assert.equal(validateMergeTokenSyntax('Hello {{ first-name }}')[0]?.code, 'invalid_dynamic_field_syntax')
})

test('getDynamicFieldValidation reports unreadable fields when validation is enabled', () => {
  const result = getDynamicFieldValidation(documentWith('<p>{{ first_name }} {{ last_name }}</p>'), readableFields, false, null)
  assert.deepEqual(result.invalidFields, ['last_name'])
  assert.equal(result.issues.length, 0)
})

test('getDynamicFieldValidation accepts one-level fields from a readable Link', () => {
  const result = getDynamicFieldValidation(
    documentWith('<p>{{ lead_owner.full_name }} {{ lead_owner.email }}</p>'),
    readableFields,
    false,
    null,
  )
  assert.deepEqual(result.invalidFields, [])
})

test('getDynamicFieldValidation requires reference doctype only when field validation is enabled', () => {
  const document = documentWith('<p>{{ first_name }}</p>')
  document.metadata.reference_doctype = ''
  const result = getDynamicFieldValidation(document, [], false, null)
  assert.equal(result.issues[0]?.code, 'missing_reference_doctype')

  document.metadata.validate_dynamic_fields = false
  const genericResult = getDynamicFieldValidation(document, [], false, null)
  assert.equal(genericResult.issues.length, 0)
})
