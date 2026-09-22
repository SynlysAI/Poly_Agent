<script setup>
import { useI18n } from '../i18n/index.js'

const { locale, t, setLocale } = useI18n()
</script>

<template>
  <div class="locale-switcher" role="group" :aria-label="t('locale.switchTo', { language: locale === 'zh-CN' ? t('locale.english') : t('locale.chinese') })">
    <button type="button" :class="{ active: locale === 'zh-CN' }" :aria-pressed="locale === 'zh-CN'" @click="setLocale('zh-CN')">中</button>
    <span aria-hidden="true">/</span>
    <button type="button" :class="{ active: locale === 'en-US' }" :aria-pressed="locale === 'en-US'" @click="setLocale('en-US')">EN</button>
  </div>
</template>

<style scoped>
.locale-switcher {
  position: absolute;
  top: 18px;
  right: 18px;
  z-index: 2;
}

.locale-switcher button {
  min-width: 25px;
  padding: 4px 5px;
  border: 0;
  border-radius: 9999px;
  background: transparent;
  color: #64748b;
  font: inherit;
  font-size: 12px;
  cursor: pointer;
}

.locale-switcher button.active {
  background: #e5efff;
  color: #1d4ed8;
  font-weight: 700;
}
</style>
