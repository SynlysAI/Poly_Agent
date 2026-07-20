<script setup>
import { computed } from 'vue'

const props = defineProps({
  attributions: { type: Array, default: () => [] },
  limit: { type: Number, default: 2 },
})

const publicAttributions = computed(() => {
  const internalNames = new Set(['polyagent', 'poly agent'])
  return props.attributions.filter((item) => {
    const name = String(item?.name || '').trim().toLowerCase()
    const organization = String(item?.organization || '').trim().toLowerCase()
    return !internalNames.has(name) && !internalNames.has(organization)
  })
})

function label(item) {
  return item.organization || item.name || '来源'
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
