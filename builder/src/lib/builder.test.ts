import assert from 'node:assert/strict'
import test from 'node:test'

import {
  cloneNode,
  createBlock,
  createSection,
  emptyDocument,
  findBlock,
  findColumn,
  findSection,
  findSelected,
  LAYOUTS,
  moveBlock,
  moveSection,
  nodeCss,
  normalizeColumnWidths,
  normalizeLength,
  rebalanceColumnWidths,
  buttonActionIssue,
  markCustomisedSharedSections,
  resizeSection,
  sharedSectionState,
  shiftNode,
  typographyCss,
  visibilitySummary,
} from './builder.ts'

function section(id: string) {
  const value = createSection('1')
  value.id = id
  value.columns[0].id = `${id}-column`
  return value
}

function block(id: string) {
  const value = createBlock('text')
  value.id = id
  return value
}

test('moves rows correctly in both directions', () => {
  const schema = emptyDocument().schema
  schema.sections = [section('a'), section('b'), section('c')]
  assert.equal(moveSection(schema, 'a', 'c'), true)
  assert.deepEqual(schema.sections.map((item) => item.id), ['b', 'c', 'a'])
  assert.equal(moveSection(schema, 'a', 'b'), true)
  assert.deepEqual(schema.sections.map((item) => item.id), ['a', 'b', 'c'])
})

test('moveSection handles invalid inputs gracefully', () => {
  const schema = emptyDocument().schema
  schema.sections = [section('a'), section('b')]
  assert.equal(moveSection(schema, 'x', 'b'), false)
  assert.equal(moveSection(schema, 'a', 'x'), false)
  assert.equal(moveSection(schema, 'a', 'a'), false)
})

test('moves blocks within a column without dragging siblings', () => {
  const schema = emptyDocument().schema
  const row = section('row')
  row.columns[0].blocks = [block('a'), block('b'), block('c')]
  schema.sections = [row]
  assert.equal(moveBlock(schema, 'a', 'row-column', 'c'), true)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['b', 'c', 'a'])
  assert.equal(moveBlock(schema, 'a', 'row-column', 'b'), true)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['a', 'b', 'c'])
})

test('moves a block between columns at the requested target', () => {
  const schema = emptyDocument().schema
  const row = createSection('1/2:1/2')
  row.columns[0].id = 'left'
  row.columns[1].id = 'right'
  row.columns[0].blocks = [block('a'), block('b')]
  row.columns[1].blocks = [block('c')]
  schema.sections = [row]
  assert.equal(moveBlock(schema, 'b', 'right', 'c'), true)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['a'])
  assert.deepEqual(row.columns[1].blocks.map((item) => item.id), ['b', 'c'])
})

test('moves a block to an empty column or end of column', () => {
  const schema = emptyDocument().schema
  const row = createSection('1/2:1/2')
  row.columns[0].id = 'left'
  row.columns[1].id = 'right'
  row.columns[0].blocks = [block('a'), block('b')]
  row.columns[1].blocks = []
  schema.sections = [row]
  assert.equal(moveBlock(schema, 'a', 'right'), true)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['b'])
  assert.deepEqual(row.columns[1].blocks.map((item) => item.id), ['a'])
})

test('moveBlock handles invalid inputs gracefully', () => {
  const schema = emptyDocument().schema
  const row = section('row')
  row.columns[0].blocks = [block('a')]
  schema.sections = [row]
  assert.equal(moveBlock(schema, 'x', 'row-column'), false)
  assert.equal(moveBlock(schema, 'a', 'x'), false)
})

test('layout reduction retains content from removed columns', () => {
  const row = createSection('1/3:1/3:1/3')
  row.columns[0].blocks = [block('a')]
  row.columns[1].blocks = [block('b')]
  row.columns[2].blocks = [block('c')]
  resizeSection(row, '1/2:1/2')
  assert.equal(row.columns.length, 2)
  assert.deepEqual(row.columns[1].blocks.map((item) => item.id), ['b', 'c'])
})

test('shiftNode moves a block or a row one place and stops at the ends', () => {
  const row = createSection('1')
  row.columns[0].blocks = [block('a'), block('b'), block('c')]
  const schema = emptyDocument().schema
  schema.sections = [row, createSection('1'), createSection('1')]
  assert.equal(shiftNode(schema, 'block', 'a', -1), false)
  assert.equal(shiftNode(schema, 'block', 'a', 1), true)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['b', 'a', 'c'])
  assert.equal(shiftNode(schema, 'block', 'c', 1), false)
  assert.equal(shiftNode(schema, 'block', 'missing', 1), false)
  const [first, second] = schema.sections
  assert.equal(shiftNode(schema, 'section', first.id, 1), true)
  assert.deepEqual(schema.sections.slice(0, 2).map((item) => item.id), [second.id, first.id])
  assert.equal(shiftNode(schema, 'section', second.id, -1), false)
})

test('visibilitySummary describes who sees a block, or nothing when it is for everyone', () => {
  assert.equal(visibilitySummary(undefined), null)
  assert.equal(visibilitySummary({ conditions: [], segment_conditions: [] }), null)
  assert.deepEqual(visibilitySummary({ match: 'all', conditions: [{}] }), { rules: 1, label: 'Conditional', title: 'Shown only when the condition is met' })
  assert.equal(visibilitySummary({ match: 'any', conditions: [{}], segment_conditions: [{}] })?.title, 'Shown only when any of the 2 conditions is met')
  assert.equal(visibilitySummary({ match: 'all', conditions: [{}, {}, {}] })?.label, 'Conditional · 3')
})

test('layout expansion adds new columns', () => {
  const row = createSection('1/2:1/2')
  resizeSection(row, '1/3:1/3:1/3')
  assert.equal(row.columns.length, 3)
})

test('column widths are finite, normalized, and safe for no columns', () => {
  assert.deepEqual(normalizeColumnWidths(undefined, 0), [])
  const widths = normalizeColumnWidths([1, 2, 3], 3)
  assert.equal(widths.reduce((sum, value) => sum + value, 0), 100)
  assert.ok(widths.every((value) => Number.isFinite(value) && value > 0))
})

test('rebalanceColumnWidths correctly recalculates shares based on minimum width', () => {
  const widths2 = [50, 50]
  assert.deepEqual(rebalanceColumnWidths(widths2, 0, 70), [70, 30])
  
  // enforce minimum width of 8
  assert.deepEqual(rebalanceColumnWidths(widths2, 0, 95, 8), [92, 8])
  assert.deepEqual(rebalanceColumnWidths(widths2, 0, 2, 8), [8, 92])
  
  const widths3 = [33.334, 33.333, 33.333]
  assert.deepEqual(rebalanceColumnWidths(widths3, 0, 50, 8), [50, 25, 25])
})

test('normalizeLength parses properly', () => {
  assert.equal(normalizeLength('16'), '16px')
  assert.equal(normalizeLength(16), '16px')
  assert.equal(normalizeLength('16.5'), '16.5px')
  assert.equal(normalizeLength('100%'), '100%')
  assert.equal(normalizeLength('auto'), 'auto')
  assert.equal(normalizeLength(''), '0px')
  assert.equal(normalizeLength(null), '0px')
  assert.equal(normalizeLength(undefined, 'auto'), 'auto')
})

test('nodeCss creates CSS object from settings', () => {
  const style = nodeCss({ background: '#fff', font_size: '16', padding: { top: '10', left: 'auto' } })
  assert.equal(style.background, '#fff')
  assert.equal(style.fontSize, '16px')
  assert.equal(style.padding, '10px 0px 0px auto')
})

test('finders locate nodes correctly', () => {
  const schema = emptyDocument().schema
  const s = section('s1')
  const b = block('b1')
  s.columns[0].blocks.push(b)
  schema.sections.push(s)
  
  const foundB = findBlock(schema, 'b1')
  assert.ok(foundB)
  assert.equal(foundB.block.id, 'b1')
  assert.equal(foundB.column.id, 's1-column')
  
  const foundS = findSection(schema, 's1')
  assert.ok(foundS)
  assert.equal(foundS.section.id, 's1')
  
  const foundC = findColumn(schema, 's1-column')
  assert.ok(foundC)
  assert.equal(foundC.column.id, 's1-column')
  
  const selected = findSelected(schema, { kind: 'block', id: 'b1' })
  assert.ok(selected)
  assert.equal(selected.id, 'b1')
  
  assert.equal(findBlock(schema, 'missing'), null)
})

test('cloneNode deep clones and assigns new IDs', () => {
  const b1 = block('b1')
  const clonedB1 = cloneNode(b1)
  assert.notEqual(b1.id, clonedB1.id)
  assert.equal(b1.type, clonedB1.type)
  assert.notStrictEqual(b1.content, clonedB1.content) // Reference check
  assert.deepEqual(b1.content, clonedB1.content) // Value check
  
  const s1 = section('s1')
  const clonedS1 = cloneNode(s1)
  assert.notEqual(s1.id, clonedS1.id)
  assert.notEqual(s1.columns[0].id, clonedS1.columns[0].id)
})

test('normalizeColumnWidths exhaustive edge cases', () => {
  // Empty, zero, or negative inputs
  assert.deepEqual(normalizeColumnWidths([], 0), [])
  assert.deepEqual(normalizeColumnWidths([], 3), [33.333, 33.333, 33.334])
  assert.deepEqual(normalizeColumnWidths([0, 0], 2), [50, 50])
  assert.deepEqual(normalizeColumnWidths([-10, 10], 2), [50, 50]) // Invalid widths fall back to default
  
  // NaN handling
  assert.deepEqual(normalizeColumnWidths([NaN, 50], 2), [50, 50])
  
  // Exact rounding combinations
  assert.deepEqual(normalizeColumnWidths([1, 1, 1], 3), [33.333, 33.333, 33.334])
  assert.deepEqual(normalizeColumnWidths([1, 2, 1], 3), [25, 50, 25])
  
  // Mismatched count
  assert.deepEqual(normalizeColumnWidths([50, 50], 3), [33.333, 33.333, 33.334])
})

test('rebalanceColumnWidths exhaustive combinations', () => {
  const w3 = [33.333, 33.333, 33.334]
  
  // Requested equals exactly current
  assert.deepEqual(rebalanceColumnWidths(w3, 1, 33.333, 8), [33.333, 33.333, 33.334])
  
  // Requested is larger than allowed maximum
  assert.deepEqual(rebalanceColumnWidths(w3, 1, 100, 8), [8, 84, 8])
  
  // Requested is smaller than allowed minimum
  assert.deepEqual(rebalanceColumnWidths(w3, 1, 0, 8), [45.999, 8, 46.001])
  
  // Rebalancing handles single column (should just return 100%)
  assert.deepEqual(rebalanceColumnWidths([100], 0, 50, 8), [100])
  
  // Rebalancing with NaN requested
  assert.deepEqual(rebalanceColumnWidths(w3, 1, NaN, 8), w3)
  
  // Test distribution logic when others have different flexible space
  const unequal = [20, 60, 20]
  assert.deepEqual(rebalanceColumnWidths(unequal, 1, 40, 8), [30, 40, 30])
})

test('resizeSection exhaustive layout changes', () => {
  // 1 -> 4
  const sec = createSection('1')
  sec.columns[0].blocks = [block('a'), block('b')]
  resizeSection(sec, '1/4:1/4:1/4:1/4')
  assert.equal(sec.columns.length, 4)
  assert.equal(sec.columns[0].blocks.length, 2)
  assert.equal(sec.columns[1].blocks.length, 0)
  
  // 4 -> 2
  sec.columns[1].blocks = [block('c')]
  sec.columns[3].blocks = [block('d')]
  resizeSection(sec, '1/2:1/2')
  assert.equal(sec.columns.length, 2)
  assert.equal(sec.columns[0].blocks.length, 2) // a, b
  // Blocks from columns 1 (c), 2 (empty), 3 (d) should all merge into the last column (index 1)
  assert.equal(sec.columns[1].blocks.length, 2) 
  assert.deepEqual(sec.columns[1].blocks.map(b => b.id), ['c', 'd'])
})

test('nodeCss exhaustive combinations', () => {
  // All properties empty
  assert.deepEqual(nodeCss({}), {
    background: undefined, color: undefined, padding: undefined, margin: undefined,
    textAlign: undefined, fontFamily: undefined, fontSize: undefined, lineHeight: undefined,
    fontWeight: undefined, fontStyle: undefined, textDecoration: undefined,
    width: undefined, height: undefined, borderWidth: undefined, borderColor: undefined,
    borderStyle: undefined, borderRadius: undefined
  })
  
  // Fallbacks map correctly (color vs font_color)
  assert.equal(nodeCss({ font_color: 'red' }).color, 'red')
  assert.equal(nodeCss({ color: 'blue', font_color: 'red' }).color, 'blue')
  
  // Width/height numeric -> px
  assert.equal(nodeCss({ width: '100%' }).width, '100%')
  assert.equal(nodeCss({ width: '50' }).width, '50px')
})



test('moveBlock rejects target blocks that are not in the destination column', () => {
  const schema = emptyDocument().schema
  const row = createSection('1/2:1/2')
  row.columns[0].id = 'left'
  row.columns[1].id = 'right'
  row.columns[0].blocks = [block('a'), block('b')]
  row.columns[1].blocks = [block('c')]
  schema.sections = [row]

  assert.equal(moveBlock(schema, 'a', 'right', 'b'), false)
  assert.deepEqual(row.columns[0].blocks.map((item) => item.id), ['a', 'b'])
  assert.deepEqual(row.columns[1].blocks.map((item) => item.id), ['c'])
})

test('createSection produces valid column counts and 100 percent widths for every layout', () => {
  for (const layout of LAYOUTS) {
    const row = createSection(layout.value)
    assert.equal(row.layout, layout.value)
    assert.equal(row.columns.length, layout.widths.length)
    assert.equal(row.column_widths?.length, layout.widths.length)
    assert.equal(Number(row.column_widths?.reduce((sum, width) => sum + width, 0).toFixed(3)), 100)
    assert.ok(row.column_widths?.every((width) => width > 0))
  }
})

test('resizeSection keeps widths normalized after every layout permutation', () => {
  for (const startLayout of LAYOUTS) {
    for (const nextLayout of LAYOUTS) {
      const row = createSection(startLayout.value)
      row.columns[0].blocks = [block('kept')]
      resizeSection(row, nextLayout.value)
      assert.equal(row.layout, nextLayout.value)
      assert.equal(row.columns.length, nextLayout.widths.length)
      assert.equal(Number(row.column_widths?.reduce((sum, width) => sum + width, 0).toFixed(3)), 100)
      assert.ok(row.columns.some((column) => column.blocks.some((item) => item.id === 'kept')))
    }
  }
})

test('cloneNode deep clones sections with nested block IDs and content references', () => {
  const row = createSection('1/2:1/2')
  const text = block('text-1')
  text.content.html = '<p>Hello</p>'
  const button = createBlock('button')
  button.id = 'button-1'
  row.columns[0].blocks = [text]
  row.columns[1].blocks = [button]

  const cloned = cloneNode(row)
  assert.notEqual(cloned.id, row.id)
  assert.notEqual(cloned.columns[0].id, row.columns[0].id)
  assert.notEqual(cloned.columns[1].id, row.columns[1].id)
  assert.notEqual(cloned.columns[0].blocks[0].id, 'text-1')
  assert.notEqual(cloned.columns[1].blocks[0].id, 'button-1')
  assert.notStrictEqual(cloned.columns[0].blocks[0].content, text.content)
  assert.deepEqual(cloned.columns[0].blocks[0].content, text.content)
})

test('createBlock returns independent default content and visibility objects', () => {
  const first = createBlock('text')
  const second = createBlock('text')
  first.content.html = '<p>Changed</p>'
  first.visibility.conditions.push({ fieldname: 'name', operator: 'equals', value: 'A' })

  assert.equal(second.content.html, '<p>Write your message here</p>')
  assert.deepEqual(second.visibility.conditions, [])
  assert.notStrictEqual(first.content, second.content)
  assert.notStrictEqual(first.visibility, second.visibility)
})

test('social blocks start with email-safe HubSpot-style display defaults', () => {
  const social = createBlock('social')
  assert.equal(social.content.display, 'icon')
  assert.equal(social.content.icon_shape, 'circle')
  assert.equal(social.content.icon_size, 24)
  assert.equal(social.content.item_spacing, 8)
})

test('typographyCss writes rules only for the styles that have a font and ignores unsafe values', () => {
  assert.equal(typographyCss({}), '')
  const css = typographyCss({ h1_font_family: 'Georgia, serif', h1_font_size: '32px', h1_font_weight: '700', p_font_size: '15px' })
  assert.equal(css, '.canvas-stage .rich-text h1{font-family:Georgia, serif;font-size:32px;font-weight:700}\n.canvas-stage .rich-text p{font-size:15px}')
  assert.equal(typographyCss({ h2_font_family: 'x;}</style><script>', h2_font_size: 'huge', h2_font_weight: 'heavy', h3_font_size: '0px' }), '')
  assert.equal(typographyCss({ h3_font_size: '22' }), '.canvas-stage .rich-text h3{font-size:22px}')
})

test('a row from a shared header or footer follows the shared version until it is changed', () => {
  const header = section('h')
  header.saved_component = 'Megasol header'
  header.saved_component_category = 'Header'
  header.component_customised = false
  const plain = section('p')
  plain.saved_component = 'Some block'
  assert.deepEqual(sharedSectionState(header), { name: 'Megasol header', category: 'Header', customised: false })
  assert.equal(sharedSectionState(plain), null)

  const before = emptyDocument().schema
  before.sections = [header, plain]
  const same = JSON.parse(JSON.stringify(before))
  assert.deepEqual(markCustomisedSharedSections(before, same), [])
  const edited = JSON.parse(JSON.stringify(before))
  edited.sections[0].columns[0].blocks.push(block('new'))
  edited.sections[1].columns[0].blocks.push(block('other'))
  assert.deepEqual(markCustomisedSharedSections(before, edited), ['h'])
  assert.equal(edited.sections[0].component_customised, true)
  assert.equal(edited.sections[1].component_customised, undefined, 'a plain saved block is never linked')
})

test('resetting a customised shared row does not mark it customised again', () => {
  const header = section('h')
  header.saved_component = 'Megasol header'
  header.saved_component_category = 'Footer'
  header.component_customised = true
  const before = emptyDocument().schema
  before.sections = [header]
  const reset = JSON.parse(JSON.stringify(before))
  reset.sections[0].component_customised = false
  reset.sections[0].columns[0].blocks.push(block('shared-content'))
  assert.deepEqual(markCustomisedSharedSections(before, reset), [])
  assert.equal(reset.sections[0].component_customised, false)
})

test('button action values are checked for every action type', () => {
  assert.equal(buttonActionIssue('url', 'https://megasol.ch/offer'), '')
  assert.equal(buttonActionIssue('url', 'megasol.ch'), '')
  assert.match(buttonActionIssue('url', 'javascript:alert(1)'), /web address/)
  assert.equal(buttonActionIssue('email', 'info@megasol.ch'), '')
  assert.equal(buttonActionIssue('email', 'mailto:info@megasol.ch?subject=Hi'), '')
  assert.match(buttonActionIssue('email', 'not an email'), /email address/)
  assert.equal(buttonActionIssue('telephone', '+41 44 123 45 67'), '')
  assert.match(buttonActionIssue('telephone', 'abc'), /phone number/)
  assert.equal(buttonActionIssue('sms', '+41791234567'), '')
  assert.equal(buttonActionIssue('sms', 'sms:+41791234567?body=Hello%20there'), '')
  assert.equal(buttonActionIssue('sms', '+41791234567?body=Hello there, please call me'), '', 'spaces in the text are fine')
  assert.match(buttonActionIssue('sms', 'abc'), /mobile number/)
  assert.match(buttonActionIssue('sms', 'sms:abc'), /mobile number/)
  assert.equal(buttonActionIssue('file', '/files/brochure.pdf'), '')
  assert.match(buttonActionIssue('file', '/private/files/brochure.pdf'), /public file/)
  assert.match(buttonActionIssue('file', 'brochure.pdf'), /public file address/)
  assert.equal(buttonActionIssue('sms', '{{ mobile_no }}'), '', 'a merge field is checked when the email is sent')
  assert.equal(buttonActionIssue('sms', ''), '')
})
