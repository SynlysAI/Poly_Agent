<script setup>
import { computed } from 'vue'

defineOptions({ name: 'JsonTreeView' })

const props = defineProps({
  value: { type: null, default: null },
  depth: { type: Number, default: 0 },
})

const isObject = computed(() => Object.prototype.toString.call(props.value) === '[object Object]')
const isArray = computed(() => Array.isArray(props.value))
const entries = computed(() => {
  if (isArray.value) return props.value.map((value, index) => [String(index), value])
  if (isObject.value) return Object.entries(props.value)
  return []
})

function isComplex(value) {
  return Array.isArray(value) || Object.prototype.toString.call(value) === '[object Object]'
}

function valueSummary(value) {
  if (Array.isArray(value)) return `Array(${value.length})`
  if (Object.prototype.toString.call(value) === '[object Object]') return `Object(${Object.keys(value).length})`
  if (value === null) return 'null'
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  if (value === undefined) return 'undefined'
  return String(value)
}
</script>

<template>
  <div v-if="isObject || isArray" class="json-tree" :class="{ 'is-root': depth === 0 }">
    <div v-if="!entries.length" class="json-empty">{{ isArray ? '[]' : '{}' }}</div>
    <div v-for="([key, item], index) in entries" :key="`${key}-${index}`" class="json-node">
      <details v-if="isComplex(item)" :open="depth < 1">
        <summary>
          <code>{{ isArray ? `[${key}]` : key }}</code>
          <span>{{ valueSummary(item) }}</span>
        </summary>
        <JsonTreeView :value="item" :depth="depth + 1" />
      </details>
      <div v-else class="json-leaf">
        <code>{{ isArray ? `[${key}]` : key }}</code>
        <span>{{ valueSummary(item) }}</span>
      </div>
    </div>
  </div>
  <span v-else class="json-scalar">{{ valueSummary(value) }}</span>
</template>

<style scoped>
.json-tree {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding-left: 14px;
  border-left: 1px solid var(--app-border-soft);
}
.json-tree.is-root {
  padding-left: 0;
  border-left: 0;
}
.json-node,
.json-node details {
  min-width: 0;
}
.json-node summary,
.json-leaf {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-height: 28px;
  padding: 4px 0;
}
.json-node summary {
  cursor: pointer;
}
.json-node code,
.json-leaf code {
  color: var(--app-primary-active);
  font-family: var(--app-mono-font);
  font-size: 12px;
  font-weight: 700;
  overflow-wrap: anywhere;
}
.json-node span,
.json-leaf span,
.json-scalar,
.json-empty {
  min-width: 0;
  color: var(--app-ink-body);
  font-family: var(--app-mono-font);
  font-size: 12px;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.json-empty {
  color: var(--app-ink-muted);
}
</style>
