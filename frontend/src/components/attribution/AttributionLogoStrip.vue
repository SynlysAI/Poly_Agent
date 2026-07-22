<script setup>
const props = defineProps({
  items: { type: Array, default: () => [] },
  limit: { type: Number, default: 3 },
})

const emit = defineEmits(['select', 'open-more'])

function displayText(item) {
  return item.organization || item.name || '来源'
}

function displayLines(item) {
  return displayText(item)
    .split(/\s+\/\s+/)
    .map((part) => part.trim())
    .filter(Boolean)
}

function visibleItems() {
  return props.items.slice(0, props.limit)
}

function hiddenCount() {
  return Math.max(0, props.items.length - props.limit)
}
</script>

<template>
  <div class="attribution-logo-strip" aria-label="来源机构">
    <button
      v-for="item in visibleItems()"
      :key="`${item.role}-${item.name}-${item.organization || ''}`"
      type="button"
      class="attribution-logo-card"
      :title="item.description || displayText(item)"
      :aria-label="`查看来源：${displayText(item)}`"
      @click="emit('select', item)"
    >
      <img v-if="item.logo_asset" :src="item.logo_asset" :alt="item.logo_alt || displayText(item)" />
      <span v-else class="logo-text-mark">
        <span v-for="line in displayLines(item)" :key="line">{{ line }}</span>
      </span>
      <strong v-if="item.logo_asset">
        <span v-for="line in displayLines(item)" :key="line">{{ line }}</span>
      </strong>
    </button>
    <button
      v-if="hiddenCount()"
      type="button"
      class="attribution-more"
      :aria-label="`查看还有 ${hiddenCount()} 个来源`"
      @click="emit('open-more')"
    >
      +{{ hiddenCount() }}
    </button>
  </div>
</template>

<style scoped>
.attribution-logo-strip {
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 10px;
  flex-wrap: wrap;
}

.attribution-logo-card {
  min-width: 150px;
  max-width: 260px;
  height: auto;
  min-height: 58px;
  padding: 8px 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #fff;
  color: var(--app-ink);
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  font: inherit;
  cursor: pointer;
  transition: border-color 0.16s ease, box-shadow 0.16s ease, transform 0.16s ease;
}

.attribution-logo-card:hover,
.attribution-logo-card:focus-visible {
  border-color: var(--app-primary);
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.12);
}

.attribution-logo-card:active {
  transform: translateY(1px);
}

.attribution-logo-card img {
  max-width: 112px;
  max-height: 38px;
  object-fit: contain;
}

.logo-text-mark {
  max-width: 100%;
  color: var(--app-ink);
  font-size: 15px;
  font-weight: 800;
  line-height: 1.35;
  overflow-wrap: anywhere;
  white-space: normal;
  text-align: center;
}

.logo-text-mark span,
.attribution-logo-card strong span {
  display: block;
}

.attribution-logo-card strong {
  min-width: 0;
  color: var(--app-ink);
  font-size: 14px;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.attribution-more {
  border: 0;
  background: transparent;
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 700;
  line-height: 1;
  padding: 8px 4px;
  cursor: pointer;
  border-radius: var(--app-radius-sm);
}

.attribution-more:hover,
.attribution-more:focus-visible {
  color: var(--app-primary-active);
  outline: 2px solid rgba(59, 130, 246, 0.24);
  outline-offset: 2px;
}

@media (max-width: 760px) {
  .attribution-logo-strip {
    justify-content: flex-start;
  }

  .attribution-logo-card {
    min-width: 0;
    width: 100%;
    max-width: 100%;
  }
}
</style>
