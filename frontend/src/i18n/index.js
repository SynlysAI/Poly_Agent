import { computed, inject, ref, watch } from 'vue'

import { messages, staticTextTranslations } from './locales.js'

export const DEFAULT_LOCALE = 'zh-CN'
export const SUPPORTED_LOCALES = ['zh-CN', 'en-US']
export const LOCALE_STORAGE_KEY = 'poly-agent-locale'
export const I18N_INJECTION_KEY = Symbol('poly-agent-i18n')
let activeLocale = null

/** 读取当前语言，供非 Vue 组件的工具函数使用。 */
export function getCurrentLocale() {
  return activeLocale || readStoredLocale()
}

function readStoredLocale(storage = globalThis.localStorage) {
  try {
    const value = storage?.getItem(LOCALE_STORAGE_KEY)
    return SUPPORTED_LOCALES.includes(value) ? value : DEFAULT_LOCALE
  } catch {
    return DEFAULT_LOCALE
  }
}

function persistLocale(value, storage = globalThis.localStorage) {
  try {
    storage?.setItem(LOCALE_STORAGE_KEY, value)
  } catch {
    // 隐私模式或受限环境下无法持久化时仍保持当前页面可用。
  }
}

function interpolate(value, params = {}) {
  return String(value).replace(/\{(\w+)\}/g, (_, key) => String(params[key] ?? `{${key}}`))
}

/** 创建应用级语言状态，并同步浏览器语言标记。 */
export function createI18n() {
  const locale = ref(readStoredLocale())
  activeLocale = locale.value

  function setLocale(nextLocale) {
    if (!SUPPORTED_LOCALES.includes(nextLocale) || nextLocale === locale.value) return false
    locale.value = nextLocale
    activeLocale = nextLocale
    persistLocale(nextLocale)
    return true
  }

  function t(key, params = {}) {
    const current = messages[locale.value]?.[key]
    const fallback = messages[DEFAULT_LOCALE]?.[key]
    return interpolate(current ?? fallback ?? key, params)
  }

  function translateStaticText(text) {
    if (locale.value !== 'en-US') return text
    return staticTextTranslations[text] || text
  }

  watch(locale, value => {
    if (typeof document !== 'undefined') document.documentElement.lang = value
  }, { immediate: true })

  const api = {
    locale,
    currentLocale: computed(() => locale.value),
    setLocale,
    t,
    translateStaticText,
    supportedLocales: SUPPORTED_LOCALES,
  }
  return api
}

/** 注册全局语言状态。 */
export const i18nPlugin = {
  install(app) {
    const api = createI18n()
    app.provide(I18N_INJECTION_KEY, api)
    app.config.globalProperties.$t = api.t
    app.config.globalProperties.$locale = api.locale
  },
}

/** 在 setup 中取得全局语言状态。 */
export function useI18n() {
  const api = inject(I18N_INJECTION_KEY)
  if (!api) throw new Error('useI18n() must be called under createI18n()')
  return api
}

export { readStoredLocale, persistLocale }
