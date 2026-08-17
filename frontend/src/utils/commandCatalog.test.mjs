import assert from 'node:assert/strict'

import { createCommandCatalogCache } from './commandCatalog.mjs'

/**
 * 验证命令目录缓存、强制刷新、失败记录与重试。
 */
async function runCacheTests() {
  let calls = 0
  let shouldFail = false
  const versions = ['v1', 'v2']
  const cache = createCommandCatalogCache(async () => {
    calls += 1
    if (shouldFail) throw new Error('catalog unavailable')
    const version = versions[Math.min(calls - 1, versions.length - 1)]
    return {
      items: [{ name: 'plan', category: 'agent' }],
      total: 1,
      session_state: { plan_mode: calls >= 2 },
      catalog_version: version,
    }
  })

  const first = await cache.load('chat-1')
  assert.equal(calls, 1)
  assert.equal(first.catalogVersion, 'v1')
  assert.deepEqual(cache.state, {
    loading: false,
    error: '',
    items: first.items,
    sessionState: first.sessionState,
    catalogVersion: 'v1',
  })

  await cache.load('chat-1')
  assert.equal(calls, 1)

  const forced = await cache.load('chat-1', { force: true })
  assert.equal(calls, 2)
  assert.equal(forced.catalogVersion, 'v2')
  assert.equal(forced.sessionState.plan_mode, true)

  shouldFail = true
  await assert.rejects(
    () => cache.load('chat-2', { force: true }),
    /catalog unavailable/,
  )
  assert.equal(cache.state.error, 'catalog unavailable')

  shouldFail = false
  const retried = await cache.load('chat-2', { force: true })
  assert.equal(retried.catalogVersion, 'v2')
  assert.equal(cache.state.error, '')
  assert.equal(calls, 4)

  cache.invalidate()
  assert.equal(cache.state.catalogVersion, '')

}

/**
 * 验证快速切换会话时旧目录响应不会覆盖新目录状态。
 */
async function runStaleResponseTests() {
  let calls = 0
  const pending = new Map()
  const cache = createCommandCatalogCache((chatId) => new Promise((resolve, reject) => {
    calls += 1
    pending.set(chatId, { resolve, reject })
  }))

  const first = cache.load('chat-a', { force: true })
  const second = cache.load('chat-b', { force: true })
  pending.get('chat-b').resolve({
    items: [],
    total: 0,
    session_state: {},
    catalog_version: 'new',
  })
  pending.get('chat-a').resolve({
    items: [],
    total: 0,
    session_state: {},
    catalog_version: 'old',
  })

  assert.equal((await second).catalogVersion, 'new')
  assert.equal((await first).catalogVersion, 'new')
  assert.equal(cache.state.catalogVersion, 'new')
  assert.equal(calls, 2)
}

await runCacheTests()
await runStaleResponseTests()
console.log('commandCatalog tests passed')
