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

function providerLabel(item) {
  return item?.providerName || ''
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
        <div class="llm-model-option-title">
          <strong>{{ item.label }}</strong>
        </div>
        <div v-if="providerLabel(item)" class="llm-model-option-provider">
          {{ providerLabel(item) }}
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

.llm-model-option-title strong {
  color: var(--app-ink);
  font-size: 13px;
}

@media (max-width: 640px) {
  .llm-model-select {
    width: 100%;
  }
}
</style>
