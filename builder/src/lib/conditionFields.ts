import type { MergeField, VisibilityCondition } from '../types'

export const CONDITION_OPERATORS: Array<[VisibilityCondition['operator'], string]> = [
  ['equals', 'equals'],
  ['not_equals', 'does not equal'],
  ['contains', 'contains'],
  ['not_contains', 'does not contain'],
  ['empty', 'is empty'],
  ['not_empty', 'is not empty'],
]

export const CONDITION_VALUE_OPERATORS = new Set<VisibilityCondition['operator']>(['equals', 'not_equals', 'contains', 'not_contains'])

const CHECK_OPERATORS: Array<[VisibilityCondition['operator'], string]> = [
  ['equals', 'is'],
  ['not_equals', 'is not'],
  ['empty', 'is empty'],
  ['not_empty', 'is not empty'],
]

const SELECT_OPERATORS: Array<[VisibilityCondition['operator'], string]> = [
  ['equals', 'equals'],
  ['not_equals', 'does not equal'],
  ['empty', 'is empty'],
  ['not_empty', 'is not empty'],
]

const MULTI_SELECT_OPERATORS: Array<[VisibilityCondition['operator'], string]> = [
  ['contains', 'contains'],
  ['not_contains', 'does not contain'],
  ['empty', 'is empty'],
  ['not_empty', 'is not empty'],
]

export function conditionFieldType(field?: Pick<MergeField, 'fieldtype'> | null) {
  return String(field?.fieldtype || '').trim()
}

export function isCheckField(field?: Pick<MergeField, 'fieldtype'> | null) {
  return conditionFieldType(field) === 'Check'
}

export function isSelectField(field?: Pick<MergeField, 'fieldtype'> | null) {
  return ['Select', 'Autocomplete'].includes(conditionFieldType(field))
}

export function isMultiSelectField(field?: Pick<MergeField, 'fieldtype'> | null) {
  return conditionFieldType(field) === 'MultiSelect'
}

export function isLinkField(field?: Pick<MergeField, 'fieldtype'> | null) {
  return conditionFieldType(field) === 'Link'
}

export function conditionFieldOptions(field?: Pick<MergeField, 'options'> | null) {
  return String(field?.options || '')
    .split('\n')
    .map((option) => option.trim())
    .filter((option) => option && !option.startsWith('{') && !option.startsWith('['))
    .map((option) => ({ value: option, label: option }))
}

export function conditionOperatorOptions(field?: Pick<MergeField, 'fieldtype'> | null) {
  if (isCheckField(field)) return CHECK_OPERATORS
  if (isMultiSelectField(field)) return MULTI_SELECT_OPERATORS
  if (isSelectField(field) || isLinkField(field)) return SELECT_OPERATORS
  return CONDITION_OPERATORS
}

export function conditionNeedsValue(operator: VisibilityCondition['operator']) {
  return CONDITION_VALUE_OPERATORS.has(operator)
}

export function defaultConditionOperator(field?: Pick<MergeField, 'fieldtype'> | null): VisibilityCondition['operator'] {
  if (isMultiSelectField(field)) return 'contains'
  return 'equals'
}

export function defaultConditionValue(field?: Pick<MergeField, 'fieldtype' | 'options'> | null) {
  if (isCheckField(field)) return '1'
  return conditionFieldOptions(field)[0]?.value || ''
}

export function normalizeConditionForField(condition: VisibilityCondition, field?: Pick<MergeField, 'fieldtype' | 'options'> | null): VisibilityCondition {
  const allowedOperators = new Set(conditionOperatorOptions(field).map(([operator]) => operator))
  const operator = allowedOperators.has(condition.operator) ? condition.operator : defaultConditionOperator(field)
  const needsValue = conditionNeedsValue(operator)
  let value = needsValue ? String(condition.value ?? '') : ''

  if (needsValue && isCheckField(field) && !['0', '1'].includes(value)) value = '1'
  const options = conditionFieldOptions(field)
  if (needsValue && options.length && isSelectField(field) && !options.some((option) => option.value === value)) {
    value = options[0].value
  }

  return { ...condition, operator, value }
}
