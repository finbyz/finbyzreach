import assert from 'node:assert/strict'
import test from 'node:test'

import {
  conditionFieldOptions,
  conditionOperatorOptions,
  defaultConditionValue,
  normalizeConditionForField,
} from './conditionFields.ts'
import type { MergeField, VisibilityCondition } from '../types.ts'

function field(fieldtype: string, options = ''): MergeField {
  return { fieldname: 'status', label: 'Status', fieldtype, options }
}

const base: VisibilityCondition = { fieldname: 'status', operator: 'contains', value: 'Draft' }

test('conditionFieldOptions parses Frappe Select options safely', () => {
  assert.deepEqual(conditionFieldOptions(field('Select', '\nDraft\nSubmitted\nCancelled\n')), [
    { value: 'Draft', label: 'Draft' },
    { value: 'Submitted', label: 'Submitted' },
    { value: 'Cancelled', label: 'Cancelled' },
  ])
})

test('Check fields use boolean-friendly operators and values', () => {
  assert.deepEqual(conditionOperatorOptions(field('Check')).map(([key]) => key), ['equals', 'not_equals', 'empty', 'not_empty'])
  assert.equal(defaultConditionValue(field('Check')), '1')
  assert.deepEqual(normalizeConditionForField(base, field('Check')), { fieldname: 'status', operator: 'equals', value: '1' })
})

test('Select fields reject contains operator and keep valid choices', () => {
  const select = field('Select', 'Draft\nSubmitted')
  assert.deepEqual(conditionOperatorOptions(select).map(([key]) => key), ['equals', 'not_equals', 'empty', 'not_empty'])
  assert.equal(defaultConditionValue(select), 'Draft')
  assert.deepEqual(normalizeConditionForField(base, select), { fieldname: 'status', operator: 'equals', value: 'Draft' })
})

test('MultiSelect fields prefer contains semantics', () => {
  const multi = field('MultiSelect', 'Solar\nBattery')
  assert.deepEqual(conditionOperatorOptions(multi).map(([key]) => key), ['contains', 'not_contains', 'empty', 'not_empty'])
  assert.equal(defaultConditionValue(multi), 'Solar')
  assert.deepEqual(normalizeConditionForField({ ...base, operator: 'equals' }, multi), { fieldname: 'status', operator: 'contains', value: 'Draft' })
})

test('Link fields use record identity operators instead of text contains', () => {
  const link = field('Link', 'User')
  assert.deepEqual(conditionOperatorOptions(link).map(([key]) => key), ['equals', 'not_equals', 'empty', 'not_empty'])
  assert.equal(normalizeConditionForField({ fieldname: 'lead_owner', operator: 'contains', value: 'Administrator' }, link).operator, 'equals')
})
