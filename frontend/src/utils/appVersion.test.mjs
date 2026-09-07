import assert from 'node:assert/strict'

import {
  APP_VERSION_FALLBACK,
  buildAppReleaseUrl,
  normalizeAppVersion,
} from './appVersion.mjs'

assert.equal(APP_VERSION_FALLBACK, '1.0.0')
assert.equal(normalizeAppVersion(' v1.0.0 '), '1.0.0')
assert.equal(normalizeAppVersion('v1.2.3-rc.1'), '1.2.3-rc.1')
assert.equal(normalizeAppVersion('', APP_VERSION_FALLBACK), APP_VERSION_FALLBACK)
assert.equal(normalizeAppVersion('develop', APP_VERSION_FALLBACK), APP_VERSION_FALLBACK)
assert.equal(
  buildAppReleaseUrl('1.0.0'),
  'https://github.com/SynlysAI/Poly_Agent/releases/tag/v1.0.0',
)

console.log('app version tests passed')
