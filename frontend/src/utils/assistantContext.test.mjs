import assert from 'node:assert/strict'

import {
  assistantContextLabel,
  assistantContextTooltip,
  normalizeAssistantContextDigest,
} from './assistantContext.js'

const digest = 'sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef'

assert.equal(normalizeAssistantContextDigest(null), '')
assert.equal(normalizeAssistantContextDigest(42), '')
assert.equal(normalizeAssistantContextDigest('sha256:abc'), 'sha256:abc')
assert.equal(assistantContextLabel({ context_digest: digest }), '上下文 abcdef')
assert.equal(assistantContextLabel({ context_digest: '' }), '')
assert.equal(assistantContextTooltip({ context_digest: digest }), digest)
assert.equal(assistantContextTooltip({}), '')

console.log('assistant context meta tests passed')
