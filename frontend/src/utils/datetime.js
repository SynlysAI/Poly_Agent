function isIsoDateTimeWithoutTimezone(value) {
  return /^\d{4}-\d{2}-\d{2}T/.test(value) && !/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value)
}

export function parseApiDateTime(value) {
  if (!value) return null
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value
  }
  const raw = typeof value === 'string' ? value.trim() : value
  const normalized = typeof raw === 'string' && isIsoDateTimeWithoutTimezone(raw) ? `${raw}Z` : raw
  const date = new Date(normalized)
  return Number.isNaN(date.getTime()) ? null : date
}

export function formatApiDateTime(value) {
  const date = parseApiDateTime(value)
  return date ? date.toLocaleString() : (value || '-')
}

export function apiDateTimeMs(value) {
  return parseApiDateTime(value)?.getTime() ?? Number.NaN
}
