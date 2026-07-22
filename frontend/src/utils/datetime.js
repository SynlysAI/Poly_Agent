export const APP_DISPLAY_TIME_ZONE = import.meta.env.VITE_APP_TIME_ZONE || 'Asia/Shanghai'

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
  return date ? date.toLocaleString('zh-CN', { timeZone: APP_DISPLAY_TIME_ZONE, hour12: false }) : (value || '-')
}

export function apiDateTimeMs(value) {
  return parseApiDateTime(value)?.getTime() ?? Number.NaN
}

export function formatAppDate(value = new Date()) {
  const date = value instanceof Date ? value : parseApiDateTime(value)
  if (!date) return '-'
  const parts = new Intl.DateTimeFormat('zh-CN', {
    timeZone: APP_DISPLAY_TIME_ZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(date)
  const partValue = type => parts.find(part => part.type === type)?.value || ''
  return `${partValue('year')}-${partValue('month')}-${partValue('day')}`
}
