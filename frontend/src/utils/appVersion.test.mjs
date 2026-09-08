import assert from 'node:assert/strict'

import {
  APP_VERSION_FALLBACK,
  APP_LATEST_RELEASE_API_URL,
  buildAppReleaseUrl,
  fetchLatestAppVersion,
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

function createReleaseResponse(payload, ok = true) {
  return { ok, json: async () => payload }
}

assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => createReleaseResponse({ tag_name: 'v1.2.3' }) }),
  '1.2.3',
)
assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => createReleaseResponse({ tag_name: 'v2.0.0-rc.1' }) }),
  '2.0.0-rc.1',
)
assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => createReleaseResponse({}, false) }),
  null,
)
assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => createReleaseResponse({}) }),
  null,
)
assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => createReleaseResponse({ tag_name: 'develop' }) }),
  null,
)
assert.equal(
  await fetchLatestAppVersion({ fetchImpl: async () => { throw new Error('network error') } }),
  null,
)
assert.equal(await fetchLatestAppVersion({ fetchImpl: undefined }), null)

let requestedUrl = ''
await fetchLatestAppVersion({
  fetchImpl: async (url) => {
    requestedUrl = url
    return createReleaseResponse({ tag_name: 'v1.0.0' })
  },
})
assert.equal(requestedUrl, APP_LATEST_RELEASE_API_URL)

console.log('app version tests passed')
