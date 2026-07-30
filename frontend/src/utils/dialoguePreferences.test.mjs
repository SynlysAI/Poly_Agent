import assert from 'node:assert/strict'

import {
  loadKnowledgePreference,
  loadWebSearchPreference,
  saveKnowledgePreference,
  saveWebSearchPreference,
} from './dialoguePreferences.js'

function createStorage(initial = {}) {
  const values = new Map(Object.entries(initial))
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null
    },
    setItem(key, value) {
      values.set(key, String(value))
    },
    removeItem(key) {
      values.delete(key)
    },
  }
}

const emptyStorage = createStorage()
assert.equal(loadWebSearchPreference(emptyStorage), false)
assert.deepEqual(loadKnowledgePreference(emptyStorage), [])

const webStorage = createStorage()
saveWebSearchPreference(true, webStorage)
assert.equal(loadWebSearchPreference(webStorage), true)
saveWebSearchPreference(false, webStorage)
assert.equal(loadWebSearchPreference(webStorage), false)

const knowledgeStorage = createStorage()
saveKnowledgePreference(['light-rag', '', 'weknora'], knowledgeStorage)
assert.deepEqual(loadKnowledgePreference(knowledgeStorage), ['light-rag', 'weknora'])
saveKnowledgePreference([], knowledgeStorage)
assert.deepEqual(loadKnowledgePreference(knowledgeStorage), [])

const legacyKnowledgeStorage = createStorage({
  'poly-agent-dialogue-knowledge-base-id': 'legacy-system',
})
assert.deepEqual(loadKnowledgePreference(legacyKnowledgeStorage), ['legacy-system'])
