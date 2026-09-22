import en from 'element-plus/es/locale/lang/en'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

/** 返回 Element Plus 当前语言包。 */
export function getElementLocale(locale) {
  return locale === 'en-US' ? en : zhCn
}
