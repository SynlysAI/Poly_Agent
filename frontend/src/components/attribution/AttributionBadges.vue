<script setup>
import { computed } from 'vue'

const props = defineProps({
  attributions: { type: Array, default: () => [] },
  limit: { type: Number, default: 2 },
})

const publicAttributions = computed(() => {
  return props.attributions.filter((item) => {
    return Boolean(publicText(item?.name) || publicText(item?.organization))
  })
})

function publicText(value) {
  const text = String(value || '').trim()
  const normalized = text.toLowerCase()
  const hiddenNames = new Set(['polyagent', 'poly agent', 'anonymous', 'demo_user', 'system', 'raman demo adapter', 'local raman reference'])
  if (!text || hiddenNames.has(normalized)) return ''
  if (/^u_[0-9a-z]{8,}$/i.test(text)) return ''
  return text
}

function label(item) {
  return publicText(item.organization) || publicText(item.name) || '来源'
}
</script>

<template>
  <div v-if="publicAttributions.length" class="attribution-badges">
    <el-tag
      v-for="item in publicAttributions.slice(0, limit)"
      :key="`${item.role}-${item.name}`"
      size="small"
      effect="plain"
      type="info"
    >
      {{ label(item) }}
    </el-tag>
    <el-tag v-if="publicAttributions.length > limit" size="small" effect="plain" type="info">
      +{{ publicAttributions.length - limit }}
    </el-tag>
  </div>
</template>

<style scoped>
.attribution-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
</style>
