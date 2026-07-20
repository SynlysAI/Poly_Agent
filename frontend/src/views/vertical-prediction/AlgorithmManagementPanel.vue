<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import {
  activateAlgorithmVersion,
  decommissionAlgorithmVersion,
  deployAlgorithmVersion,
  freezeAlgorithmVersion,
  getAlgorithmVersionLogs,
  getApiErrorMessage,
  listAlgorithms,
  listAlgorithmVersions,
  redeployAlgorithmVersion,
  rollbackAlgorithmVersion,
} from '../../api/polyAgentApi'
import AttributionBadges from '../../components/attribution/AttributionBadges.vue'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
  algorithmId: { type: String, default: '' },
  showSelector: { type: Boolean, default: true },
})
const emit = defineEmits(['changed'])

const loading = ref(false)
const actionVersionId = ref('')
const algorithms = ref([])
const selectedAlgorithmId = ref('')
const versions = ref([])
const logsVisible = ref(false)
const versionLogs = ref(null)

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === selectedAlgorithmId.value) || null)

watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(selectedAlgorithmId, loadVersions)

async function loadAlgorithms() {
  loading.value = true
  try {
    const data = await listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 })
    algorithms.value = (data.items || []).filter((item) => item.source === 'uploaded_package')
    const preferredId = props.algorithmId || selectedAlgorithmId.value
    if (!algorithms.value.some((item) => item.algorithm_id === preferredId)) {
      selectedAlgorithmId.value = algorithms.value[0]?.algorithm_id || ''
    } else if (selectedAlgorithmId.value !== preferredId) {
      selectedAlgorithmId.value = preferredId
    } else {
      await loadVersions()
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadVersions() {
  if (!selectedAlgorithmId.value) {
    versions.value = []
    return
  }
  loading.value = true
  try {
    const data = await listAlgorithmVersions(selectedAlgorithmId.value, { page: 1, page_size: 100 })
    versions.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function runAction(version, action, confirmText = '') {
  try {
    if (confirmText) await ElMessageBox.confirm(confirmText, '版本治理确认', { type: 'warning' })
    actionVersionId.value = version.version_id
    await action(version.algorithm_id, version.version_id)
    await loadAlgorithms()
    emit('changed')
    ElMessage.success('版本状态已更新')
  } catch (error) {
    if (error !== 'cancel' && error !== 'close') ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionVersionId.value = ''
  }
}

async function openLogs(version) {
  try {
    actionVersionId.value = version.version_id
    versionLogs.value = await getAlgorithmVersionLogs(version.algorithm_id, version.version_id)
    logsVisible.value = true
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionVersionId.value = ''
  }
}

function statusType(status) {
  const map = { active: 'success', deployed_staging: 'warning', built: 'info', validated: 'info', frozen: 'info', decommissioned: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { active: '已激活', deployed_staging: '待激活', built: '已构建', validated: '已校验', frozen: '已冻结', decommissioned: '已下线' }
  return map[status] || status
}

function shortDigest(value) {
  if (!value) return '-'
  return value.length > 22 ? `${value.slice(0, 18)}...` : value
}

function runtimeBackend(row) {
  return row.deployment?.backend || row.deployment?.kind || '未部署'
}

function runtimeHealth(row) {
  return row.deployment?.health || (row.status === 'built' ? 'built' : '-')
}

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

function rowAttributions(row) {
  return [
    row?.developer_attribution || selectedAlgorithm.value?.developer_attribution,
    ...(row?.method_attributions || selectedAlgorithm.value?.method_attributions || []),
  ].filter(Boolean)
}

onMounted(loadAlgorithms)
</script>

<template>
  <div class="management-panel">
    <div class="management-toolbar">
      <div v-if="showSelector">
        <label for="algorithm-select">算法资产</label>
        <el-select id="algorithm-select" v-model="selectedAlgorithmId" filterable placeholder="选择已上传算法" style="width: 320px">
          <el-option v-for="item in algorithms" :key="item.algorithm_id" :label="`${item.name} · ${item.algorithm_id}`" :value="item.algorithm_id" />
        </el-select>
      </div>
      <div v-else>
        <label>当前算法</label>
        <strong class="selected-algorithm-title">{{ selectedAlgorithm?.name || selectedAlgorithmId || '未选择' }}</strong>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAlgorithms">刷新</el-button>
    </div>

    <el-alert v-if="selectedAlgorithm" :closable="false" type="info" show-icon>
      <template #title>
        当前 active：{{ selectedAlgorithm.active_version_id || '无' }} · 注册表状态：{{ statusLabel(selectedAlgorithm.status) }}
      </template>
    </el-alert>
    <AttributionBadges v-if="selectedAlgorithm" :attributions="rowAttributions(selectedAlgorithm)" />

    <el-table v-loading="loading" :data="versions" border empty-text="暂无上传版本">
      <el-table-column prop="version" label="Version" width="100" />
      <el-table-column prop="status" label="状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="Runtime" min-width="165"><template #default="{ row }"><code>{{ runtimeBackend(row) }}</code></template></el-table-column>
      <el-table-column label="Health" width="105"><template #default="{ row }"><el-tag size="small" :type="runtimeHealth(row) === 'ready' ? 'success' : 'info'">{{ runtimeHealth(row) }}</el-tag></template></el-table-column>
      <el-table-column label="Package SHA256" min-width="170"><template #default="{ row }"><el-tooltip :content="row.package_sha256"><code>{{ shortDigest(row.package_sha256) }}</code></el-tooltip></template></el-table-column>
      <el-table-column label="Runtime Digest" min-width="170"><template #default="{ row }"><el-tooltip :content="row.runtime_digest || row.image_digest || '-'"><code>{{ shortDigest(row.runtime_digest || row.image_digest) }}</code></el-tooltip></template></el-table-column>
      <el-table-column label="来源" min-width="170"><template #default="{ row }"><AttributionBadges :attributions="rowAttributions(row)" /></template></el-table-column>
      <el-table-column label="Environment Digest" min-width="180"><template #default="{ row }"><el-tooltip :content="row.environment_digest || '-'"><code>{{ shortDigest(row.environment_digest) }}</code></el-tooltip></template></el-table-column>
      <el-table-column prop="created_by" label="创建人" width="110" />
      <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" min-width="290" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'built'" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, deployAlgorithmVersion)">部署</el-button>
          <el-button v-if="['active','deployed_staging'].includes(row.status)" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, redeployAlgorithmVersion)">重部署</el-button>
          <el-button size="small" :loading="actionVersionId === row.version_id" @click="openLogs(row)">日志</el-button>
          <el-button v-if="row.status === 'deployed_staging'" type="primary" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, activateAlgorithmVersion)">激活</el-button>
          <el-button v-if="row.status === 'deployed_staging' && selectedAlgorithm?.active_version_id !== row.version_id" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, rollbackAlgorithmVersion, `确认回滚到 ${row.version}？`)">回滚</el-button>
          <el-button v-if="['active','deployed_staging'].includes(row.status)" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, freezeAlgorithmVersion, `冻结版本 ${row.version} 后，新任务将不能选择它。`)">冻结</el-button>
          <el-button v-if="row.status !== 'decommissioned'" type="danger" plain size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, decommissionAlgorithmVersion, `下线版本 ${row.version}？历史记录仍会保留。`)">下线</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="!loading && !algorithms.length" class="empty-state">
      <strong>还没有已上传的垂类预测算法</strong>
      <span>先到“上传部署”完成脚本或标准 ZIP 上传。</span>
    </div>

    <el-drawer v-model="logsVisible" title="版本运行日志" size="min(720px, 94vw)">
      <template v-if="versionLogs">
        <el-descriptions :column="1" border size="small">
          <el-descriptions-item label="版本">{{ versionLogs.algorithm_id }} / {{ versionLogs.version_id }}</el-descriptions-item>
          <el-descriptions-item label="Deployment"><pre class="log-block">{{ JSON.stringify(versionLogs.deployment || {}, null, 2) }}</pre></el-descriptions-item>
          <el-descriptions-item label="校验日志"><pre class="log-block">{{ (versionLogs.validation_logs || []).join('\n') || '-' }}</pre></el-descriptions-item>
          <el-descriptions-item label="构建日志"><pre class="log-block">{{ (versionLogs.build_logs || []).join('\n') || '-' }}</pre></el-descriptions-item>
          <el-descriptions-item label="部署日志"><pre class="log-block">{{ (versionLogs.deployment_logs || []).join('\n') || '-' }}</pre></el-descriptions-item>
          <el-descriptions-item label="Runtime logs"><pre class="log-block">{{ JSON.stringify(versionLogs.runtime_logs || [], null, 2) }}</pre></el-descriptions-item>
        </el-descriptions>
      </template>
    </el-drawer>
  </div>
</template>

<style scoped>
.management-panel { display: grid; gap: 16px; }
.management-toolbar { display: flex; justify-content: space-between; align-items: end; gap: 12px; }
.management-toolbar > div { display: grid; gap: 6px; }
.management-toolbar label { color: var(--app-ink-muted); font-size: 12px; }
.selected-algorithm-title { color: var(--app-ink); font-size: 15px; overflow-wrap: anywhere; }
code { font-family: var(--app-mono-font); font-size: 12px; }
.log-block { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--app-mono-font); font-size: 12px; }
.empty-state { display: grid; gap: 4px; padding: 32px; text-align: center; color: var(--app-ink-muted); }
.empty-state strong { color: var(--app-ink); }
@media (max-width: 720px) { .management-toolbar { align-items: stretch; flex-direction: column; } .management-toolbar :deep(.el-select) { width: 100% !important; } }
</style>
