<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { InfoFilled } from '@element-plus/icons-vue'

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
  <section v-if="resolvedAttributions.length || moduleId" class="attribution-banner" :class="{ compact, embedded }" v-loading="loading">
    <div class="attribution-copy">
      <div class="attribution-kicker">
        <el-icon><InfoFilled /></el-icon>
        <span>{{ resolvedLabel }}</span>
      </div>
      <h3 v-if="!embedded && !compact">{{ resolvedTitle }}</h3>
      <p>{{ errorText || resolvedSummary || '展示主要机构和方法来源。' }}</p>
    </div>
    <AttributionLogoStrip :items="prominentItems" />
  </section>
</template>

<style scoped>
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
</style>
