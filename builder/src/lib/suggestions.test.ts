import assert from 'node:assert/strict'
import test from 'node:test'

import { collectBuilderSuggestions } from './suggestions.ts'
import type { BuilderDocument, MergeField } from '../types.ts'

function baseDocument(): BuilderDocument {
  return {
    metadata: {
      subject: 'Hello {{ first_name }}',
      preheader: '',
      reference_doctype: 'Customer',
      preview_document: 'CUST-0001',
      validate_dynamic_fields: true,
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
        visibility: { device: 'both', match: 'all', conditions: [] },
        columns: [{
          id: 'column-1',
          style: {},
          blocks: [],
        }],
      }],
    },
  }
}

const fields: MergeField[] = [{ fieldname: 'first_name', label: 'First Name', fieldtype: 'Data' }]

test('collectBuilderSuggestions reports invalid token syntax centrally', () => {
  const document = baseDocument()
  document.schema.sections[0].columns[0].blocks.push({
    id: 'text-1',
    type: 'text',
    content: { html: '<p>Hello {{ }}</p>' },
    style: {},
    visibility: { device: 'both', match: 'all', conditions: [] },
  })

  const suggestions = collectBuilderSuggestions(document, fields, false, null)
  assert.equal(suggestions[0].severity, 'error')
  assert.equal(suggestions[0].category, 'Dynamic fields')
  assert.match(suggestions[0].message, /Empty dynamic fields/)
})

test('collectBuilderSuggestions reports invalid readable fields only when validation is on', () => {
  const document = baseDocument()
  document.schema.sections[0].columns[0].blocks.push({
    id: 'text-1',
    type: 'text',
    content: { html: '<p>{{ last_name }}</p>' },
    style: {},
    visibility: { device: 'both', match: 'all', conditions: [] },
  })

  assert.deepEqual(collectBuilderSuggestions(document, fields, false, null).find((item) => item.id.startsWith('dynamic:invalid-fields'))?.fields, ['last_name'])
  document.metadata.validate_dynamic_fields = false
  assert.equal(collectBuilderSuggestions(document, fields, false, null).some((item) => item.id.startsWith('dynamic:invalid-fields')), false)
})

test('collectBuilderSuggestions reports image and button guidance', () => {
  const document = baseDocument()
  document.schema.sections[0].columns[0].blocks.push(
    { id: 'image-1', type: 'image', content: { src: '/files/photo.png', alt: '' }, style: {}, visibility: { device: 'both', match: 'all', conditions: [] } },
    { id: 'button-1', type: 'button', content: { text: 'Open', href: '' }, style: {}, visibility: { device: 'both', match: 'all', conditions: [] } },
  )

  const ids = collectBuilderSuggestions(document, fields, false, null).map((item) => item.id)
  assert.equal(ids.includes('image:image-1:missing-alt'), true)
  assert.equal(ids.includes('link:button-1:missing-button-url'), true)
})
