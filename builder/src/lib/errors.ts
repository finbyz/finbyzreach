type UnknownRecord = Record<string, unknown>

const statusMessages: Record<number, string> = {
  400: 'The request could not be processed. Check the entered information.',
  401: 'Your session has expired. Sign in again.',
  403: 'You do not have permission to complete this action.',
  404: 'The requested record was not found.',
  409: 'This template changed elsewhere. Reload and try again.',
  413: 'The submitted email design is too large.',
  417: 'A builder validation rule failed.',
  429: 'Too many requests were made. Wait and try again.',
  500: 'The server could not complete this action.',
}

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function parseJson(value: unknown): unknown {
  let parsed = value
  for (let attempt = 0; attempt < 4 && typeof parsed === 'string'; attempt += 1) {
    try { parsed = JSON.parse(parsed) } catch { break }
  }
  return parsed
}

function clean(value: string) {
  return value
    .replace(/<br\s*\/?\s*>/gi, '\n')
    .replace(/<[^>]+>/g, '')
    .replace(/&amp;/gi, '&')
    .replace(/&lt;/gi, '<')
    .replace(/&gt;/gi, '>')
    .replace(/&quot;/gi, '"')
    .trim()
}

function collect(value: unknown, output: string[], depth = 0) {
  if (depth > 5 || value == null) return
  const parsed = parseJson(value)
  if (typeof parsed === 'string') {
    const message = clean(parsed)
    if (message && !message.toLowerCase().startsWith('traceback')) output.push(message)
    return
  }
  if (Array.isArray(parsed)) return parsed.forEach((item) => collect(item, output, depth + 1))
  if (!isRecord(parsed)) return
  collect(parsed.message, output, depth + 1)
  collect(parsed.errors, output, depth + 1)
}

function records(error: unknown) {
  const found: UnknownRecord[] = []
  if (isRecord(error)) found.push(error)
  if (isRecord(error) && isRecord(error.response) && isRecord(error.response.data)) found.push(error.response.data)
  return found
}

export function getErrorStatus(error: unknown) {
  for (const item of records(error)) {
    const response = isRecord(item.response) ? item.response : undefined
    const status = item.httpStatus || item.http_status_code || item.status || response?.status
    if (typeof status === 'number') return status
  }
  return undefined
}

export function getErrorMessage(error: unknown, fallback = 'Something went wrong') {
  const messages: string[] = []
  for (const item of records(error)) {
    collect(item._server_messages, messages)
    collect(item.server_messages, messages)
  }
  if (messages.length) return Array.from(new Set(messages)).join('\n')
  for (const item of records(error)) {
    if (typeof item.exception === 'string' && !item.exception.includes('Traceback')) {
      const message = clean(item.exception.split(':').slice(1).join(':'))
      if (message) return message
    }
    collect(item.message, messages)
  }
  if (error instanceof Error) collect(error.message, messages)
  if (messages.length) return messages[0]
  const status = getErrorStatus(error)
  return (status && statusMessages[status]) || fallback
}

/** True when Frappe rejected a stale document version. */
export function isConcurrencyError(error: unknown) {
  if (getErrorStatus(error) === 409) return true
  const rawDetails = records(error)
    .flatMap((item) => [item.exception, item.message, item._server_messages, item.server_messages])
    .filter((value): value is string => typeof value === 'string')
  return /timestampmismatcherror|changed in another window|modified after you have opened|please refresh to get the latest document/i.test(
    [getErrorMessage(error, ''), ...rawDetails].join('\n'),
  )
}
