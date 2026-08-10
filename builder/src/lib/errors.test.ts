import assert from 'node:assert/strict'
import test from 'node:test'

import { getErrorMessage, getErrorStatus, isConcurrencyError } from './errors.ts'

test('getErrorStatus extracts status correctly from various structures', () => {
  assert.equal(getErrorStatus(undefined), undefined)
  assert.equal(getErrorStatus(null), undefined)
  assert.equal(getErrorStatus('string'), undefined)
  
  assert.equal(getErrorStatus({ status: 404 }), 404)
  assert.equal(getErrorStatus({ httpStatus: 403 }), 403)
  assert.equal(getErrorStatus({ http_status_code: 500 }), 500)
  
  assert.equal(getErrorStatus({ response: { status: 401 } }), 401)
  assert.equal(getErrorStatus({ response: { data: { status: 409 } } }), 409)
})

test('getErrorMessage extracts frappe server messages', () => {
  // Flat string
  assert.equal(getErrorMessage({ _server_messages: '["Message"]' }), 'Message')
  
  // Clean HTML
  assert.equal(getErrorMessage({ server_messages: '["<b>Bold</b><br>New line"]' }), 'Bold\nNew line')
  
  // Parse nested JSON strings
  assert.equal(
    getErrorMessage({ _server_messages: '["{\\"message\\": \\"Nested JSON\\"}"]' }),
    'Nested JSON'
  )
  
  // Array of messages
  assert.equal(
    getErrorMessage({ server_messages: '["Error 1", "Error 2"]' }),
    'Error 1\nError 2'
  )
  
  // Deduplicates messages
  assert.equal(
    getErrorMessage({ server_messages: '["Same", "Same"]' }),
    'Same'
  )
})

test('getErrorMessage handles exception tracebacks', () => {
  assert.equal(
    getErrorMessage({ exception: 'frappe.exceptions.ValidationError: Invalid data' }),
    'Invalid data'
  )
  
  // Ignores full tracebacks
  assert.equal(
    getErrorMessage({ exception: 'Traceback (most recent call last):' }),
    'Something went wrong'
  )
})

test('getErrorMessage handles standard error messages', () => {
  assert.equal(getErrorMessage(new Error('Standard error')), 'Standard error')
  assert.equal(getErrorMessage({ message: 'Plain message' }), 'Plain message')
})

test('getErrorMessage falls back to status messages', () => {
  assert.equal(getErrorMessage({ status: 404 }), 'The requested record was not found.')
  assert.equal(getErrorMessage({ status: 403 }), 'You do not have permission to complete this action.')
  assert.equal(getErrorMessage({ status: 500 }), 'The server could not complete this action.')
  assert.equal(getErrorMessage({ status: 999 }), 'Something went wrong')
})

test('getErrorMessage handles deeply nested response objects', () => {
  const error = {
    response: {
      data: {
        message: {
          errors: ['Deep error']
        }
      }
    }
  }
  assert.equal(getErrorMessage(error), 'Deep error')
})

test('getErrorMessage safely handles circular or excessively deep structures', () => {
  const error: Record<string, unknown> = {}
  error.response = { data: { message: error } } // Circular
  // Shouldn't crash, will hit depth limit and return fallback
  assert.equal(getErrorMessage(error), 'Something went wrong')
})

test('isConcurrencyError recognizes stale document saves', () => {
  assert.equal(isConcurrencyError({ status: 409 }), true)
  assert.equal(isConcurrencyError({ exception: 'frappe.exceptions.TimestampMismatchError: Document changed' }), true)
  assert.equal(isConcurrencyError({ _server_messages: '["This template changed in another window. Reload before continuing."]' }), true)
  assert.equal(isConcurrencyError(new Error('Network unavailable')), false)
})
