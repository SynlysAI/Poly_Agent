<script setup>
import { computed } from 'vue'

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

const selectedModel = computed(() => props.models.find((item) => item.key === props.modelValue) || null)

function capabilityLabels(item) {
  const capabilities = item?.capabilities || []
  const labels = []
  if (capabilities.includes('fast')) labels.push('快速')
  if (capabilities.includes('reasoning')) labels.push('推理')
  if (capabilities.includes('long_context')) labels.push('长上下文')
  if (capabilities.includes('structured_json')) labels.push('JSON')
  if (capabilities.includes('local')) labels.push('本地')
  return labels.length ? labels.slice(0, 4) : ['模型']
}

function selectedLabel(item) {
  if (!item) return props.placeholder
  return item.label
}

function statusClass(status) {
  if (status === 'available') return 'is-available'
  if (status === 'down' || status === 'not_configured') return 'is-down'
  if (status === 'degraded') return 'is-degraded'
  return 'is-unknown'
}

function statusText(status) {
  const map = {
    available: '可用',
    degraded: '降级',
    down: '不可用',
    not_configured: '未配置',
    unknown: '未探测',
  }
  return map[status] || '未探测'
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
    <template #prefix>
      <span class="model-status-dot" :class="statusClass(selectedModel?.status)" aria-hidden="true" />
    </template>
    <el-option
      v-for="item in models"
      :key="item.key"
      :label="selectedLabel(item)"
      :value="item.key"
    >
      <div class="llm-model-option">
        <div class="llm-model-option-main">
          <div class="llm-model-option-title">
            <span class="model-status-dot" :class="statusClass(item.status)" aria-hidden="true" />
            <strong>{{ item.label }}</strong>
          </div>
          <span>{{ item.providerName }} · {{ statusText(item.status) }}</span>
        </div>
        <div class="llm-model-option-tags">
          <span
            v-for="tag in capabilityLabels(item)"
            :key="`${item.key}-${tag}`"
            :class="{ primary: tag === '推理', fast: tag === '快速' }"
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

.model-status-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: #94a3b8;
  box-shadow: 0 0 0 2px rgba(148, 163, 184, 0.15);
}

.model-status-dot.is-available {
  background: #16a34a;
  box-shadow: 0 0 0 2px rgba(22, 163, 74, 0.14);
}

.model-status-dot.is-degraded {
  background: #d97706;
  box-shadow: 0 0 0 2px rgba(217, 119, 6, 0.14);
}

.model-status-dot.is-down {
  background: #dc2626;
  box-shadow: 0 0 0 2px rgba(220, 38, 38, 0.14);
}

:global(.llm-model-select-popper .el-select-dropdown__item) {
  height: auto;
  min-height: 64px;
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

.llm-model-option-main {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.llm-model-option-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
}

.llm-model-option-title strong,
.llm-model-option-main span {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.llm-model-option-title strong {
  color: var(--app-ink);
  font-size: 13px;
}

.llm-model-option-main span {
  color: var(--app-ink-muted);
  font-size: 12px;
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

@media (max-width: 640px) {
  .llm-model-select {
    width: 100%;
  }
}
</style>
