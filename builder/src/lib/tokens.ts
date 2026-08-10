import type { BuilderDocument, MergeField } from '../types'

export type TokenValidationIssueCode =
  | 'empty_dynamic_field'
  | 'unsupported_jinja'
  | 'invalid_dynamic_field_syntax'
  | 'missing_reference_doctype'

export type TokenValidationIssue = {
  code: TokenValidationIssueCode
  message: string
  fields?: string[]
}

const FIELD_PATH_SOURCE = '[A-Za-z_][A-Za-z0-9_]*(?:\\.[A-Za-z_][A-Za-z0-9_]*)?'
const VALID_TOKEN_RE = new RegExp(`{{\\s*(${FIELD_PATH_SOURCE})\\s*(?:\\|\\s*default\\(\\s*(?:"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*')\\s*(?:,\\s*true)?\\s*\\))?\\s*}}`, 'g')
const VALID_TOKEN_FULL_RE = new RegExp(`^{{\\s*(${FIELD_PATH_SOURCE})\\s*(?:\\|\\s*default\\(\\s*(?:"(?:\\\\.|[^"\\\\])*"|'(?:\\\\.|[^'\\\\])*')\\s*(?:,\\s*true)?\\s*\\))?\\s*}}$`)
const ANY_TOKEN_RE = /{{[\s\S]*?}}/g
const EMPTY_TOKEN_RE = /{{\s*}}/
const JINJA_BLOCK_RE = /{[%#]|[%#]}/
const FIELDNAME_RE = /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)?$/

export function buildMergeToken(fieldname: string, fallback = '') {
  const safeFieldname = String(fieldname || '').trim()
  if (!FIELDNAME_RE.test(safeFieldname)) {
    throw new Error('Invalid dynamic field name')
  }
  const safeFallback = String(fallback || '')
  return safeFallback
    ? `{{ ${safeFieldname}|default(${JSON.stringify(safeFallback)}, true) }}`
    : `{{ ${safeFieldname} }}`
}

export function isValidMergeToken(value: string) {
  return VALID_TOKEN_FULL_RE.test(String(value || ''))
}

function pushIssue(issues: TokenValidationIssue[], issue: TokenValidationIssue) {
  if (!issues.some((existing) => existing.code === issue.code && existing.message === issue.message)) {
    issues.push(issue)
  }
}

export function collectDynamicFields(value: unknown, output = new Set<string>()) {
  if (typeof value === 'string') {
    VALID_TOKEN_RE.lastIndex = 0
    let match = VALID_TOKEN_RE.exec(value)
    while (match) {
      output.add(match[1])
      match = VALID_TOKEN_RE.exec(value)
    }
    return output
  }

  if (Array.isArray(value)) {
    value.forEach((item) => collectDynamicFields(item, output))
    return output
  }

  if (!value || typeof value !== 'object') return output

  const record = value as Record<string, unknown>
  if (typeof record.fieldname === 'string' && typeof record.operator === 'string') {
    output.add(record.fieldname)
  }
  Object.values(record).forEach((item) => collectDynamicFields(item, output))
  return output
}

function validateStringTokens(value: string, issues: TokenValidationIssue[]) {
  if (!/[{}]/.test(value)) return

  const hasEmptyToken = EMPTY_TOKEN_RE.test(value)
  if (hasEmptyToken) {
    pushIssue(issues, {
      code: 'empty_dynamic_field',
      message: 'Empty dynamic fields like {{ }} are not allowed. Choose a field or remove the braces.',
    })
  }

  if (JINJA_BLOCK_RE.test(value)) {
    pushIssue(issues, {
      code: 'unsupported_jinja',
      message: 'Visual templates support merge fields only. Use {{ field_name }} here, or switch this template to Raw HTML for custom Jinja blocks.',
    })
  }

  const tokens = value.match(ANY_TOKEN_RE) || []
  const hasInvalidClosedToken = tokens.some((token) => !VALID_TOKEN_FULL_RE.test(token))

  VALID_TOKEN_RE.lastIndex = 0
  const remainder = value.replace(VALID_TOKEN_RE, '')
  const hasUnmatchedBraces = remainder.includes('{{') || remainder.includes('}}')

  if (!hasEmptyToken && (hasInvalidClosedToken || hasUnmatchedBraces)) {
    pushIssue(issues, {
      code: 'invalid_dynamic_field_syntax',
      message: 'Invalid dynamic field syntax. Use {{ field_name }}, {{ link_field.target_field }}, or add a fallback.',
    })
  }
}

export function validateMergeTokenSyntax(value: unknown, issues: TokenValidationIssue[] = []) {
  if (typeof value === 'string') {
    validateStringTokens(value, issues)
    return issues
  }

  if (Array.isArray(value)) {
    value.forEach((item) => validateMergeTokenSyntax(item, issues))
    return issues
  }

  if (!value || typeof value !== 'object') return issues

  Object.values(value as Record<string, unknown>).forEach((item) => validateMergeTokenSyntax(item, issues))
  return issues
}

export function getDynamicFieldValidation(document: BuilderDocument, mergeFields: MergeField[], mergeFieldsLoading: boolean, mergeFieldsError: unknown) {
  const metadata = document.metadata
  const valuesToCheck = [document.schema, metadata.subject, metadata.preheader]
  const syntaxIssues = validateMergeTokenSyntax(valuesToCheck)
  const usedFields = collectDynamicFields(valuesToCheck)
  const invalidFields: string[] = []
  const issues = [...syntaxIssues]

  if (!metadata.validate_dynamic_fields || !usedFields.size) {
    return { invalidFields, issues, usedFields: Array.from(usedFields).sort() }
  }

  if (!metadata.reference_doctype) {
    pushIssue(issues, {
      code: 'missing_reference_doctype',
      message: 'Choose a Reference DocType before validating dynamic fields, or turn validation off for a generic template.',
      fields: Array.from(usedFields).sort(),
    })
    return { invalidFields: Array.from(usedFields).sort(), issues, usedFields: Array.from(usedFields).sort() }
  }

  if (mergeFieldsLoading || mergeFieldsError) {
    return { invalidFields, issues, usedFields: Array.from(usedFields).sort() }
  }

  const allowedFields = new Set(mergeFields.map((field) => field.fieldname))
  const allowedLinkRoots = new Set(
    mergeFields.filter((field) => field.fieldtype === 'Link' && field.options).map((field) => field.fieldname),
  )
  invalidFields.push(...Array.from(usedFields).filter((fieldname) => {
    if (allowedFields.has(fieldname)) return false
    const [root, child, extra] = fieldname.split('.')
    return Boolean(extra) || !child || !allowedLinkRoots.has(root)
  }).sort())
  return { invalidFields, issues, usedFields: Array.from(usedFields).sort() }
}
