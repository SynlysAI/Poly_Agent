<script setup>
import { computed } from 'vue'

import { formatContextWindow, toolProtocolLabel } from '../utils/assistantUi.mjs'

const props = defineProps({
  modelValue: { type: String, default: '' },
  models: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '选择模型' },
})

const emit = defineEmits(['update:modelValue', 'change'])

const value = computed({
  get: () => props.modelValue,
  set: (next) => {
    emit('update:modelValue', next)
    emit('change', next)
  },
})

function capabilityLabels(item) {
  const capabilities = item?.capabilities || []
  const labels = []
  if (capabilities.includes('fast')) labels.push('快速')
  if (capabilities.includes('reasoning')) labels.push('推理')
  if (capabilities.includes('long_context')) labels.push('长上下文')
  if (capabilities.includes('structured_json')) labels.push('JSON')
  if (capabilities.includes('tool_calling')) labels.push('工具调用')
  if (capabilities.includes('local')) labels.push('本地')
  return labels.length ? labels.slice(0, 4) : ['模型']
}

function providerLabel(item) {
  const providerName = item?.providerName || ''
  const capabilitySource = item?.capabilitySource
  if (!providerName) return ''
  return capabilitySource === 'inferred' ? `${providerName} · 能力推断` : providerName
}

function modelDetailSuffix(item) {
  return [
    formatContextWindow(item?.contextWindow),
    toolProtocolLabel(item?.toolProtocol),
  ].filter(Boolean).join(' · ')
}

function selectedLabel(item) {
  if (!item) return props.placeholder
  return item.label
}
</script>

<template>
  <el-select
    v-model="value"
    class="llm-model-select"
    popper-class="llm-model-select-popper"
    :loading="loading"
    :disabled="disabled || loading || !models.length"
    :placeholder="loading ? '加载模型...' : models.length ? placeholder : '未配置模型'"
    aria-label="选择 LLM 模型"
  >
    <el-option
      v-for="item in models"
      :key="item.key"
      :label="selectedLabel(item)"
      :value="item.key"
    >
      <div class="llm-model-option">
        <div class="llm-model-option-main">
          <div class="llm-model-option-title">
            <strong>{{ item.label }}</strong>
          </div>
          <div v-if="providerLabel(item)" class="llm-model-option-provider">
            {{ providerLabel(item) }}
          </div>
          <div v-if="modelDetailSuffix(item)" class="llm-model-option-detail">
            {{ modelDetailSuffix(item) }}
          </div>
        </div>
        <div class="llm-model-option-tags">
          <span
            v-for="tag in capabilityLabels(item)"
            :key="`${item.key}-${tag}`"
            :class="{ primary: tag === '推理', fast: tag === '快速', tools: tag === '工具调用' }"
          >
            {{ tag }}
          </span>
        </div>
      </div>
    </el-option>
  </el-select>
</template>

<style scoped>
.llm-model-select {
  width: clamp(220px, 24vw, 280px);
}

.llm-model-select :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 8px;
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--app-border-soft) inset;
  transition: box-shadow 0.18s ease, background 0.18s ease;
}

.llm-model-select :deep(.el-select__wrapper:hover),
.llm-model-select :deep(.el-select__wrapper.is-focused) {
  background: #f8fbff;
  box-shadow: 0 0 0 1px #bfdbfe inset, 0 6px 16px rgba(37, 99, 235, 0.08);
}

.llm-model-select :deep(.el-select__placeholder),
.llm-model-select :deep(.el-select__selected-item) {
  min-width: 0;
  color: var(--app-ink);
  font-size: 12px;
  font-weight: 650;
}

.llm-model-select :deep(.el-select__selected-item span) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

:global(.llm-model-select-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 46px;
  padding: 8px 10px;
}

:global(.llm-model-select-popper .el-select-dropdown__item.is-selected) {
  color: var(--app-primary-active);
  font-weight: 600;
}

.llm-model-option {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
}

.llm-model-option-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.llm-model-option-title strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.llm-model-option-provider {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-ink-muted);
  font-size: 11px;
  line-height: 1.4;
}

.llm-model-option-detail {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--app-ink-subtle);
  font-size: 11px;
  line-height: 1.4;
}

.llm-model-option-title strong {
  color: var(--app-ink);
  font-size: 13px;
}

.llm-model-option-tags {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 5px;
}

.llm-model-option-tags span {
  flex: 0 0 auto;
  border: 1px solid var(--app-border-soft);
  border-radius: 999px;
  padding: 2px 7px;
  color: var(--app-ink-muted);
  background: #ffffff;
  font-size: 11px;
  line-height: 1.4;
}

.llm-model-option-tags span.primary {
  border-color: #bbf7d0;
  color: #15803d;
  background: #f0fdf4;
}

.llm-model-option-tags span.fast {
  border-color: #bfdbfe;
  color: #1d4ed8;
  background: #eff6ff;
}

.llm-model-option-tags span.tools {
  border-color: #ddd6fe;
  color: #6d28d9;
  background: #f5f3ff;
}

@media (max-width: 640px) {
  .llm-model-select {
    width: 100%;
  }
}
</style>
