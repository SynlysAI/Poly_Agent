<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import {
  getAlgorithmCreditSummary,
  getApiErrorMessage,
} from '../../api/polyAgentApi'
import AttributionBadges from '../attribution/AttributionBadges.vue'
import { formatApiDateTime } from '../../utils/datetime'

const props = defineProps({
  visible: { type: Boolean, default: false },
  algorithmId: { type: String, default: '' },
  refreshKey: { type: Number, default: 0 },
})

const emit = defineEmits(['update:visible'])

const loading = ref(false)
const summary = ref(null)

const drawerVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
})

const metrics = computed(() => summary.value?.metrics || {})
const attributions = computed(() => [summary.value?.developer_attribution].filter(Boolean))

const metricCards = computed(() => [
  { label: '算法版本', value: metrics.value.version_count || 0 },
  { label: '通过验证', value: metrics.value.validated_version_count || 0 },
  { label: '成功运行', value: metrics.value.success_run_count || 0 },
  { label: '调用用户', value: metrics.value.caller_count || 0 },
  { label: '复用上下文', value: metrics.value.reused_project_count || 0 },
  { label: '贡献者', value: metrics.value.contributor_count || 0 },
])

function roleLabel(role) {
  const map = {
    developer: '开发',
    reviewer: '审核',
    mentor: '指导',
    maintainer: '维护',
    data: '数据',
    method: '方法',
  }
  return map[role] || role || '-'
}

function roleTagType(role) {
  const map = {
    developer: 'success',
    reviewer: 'warning',
    mentor: 'primary',
    maintainer: 'info',
    data: 'info',
    method: 'primary',
  }
  return map[role] || 'info'
}

async function loadSummary() {
  if (!props.algorithmId || !props.visible) return
  loading.value = true
  try {
    summary.value = await getAlgorithmCreditSummary(props.algorithmId)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

watch(() => [props.visible, props.algorithmId, props.refreshKey], loadSummary)
</script>

<template>
  <el-drawer v-model="drawerVisible" title="贡献分析" size="min(720px, 94vw)">
    <div v-loading="loading" class="credit-drawer">
      <template v-if="summary">
        <header class="credit-header">
          <div>
            <h3>{{ summary.name }}</h3>
            <p>{{ summary.algorithm_id }} · {{ summary.visibility === 'public' ? '公开算法' : '私有算法' }}</p>
          </div>
          <el-tag :type="summary.status === 'active' ? 'success' : 'info'">{{ summary.status }}</el-tag>
        </header>

        <AttributionBadges v-if="attributions.length" :attributions="attributions" />

        <div class="metric-grid">
          <div v-for="item in metricCards" :key="item.label" class="metric-card">
            <span>{{ item.label }}</span>
            <strong>{{ item.value }}</strong>
          </div>
        </div>

        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="当前版本">{{ summary.active_version_id || '-' }}</el-descriptions-item>
          <el-descriptions-item label="导师课题组">{{ summary.mentor_team || '-' }}</el-descriptions-item>
          <el-descriptions-item label="最近维护">{{ formatApiDateTime(metrics.latest_maintained_at) }}</el-descriptions-item>
          <el-descriptions-item label="生成时间">{{ formatApiDateTime(summary.generated_at) }}</el-descriptions-item>
        </el-descriptions>

        <section class="credit-section">
          <div class="section-heading">
            <h4>贡献构成</h4>
            <div class="role-breakdown">
              <el-tag
                v-for="(count, role) in metrics.role_breakdown || {}"
                :key="role"
                size="small"
                effect="plain"
                :type="roleTagType(role)"
              >
                {{ roleLabel(role) }} {{ count }}
              </el-tag>
            </div>
          </div>
          <el-table :data="summary.contributors || []" border size="small" empty-text="暂无结构化贡献者">
            <el-table-column label="姓名" min-width="130"><template #default="{ row }">{{ row.name || '-' }}</template></el-table-column>
            <el-table-column label="角色" width="110"><template #default="{ row }"><el-tag size="small" :type="roleTagType(row.role)">{{ roleLabel(row.role) }}</el-tag></template></el-table-column>
            <el-table-column label="机构" min-width="150"><template #default="{ row }">{{ row.organization || '-' }}</template></el-table-column>
            <el-table-column label="导师关系" min-width="140"><template #default="{ row }">{{ row.mentor_relation || '-' }}</template></el-table-column>
            <el-table-column label="说明" min-width="180"><template #default="{ row }">{{ row.description || '-' }}</template></el-table-column>
          </el-table>
        </section>
      </template>
    </div>
  </el-drawer>
</template>

<style scoped>
.credit-drawer {
  min-height: 220px;
  display: grid;
  gap: 14px;
}

.credit-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.credit-header h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 18px;
  line-height: 1.35;
}

.credit-header p {
  margin: 4px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  overflow-wrap: anywhere;
}

.metric-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}

.metric-card {
  min-width: 0;
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  display: grid;
  gap: 4px;
}

.metric-card span {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.metric-card strong {
  color: var(--app-ink);
  font-size: 22px;
  line-height: 1.1;
}

.credit-section {
  display: grid;
  gap: 10px;
}

.section-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
}

.section-heading h4 {
  margin: 0;
  color: var(--app-ink);
  font-size: 15px;
}

.role-breakdown {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

@media (max-width: 640px) {
  .metric-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
