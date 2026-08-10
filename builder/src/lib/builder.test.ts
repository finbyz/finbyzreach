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
  resizeSection,
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
