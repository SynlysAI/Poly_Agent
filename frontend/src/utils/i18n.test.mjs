import assert from 'node:assert/strict'

const storage = new Map()
const fakeStorage = {
  getItem: key => storage.get(key) ?? null,
  setItem: (key, value) => storage.set(key, value),
}

const source = await import('../i18n/index.js')
const { DEFAULT_LOCALE, LOCALE_STORAGE_KEY, readStoredLocale, persistLocale, createI18n } = source

assert.equal(DEFAULT_LOCALE, 'zh-CN')
assert.equal(readStoredLocale(fakeStorage), 'zh-CN')
persistLocale('en-US', fakeStorage)
assert.equal(fakeStorage.getItem(LOCALE_STORAGE_KEY), 'en-US')
assert.equal(readStoredLocale(fakeStorage), 'en-US')
persistLocale('fr-FR', fakeStorage)
assert.equal(readStoredLocale(fakeStorage), 'zh-CN')

globalThis.localStorage = fakeStorage
const i18n = createI18n()
assert.equal(i18n.locale.value, 'zh-CN')
assert.equal(i18n.t('app.releaseNotes', { version: '1.2.0' }), '查看 Poly Agent v1.2.0 发布说明')
assert.equal(i18n.t('dashboard.brand'), 'Poly Agent 工作台')
assert.equal(i18n.t('app.partnersList'), '智储大装置（IESI）｜嘉庚实验室（IKKEM）｜厦门大学（XMU）｜苏州实验室（SZLAB）｜浦江实验室（AILAB）')
assert.equal(i18n.setLocale('en-US'), true)
assert.equal(i18n.locale.value, 'en-US')
assert.equal(i18n.t('app.releaseNotes', { version: '1.2.0' }), 'View Poly Agent v1.2.0 release notes')
assert.equal(i18n.t('dashboard.brand'), 'Poly Agent Workspace')
assert.equal(i18n.t('app.partnersList'), 'IESI｜IKKEM｜XMU｜SZLAB｜AILAB')
assert.equal(i18n.setLocale('fr-FR'), false)
assert.equal(i18n.t('missing.key'), 'missing.key')
console.log('i18n utility tests passed')
