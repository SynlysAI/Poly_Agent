export const WEB_SEARCH_STORAGE_KEY = 'poly-agent-dialogue-use-web-search'
export const KNOWLEDGE_STORAGE_KEY = 'poly-agent-dialogue-knowledge-base-id'

function resolveStorage(storage) {
  if (storage) return storage
  try {
    return globalThis.window?.localStorage || globalThis.localStorage || null
  } catch {
    return null
  }
}

export function normalizeWebSearchPreference(value, fallback = false) {
  if (value === null || value === undefined) return fallback
  if (typeof value === 'boolean') return value
  if (typeof value === 'number') return Boolean(value)
  const normalized = String(value).trim().toLowerCase()
  if (['1', 'true', 'yes', 'on'].includes(normalized)) return true
  if (['0', 'false', 'no', 'off'].includes(normalized)) return false
  return fallback
}

export function loadWebSearchPreference(storage) {
  const target = resolveStorage(storage)
  if (!target) return false
  return normalizeWebSearchPreference(target.getItem(WEB_SEARCH_STORAGE_KEY), false)
}

export function saveWebSearchPreference(value, storage) {
  const target = resolveStorage(storage)
  if (!target) return
  target.setItem(WEB_SEARCH_STORAGE_KEY, normalizeWebSearchPreference(value) ? '1' : '0')
}

export function normalizeKnowledgePreference(value) {
  const rawItems = Array.isArray(value) ? value : [value]
  return rawItems
    .map((item) => String(item || '').trim())
    .filter(Boolean)
}

export function loadKnowledgePreference(storage) {
  const target = resolveStorage(storage)
  if (!target) return []
  const raw = target.getItem(KNOWLEDGE_STORAGE_KEY) || ''
  if (!raw) return []
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return normalizeKnowledgePreference(parsed)
  } catch {
    return normalizeKnowledgePreference(raw)
  }
  return normalizeKnowledgePreference(raw)
}

export function saveKnowledgePreference(value, storage) {
  const target = resolveStorage(storage)
  if (!target) return
  const ids = normalizeKnowledgePreference(value)
  if (ids.length) {
    target.setItem(KNOWLEDGE_STORAGE_KEY, JSON.stringify(ids))
  } else {
    target.removeItem(KNOWLEDGE_STORAGE_KEY)
  }
}
