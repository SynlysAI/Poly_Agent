<script setup>
import { computed } from 'vue'

import AttributionBadges from '../attribution/AttributionBadges.vue'

const props = defineProps({
  visible: { type: Boolean, default: false },
  groups: { type: Array, default: () => [] },
  highlightedIndex: { type: Number, default: 0 },
  loading: { type: Boolean, default: false },
  error: { type: String, default: '' },
})

const emit = defineEmits(['select', 'highlight', 'close', 'retry'])

const flatItems = computed(() => props.groups.flatMap((group) => group.items || []))
const optionStartIndexes = computed(() => {
  let cursor = 0
  return props.groups.map((group) => {
    const start = cursor
    cursor += (group.items || []).length
    return start
  })
})

/**
 * 获取分组内选项在完整列表中的索引。
 *
 * Args:
 *   groupIndex: 分组索引。
 *   itemIndex: 分组内选项索引。
 *
 * Returns:
 *   面板全局高亮索引。
 */
function globalIndex(groupIndex, itemIndex) {
  return optionStartIndexes.value[groupIndex] + itemIndex
}

/**
 * 转换风险等级为展示文案。
 *
 * Args:
 *   riskLevel: 命令风险等级。
 *
 * Returns:
 *   中文风险标签；未知等级返回空字符串。
 */
function riskLabel(riskLevel) {
  const labels = { low: '低风险', medium: '中风险', high: '高风险' }
  return labels[riskLevel] || ''
}

/**
 * 生成公共 UI 的命令来源标签。
 *
 * Args:
 *   item: 面板命令选项。
 *
 * Returns:
 *   内置命令显示为“内置命令”；外部命令保留完整来源。
 */
function sourceLabel(item) {
  return item.sourceKind === 'builtin' ? '内置命令' : item.source
}
</script>

<template>
  <section
    v-if="visible"
    class="command-palette"
    role="listbox"
    aria-label="Slash Command 命令面板"
  >
    <div v-if="loading" class="command-palette-state">正在加载命令目录...</div>
    <div v-else-if="error" class="command-palette-state command-palette-error">
      <span>命令目录加载失败：{{ error }}</span>
      <button type="button" @click="emit('retry')">重试</button>
    </div>
    <div v-else-if="!flatItems.length" class="command-palette-state">没有匹配命令</div>
    <template v-else>
      <div
        v-for="(group, groupIndex) in groups"
        :key="group.category"
        class="command-palette-group"
      >
        <header>{{ group.categoryLabel }}</header>
        <button
          v-for="(item, itemIndex) in group.items"
          :key="item.key"
          type="button"
          role="option"
          :aria-selected="globalIndex(groupIndex, itemIndex) === highlightedIndex"
          :class="{
            highlighted: globalIndex(groupIndex, itemIndex) === highlightedIndex,
            unavailable: !item.available || !item.enabled,
          }"
          @mouseenter="emit('highlight', globalIndex(groupIndex, itemIndex))"
          @mousedown.prevent
          @click="emit('select', item)"
        >
          <span class="command-usage">
            <strong>{{ item.usage }}</strong>
            <small v-if="item.argumentHint">{{ item.argumentHint }}</small>
          </span>
          <span class="command-info">
            <span class="command-title">{{ item.title }}</span>
            <span class="command-description">{{ item.description }}</span>
            <span class="command-meta">
              <em>来源：{{ sourceLabel(item) || '未记录' }}</em>
              <em v-if="riskLabel(item.riskLevel)">{{ riskLabel(item.riskLevel) }}</em>
              <em v-if="!item.available || !item.enabled">
                {{ item.unavailableReason || '当前不可用' }}
              </em>
              <AttributionBadges
                v-if="item.sourceKind !== 'builtin'"
                :attributions="item.attributions || []"
                :limit="1"
              />
            </span>
          </span>
        </button>
      </div>
      <footer>
        <span>↑ ↓ 选择</span>
        <span>Enter 填入</span>
        <span>Esc 关闭</span>
      </footer>
    </template>
  </section>
</template>

<style scoped>
.command-palette {
  position: absolute;
  left: 12px;
  right: 12px;
  bottom: calc(100% + 6px);
  z-index: 30;
  max-height: min(360px, 46vh);
  overflow: auto;
  border: 1px solid #bfd8f8;
  border-radius: var(--app-radius-md);
  background: rgba(255, 255, 255, 0.99);
  box-shadow: 0 18px 42px rgba(22, 59, 110, 0.16);
}

.command-palette-state {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 12px 14px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.command-palette-error span {
  color: #b42318;
}

.command-palette-state button {
  border: 0;
  color: var(--app-primary-active);
  background: transparent;
  cursor: pointer;
  font: inherit;
}

.command-palette-group + .command-palette-group {
  border-top: 1px solid var(--app-border-soft);
}

.command-palette-group header {
  padding: 8px 14px 5px;
  color: var(--app-ink-muted);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
}

.command-palette-group button {
  width: 100%;
  display: grid;
  grid-template-columns: minmax(128px, 28%) minmax(0, 1fr);
  gap: 12px;
  align-items: start;
  padding: 9px 14px;
  border: 0;
  border-top: 1px solid rgba(188, 216, 248, 0.36);
  background: transparent;
  color: var(--app-ink-body);
  text-align: left;
  cursor: pointer;
}

.command-palette-group button:first-of-type {
  border-top: 0;
}

.command-palette-group button:hover,
.command-palette-group button.highlighted {
  background: rgba(35, 92, 178, 0.08);
}

.command-palette-group button.unavailable {
  color: var(--app-ink-muted);
  cursor: not-allowed;
}

.command-usage {
  display: grid;
  gap: 3px;
}

.command-usage strong {
  color: var(--app-primary-active);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}

.command-usage small,
.command-description,
.command-meta {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.command-info {
  min-width: 0;
  display: grid;
  gap: 3px;
}

.command-title {
  font-weight: 650;
}

.command-description {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.command-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 7px;
}

.command-palette footer {
  display: flex;
  gap: 12px;
  padding: 8px 14px;
  border-top: 1px solid var(--app-border-soft);
  background: rgba(244, 249, 255, 0.9);
  color: var(--app-ink-muted);
  font-size: 11px;
}

@media (max-width: 640px) {
  .command-palette-group button {
    grid-template-columns: 1fr;
  }
}
</style>
