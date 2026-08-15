<script setup>
import { computed, ref } from 'vue'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  Cpu,
  MagicStick,
  MoreFilled,
  Search,
  Tools,
} from '@element-plus/icons-vue'

import {
  toolHealthClass,
  toolHealthLabel,
  toolRecentSuccessClass,
  toolRecentSuccessText,
  toolRequiresFile,
} from '../utils/assistantToolMenu.mjs'
import { categorizeTool, groupToolsByCategory } from '../utils/toolMenuCategories.mjs'

const props = defineProps({
  modelValue: {
    type: Array,
    default: () => [],
  },
  tools: {
    type: Array,
    default: () => [],
  },
  loading: {
    type: Boolean,
    default: false,
  },
  ariaLabel: {
    type: String,
    default: '选择工具',
  },
  popperClass: {
    type: String,
    default: 'tool-menu-popper',
  },
  placement: {
    type: String,
    default: 'top-start',
  },
  width: {
    type: [Number, String],
    default: 340,
  },
})

const emit = defineEmits(['update:modelValue'])

const activeCategoryKey = ref('')
const queryText = ref('')

const categoryIconMap = { Cpu, MagicStick, MoreFilled }

const categoryItems = computed(() => groupToolsByCategory(props.tools))

const activeCategory = computed(() =>
  categoryItems.value.find((item) => item.key === activeCategoryKey.value) || null,
)

const visibleTools = computed(() => {
  if (!activeCategoryKey.value) return []
  const items = (props.tools || []).filter(
    (tool) => categorizeTool(tool) === activeCategoryKey.value,
  )
  const query = queryText.value.trim().toLowerCase()
  if (!query) return items
  return items.filter((tool) =>
    [tool.name, tool.tool_id, tool.algorithm_id, tool.description, ...(tool.material_scope || [])]
      .filter(Boolean)
      .some((value) => String(value).toLowerCase().includes(query)),
  )
})

const hasSelected = computed(() => Boolean(props.modelValue.length))

function isToolSelected(toolId) {
  return props.modelValue.includes(toolId)
}

function toggleTool(toolId) {
  const next = isToolSelected(toolId)
    ? props.modelValue.filter((item) => item !== toolId)
    : [...props.modelValue, toolId]
  emit('update:modelValue', next)
}

function clearTools() {
  emit('update:modelValue', [])
}

function openCategory(key) {
  activeCategoryKey.value = key
  queryText.value = ''
}

function backToCategories() {
  activeCategoryKey.value = ''
  queryText.value = ''
}

function categoryIcon(name) {
  return categoryIconMap[name] || MoreFilled
}
</script>

<template>
  <el-popover
    :placement="placement"
    trigger="click"
    :width="width"
    :popper-class="popperClass"
    @after-leave="backToCategories"
  >
    <template #reference>
      <button
        type="button"
        class="icon-tool-btn tool-menu-trigger"
        :class="{ active: hasSelected }"
        :disabled="loading"
        :aria-label="ariaLabel"
      >
        <el-icon><Tools /></el-icon>
        <span v-if="hasSelected" class="tool-count">{{ modelValue.length }}</span>
      </button>
    </template>

    <div class="tool-menu">
      <div v-if="!activeCategory" class="tool-menu-categories">
        <button
          v-for="category in categoryItems"
          :key="category.key"
          type="button"
          class="tool-menu-category-btn"
          :disabled="category.count === 0"
          :aria-label="category.label"
          @click="openCategory(category.key)"
        >
          <span class="tool-menu-category-icon">
            <el-icon><component :is="categoryIcon(category.icon)" /></el-icon>
          </span>
          <span class="tool-menu-category-main">
            <strong>{{ category.label }}</strong>
            <small>{{ category.description }}</small>
          </span>
          <span class="tool-menu-category-meta">
            <em v-if="category.count">{{ category.count }}</em>
            <small v-else>{{ category.emptyText }}</small>
          </span>
          <el-icon class="tool-menu-category-arrow"><ArrowRight /></el-icon>
        </button>
      </div>

      <div v-else class="tool-menu-list">
        <div class="tool-menu-list-head">
          <button type="button" class="tool-menu-back" aria-label="返回工具分类" @click="backToCategories">
            <el-icon><ArrowLeft /></el-icon>
            <span>全部工具</span>
          </button>
          <strong>{{ activeCategory.label }}</strong>
        </div>
        <el-input
          v-model="queryText"
          size="small"
          clearable
          placeholder="搜索工具"
          :prefix-icon="Search"
        />
        <div class="tool-menu-items">
          <button
            v-for="tool in visibleTools"
            :key="tool.tool_id"
            type="button"
            class="tool-menu-item"
            :class="{ selected: isToolSelected(tool.tool_id) }"
            :aria-pressed="isToolSelected(tool.tool_id)"
            @click="toggleTool(tool.tool_id)"
          >
            <span class="tool-menu-item-check">
              <el-icon v-if="isToolSelected(tool.tool_id)"><Check /></el-icon>
            </span>
            <span class="tool-menu-item-main">
              <strong>{{ tool.name }}</strong>
              <small>{{ tool.description || tool.algorithm_id }}</small>
              <span class="tool-menu-item-flags">
                <span :class="`tool-flag ${toolHealthClass(tool.health_status)}`">
                  {{ toolHealthLabel(tool.health_status) }}
                </span>
                <span v-if="tool.requires_confirmation" class="tool-flag is-confirmation">需确认</span>
                <span v-if="toolRequiresFile(tool)" class="tool-flag is-file">需文件</span>
                <span v-if="tool.version" class="tool-flag is-version">v{{ tool.version }}</span>
                <span :class="`tool-flag ${toolRecentSuccessClass(tool)}`">
                  {{ toolRecentSuccessText(tool) }}
                </span>
              </span>
            </span>
          </button>
          <p v-if="!visibleTools.length" class="tool-menu-empty">{{ activeCategory.emptyText }}</p>
        </div>
        <button v-if="hasSelected" type="button" class="tool-menu-clear" @click="clearTools">
          清除全部
        </button>
      </div>
    </div>
  </el-popover>
</template>

<style scoped>
.icon-tool-btn {
  position: relative;
  width: 28px;
  height: 28px;
  min-width: 28px;
  display: inline-grid;
  place-items: center;
  padding: 0;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-muted);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.icon-tool-btn:hover:not(:disabled) {
  background: #eef4ff;
  color: var(--app-ink);
}

.icon-tool-btn.active {
  background: var(--app-primary-light);
  color: var(--app-primary-active);
  box-shadow: inset 0 0 0 1px rgba(37, 99, 235, 0.2);
}

.icon-tool-btn.active:hover:not(:disabled) {
  background: #dbeafe;
  color: var(--app-primary);
}

.icon-tool-btn:disabled {
  cursor: not-allowed;
  opacity: 0.45;
}

.tool-count {
  position: absolute;
  top: -5px;
  right: -5px;
  min-width: 15px;
  height: 15px;
  padding: 0 3px;
  border: 2px solid #fff;
  border-radius: 999px;
  background: var(--app-primary);
  color: #fff;
  font-size: 9px;
  line-height: 11px;
  box-sizing: border-box;
}

.tool-menu {
  display: grid;
  gap: 4px;
}

.tool-menu-categories {
  display: grid;
  gap: 4px;
}

.tool-menu-category-btn {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto 14px;
  align-items: center;
  gap: 8px;
  padding: 9px 8px;
  border: 1px solid transparent;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  cursor: pointer;
}

.tool-menu-category-btn:hover:not(:disabled) {
  background: #f0f7ff;
  color: var(--app-primary-active);
}

.tool-menu-category-btn:disabled {
  cursor: not-allowed;
  opacity: 0.62;
}

.tool-menu-category-icon,
.tool-menu-category-arrow {
  color: var(--app-primary-active);
  font-size: 16px;
}

.tool-menu-category-arrow {
  font-size: 12px;
  color: var(--app-ink-subtle);
}

.tool-menu-category-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.tool-menu-category-main strong {
  font-size: 13px;
  color: var(--app-ink);
}

.tool-menu-category-main small,
.tool-menu-category-meta small {
  overflow: hidden;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-menu-category-meta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--app-ink-muted);
}

.tool-menu-category-meta em {
  min-width: 18px;
  height: 18px;
  display: inline-grid;
  place-items: center;
  padding: 0 4px;
  border-radius: var(--app-radius-pill);
  background: var(--app-primary-light);
  color: var(--app-primary-active);
  font-style: normal;
  font-size: 11px;
}

.tool-menu-list {
  display: grid;
  gap: 6px;
}

.tool-menu-list-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-height: 26px;
}

.tool-menu-list-head strong {
  font-size: 13px;
  color: var(--app-ink);
}

.tool-menu-back {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 5px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-primary-active);
  font-size: 12px;
  cursor: pointer;
}

.tool-menu-back:hover {
  background: #f0f7ff;
}

.tool-menu-back .el-icon {
  font-size: 13px;
}

.tool-menu-items {
  display: grid;
  gap: 4px;
  max-height: 280px;
  overflow-y: auto;
}

.tool-menu-item {
  width: 100%;
  min-width: 0;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
  padding: 8px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  cursor: pointer;
}

.tool-menu-item:hover,
.tool-menu-item.selected {
  background: #f0f7ff;
  color: var(--app-primary-active);
}

.tool-menu-item-check {
  width: 16px;
  height: 16px;
  display: inline-grid;
  place-items: center;
  border: 1px solid var(--app-border);
  border-radius: 4px;
  color: #fff;
  font-size: 12px;
}

.tool-menu-item.selected .tool-menu-item-check {
  border-color: var(--app-primary-active);
  background: var(--app-primary-active);
}

.tool-menu-item-main {
  min-width: 0;
  display: grid;
  gap: 2px;
}

.tool-menu-item-main strong,
.tool-menu-item-main small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tool-menu-item-main strong {
  font-size: 13px;
}

.tool-menu-item-main small {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.tool-menu-item-flags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 2px;
}

.tool-flag {
  display: inline-flex;
  align-items: center;
  min-height: 18px;
  padding: 0 5px;
  border-radius: var(--app-radius-pill);
  background: #f1f5f9;
  color: var(--app-ink-muted);
  font-size: 11px;
  line-height: 18px;
  white-space: nowrap;
}

.tool-flag.is-healthy,
.tool-flag.is-success {
  background: #ecfdf5;
  color: #059669;
}

.tool-flag.is-unknown,
.tool-flag.is-muted {
  background: #f8fafc;
  color: #64748b;
}

.tool-flag.is-unavailable,
.tool-flag.is-danger {
  background: #fef2f2;
  color: #dc2626;
}

.tool-flag.is-warning {
  background: #fffbeb;
  color: #b45309;
}

.tool-flag.is-confirmation {
  background: #eef2ff;
  color: #4f46e5;
}

.tool-flag.is-file {
  background: #f0fdfa;
  color: #0f766e;
}

.tool-flag.is-version {
  background: #fdf4ff;
  color: #a21caf;
}

.tool-menu-empty {
  margin: 4px 0;
  color: var(--app-ink-muted);
  font-size: 12px;
  text-align: center;
}

.tool-menu-clear {
  justify-self: start;
  padding: 5px 7px;
  border: 0;
  border-radius: var(--app-radius-sm);
  background: transparent;
  color: var(--app-primary-active);
  cursor: pointer;
  font-size: 12px;
}

.tool-menu-clear:hover {
  background: #f0f7ff;
}
</style>
