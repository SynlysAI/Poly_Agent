<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { InfoFilled, Link } from '@element-plus/icons-vue'

import { getApiErrorMessage, getModuleAttribution } from '../../api/polyAgentApi'
import AttributionLogoStrip from './AttributionLogoStrip.vue'

const props = defineProps({
  moduleId: { type: String, default: '' },
  title: { type: String, default: '' },
  summary: { type: String, default: '' },
  implementationBoundary: { type: String, default: '' },
  attributions: { type: Array, default: () => [] },
  compact: { type: Boolean, default: false },
  embedded: { type: Boolean, default: false },
  label: { type: String, default: '' },
})

const loading = ref(false)
const errorText = ref('')
const moduleData = ref(null)
const drawerVisible = ref(false)
const drawerMode = ref('selected')
const selectedAttributionKey = ref('')
const logoStripLimit = 3

const resolvedTitle = computed(() => props.title || moduleData.value?.title || '来源')
const resolvedSummary = computed(() => props.summary || moduleData.value?.summary || '')
const publicAttributionItems = computed(() => {
  const internalNames = new Set(['polyagent', 'poly agent'])
  const sourceItems = props.attributions.length ? props.attributions : (moduleData.value?.attributions || [])
  return sourceItems.filter((item) => {
    const name = String(item?.name || '').trim().toLowerCase()
    const organization = String(item?.organization || '').trim().toLowerCase()
    return !internalNames.has(name) && !internalNames.has(organization)
  })
})
const resolvedAttributions = computed(() => {
  return publicAttributionItems.value
})
const prominentItems = computed(() => {
  const items = resolvedAttributions.value.filter(item => item.visibility === 'prominent')
  return items.length ? items : resolvedAttributions.value
})
const hiddenAttributionKeys = computed(() => new Set(prominentItems.value.slice(logoStripLimit).map(itemKey)))
const drawerAttributions = computed(() => {
  const items = [...resolvedAttributions.value]
  if (drawerMode.value === 'hidden') {
    return items.sort((a, b) => Number(hiddenAttributionKeys.value.has(itemKey(b))) - Number(hiddenAttributionKeys.value.has(itemKey(a))))
  }
  if (!selectedAttributionKey.value) return items
  return items.sort((a, b) => Number(itemKey(b) === selectedAttributionKey.value) - Number(itemKey(a) === selectedAttributionKey.value))
})
const resolvedLabel = computed(() => {
  if (props.label) return props.label
  const firstRole = prominentItems.value[0]?.role || ''
  const map = {
    framework_reference: '参考框架',
    method_reference: '方法来源',
    implementation_source: '服务来自',
    dependency: '工具支持',
    developer: '算法开发者',
  }
  return map[firstRole] || '来源'
})
const drawerLeadText = computed(() => {
  if (drawerMode.value === 'hidden') {
    const count = hiddenAttributionKeys.value.size
    return count ? `还有 ${count} 个来源已收起。` : '主要来源如下。'
  }
  return '来源说明保持简要，完整引用见项目文档。'
})

function itemKey(item) {
  return `${item?.role || ''}-${item?.name || ''}-${item?.organization || ''}`
}

function displayName(item) {
  return item?.organization || item?.name || '来源'
}

function isPrioritized(item) {
  if (drawerMode.value === 'hidden') return hiddenAttributionKeys.value.has(itemKey(item))
  return itemKey(item) === selectedAttributionKey.value
}

function openAttributionDrawer(item) {
  selectedAttributionKey.value = itemKey(item)
  drawerMode.value = 'selected'
  drawerVisible.value = true
}

function openHiddenAttributionsDrawer() {
  selectedAttributionKey.value = ''
  drawerMode.value = 'hidden'
  drawerVisible.value = true
}

async function loadModuleAttribution() {
  if (!props.moduleId) return
  loading.value = true
  errorText.value = ''
  try {
    moduleData.value = await getModuleAttribution(props.moduleId)
  } catch (error) {
    errorText.value = getApiErrorMessage(error)
  } finally {
    loading.value = false
  }
}

watch(() => props.moduleId, loadModuleAttribution)
onMounted(loadModuleAttribution)
</script>

<template>
  <section v-if="resolvedAttributions.length || moduleId" class="attribution-banner-wrap">
    <div class="attribution-banner" :class="{ compact, embedded }" v-loading="loading">
      <div class="attribution-copy">
        <div class="attribution-kicker">
          <el-icon><InfoFilled /></el-icon>
          <span>{{ resolvedLabel }}</span>
        </div>
        <h3 v-if="!embedded && !compact">{{ resolvedTitle }}</h3>
        <p>{{ errorText || resolvedSummary || '展示主要机构和方法来源。' }}</p>
      </div>
      <AttributionLogoStrip
        :items="prominentItems"
        :limit="logoStripLimit"
        @select="openAttributionDrawer"
        @open-more="openHiddenAttributionsDrawer"
      />
    </div>
    <el-drawer
      v-model="drawerVisible"
      class="attribution-drawer"
      direction="rtl"
      size="min(420px, 92vw)"
      title="引用来源"
    >
      <div class="attribution-drawer-content">
        <div class="drawer-intro">
          <strong>{{ resolvedTitle }}</strong>
          <p>{{ drawerLeadText }}</p>
        </div>
        <div class="drawer-source-list">
          <article
            v-for="item in drawerAttributions"
            :key="itemKey(item)"
            class="drawer-source-card"
            :class="{ prioritized: isPrioritized(item) }"
          >
            <div>
              <span class="source-role">{{ resolvedLabel }}</span>
              <h3>{{ displayName(item) }}</h3>
              <p v-if="item.description">{{ item.description }}</p>
              <p v-if="item.citation_text" class="source-citation">{{ item.citation_text }}</p>
            </div>
            <a
              v-if="item.url"
              class="source-link-button"
              :href="item.url"
              target="_blank"
              rel="noopener noreferrer"
            >
              <el-icon><Link /></el-icon>
              <span>打开来源</span>
            </a>
          </article>
        </div>
      </div>
    </el-drawer>
  </section>
</template>

<style scoped>
.attribution-banner-wrap {
  min-width: 0;
}

.attribution-banner {
  min-width: 0;
  padding: 14px 18px;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-lg);
  background: #fff;
  box-shadow: var(--app-card-shadow);
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, auto);
  align-items: center;
  gap: 18px;
}

.attribution-banner.embedded {
  padding: 0;
  border: 0;
  border-radius: 0;
  background: transparent;
  box-shadow: none;
}

.attribution-banner.compact {
  padding: 12px 14px;
  border-radius: var(--app-radius-md);
  box-shadow: none;
}

.attribution-copy {
  min-width: 0;
}

.attribution-kicker {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: var(--app-primary-active);
  font-size: 12px;
  font-weight: 700;
}

.attribution-copy h3 {
  margin: 4px 0;
  color: var(--app-ink);
  font-size: 16px;
  line-height: 1.35;
}

.attribution-copy p {
  margin: 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

@media (max-width: 900px) {
  .attribution-banner {
    grid-template-columns: 1fr;
  }
}

.attribution-drawer-content {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.drawer-intro {
  padding-bottom: 12px;
  border-bottom: 1px solid var(--app-border-soft);
}

.drawer-intro strong {
  display: block;
  color: var(--app-ink);
  font-size: 15px;
  line-height: 1.4;
}

.drawer-intro p {
  margin: 4px 0 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
}

.drawer-source-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.drawer-source-card {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.drawer-source-card.prioritized {
  border-color: var(--app-primary);
  background: #f8fbff;
}

.source-role {
  display: block;
  color: var(--app-ink-muted);
  font-size: 12px;
  line-height: 1.4;
}

.drawer-source-card h3 {
  margin: 2px 0 0;
  color: var(--app-ink);
  font-size: 15px;
  line-height: 1.4;
}

.drawer-source-card p {
  margin: 6px 0 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.source-citation {
  color: var(--app-ink-muted);
}

.source-link-button {
  width: fit-content;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 10px;
  border: 1px solid var(--app-primary);
  border-radius: var(--app-radius-sm);
  color: var(--app-primary-active);
  background: #fff;
  font-size: 13px;
  font-weight: 700;
  line-height: 1.4;
  text-decoration: none;
}

.source-link-button:hover,
.source-link-button:focus-visible {
  color: #fff;
  background: var(--app-primary);
  outline: none;
}
</style>
