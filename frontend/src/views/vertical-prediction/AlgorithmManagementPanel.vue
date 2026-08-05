<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Edit, Medal, Refresh, View as ViewIcon } from '@element-plus/icons-vue'

import {
  activateAlgorithmVersion,
  decommissionAlgorithmVersion,
  deleteAlgorithmVersion,
  deployAlgorithmVersion,
  freezeAlgorithmVersion,
  getAlgorithmVersionLogs,
  getApiErrorMessage,
  listAlgorithms,
  listAlgorithmVersions,
  redeployAlgorithmVersion,
  rollbackAlgorithmVersion,
} from '../../api/polyAgentApi'
import AlgorithmCreditDrawer from '../../components/algorithm/AlgorithmCreditDrawer.vue'
import AttributionBadges from '../../components/attribution/AttributionBadges.vue'
import { formatApiDateTime } from '../../utils/datetime'
import { authState } from '../../auth/authState'
import { algorithmSourceLabel, canEditRemoteInterfaceVersion, canManageUploadedAlgorithm, interfaceProtocolLabel, versionLifecycleLabel } from '../../utils/verticalPredictionState.mjs'

const props = defineProps({
  refreshKey: { type: Number, default: 0 },
  algorithmId: { type: String, default: '' },
  showSelector: { type: Boolean, default: true },
})
const emit = defineEmits(['changed', 'edit-interface-config'])

const loading = ref(false)
const actionVersionId = ref('')
const algorithms = ref([])
const selectedAlgorithmId = ref('')
const versions = ref([])
const logsVisible = ref(false)
const creditVisible = ref(false)
const versionLogs = ref(null)

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === selectedAlgorithmId.value) || null)
const canManage = computed(() => canManageUploadedAlgorithm(selectedAlgorithm.value, authState))

watch(() => props.refreshKey, loadAlgorithms)
watch(() => props.algorithmId, loadAlgorithms)
watch(selectedAlgorithmId, loadVersions)

async function loadAlgorithms() {
  loading.value = true
  try {
    const data = await listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 })
    algorithms.value = (data.items || []).filter((item) => ['uploaded_package', 'remote_interface'].includes(item.source))
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
    const result = await action(version.algorithm_id, version.version_id)
    await loadAlgorithms()
    emit('changed', {
      ...(result || {}),
      algorithm_id: version.algorithm_id,
      version_id: version.version_id,
      deleted: action === deleteAlgorithmVersion || result?.deleted === true,
    })
    ElMessage.success(action === deleteAlgorithmVersion ? '版本已删除' : '版本状态已更新')
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

function openCredit() {
  if (!selectedAlgorithmId.value) return
  creditVisible.value = true
}

function openInterfaceConfig(version) {
  emit('edit-interface-config', version)
}

function statusType(status) {
  const map = { active: 'success', deployed_staging: 'warning', built: 'info', validated: 'info', frozen: 'info', decommissioned: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  return versionLifecycleLabel(typeof status === 'string' ? { status } : status)
}

function runtimeBackend(row) {
  if (selectedAlgorithm.value?.source === 'remote_interface') return `${interfaceProtocolLabel(row.interface_config?.protocol || selectedAlgorithm.value.interface_config?.protocol)} remote`
  return row.deployment?.backend || row.deployment?.kind || '未部署'
}

function runtimeHealth(row) {
  if (selectedAlgorithm.value?.source === 'remote_interface') return row.status === 'active' ? 'ready' : (row.status || '-')
  return row.deployment?.health || (row.status === 'built' ? 'built' : '-')
}

function formatDate(value) {
  return formatApiDateTime(value)
}

function visibilityLabel(value) {
  return value === 'public' ? '公开发布' : '非公开'
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
        <el-select id="algorithm-select" v-model="selectedAlgorithmId" filterable placeholder="选择垂类模型" style="width: 320px">
          <el-option v-for="item in algorithms" :key="item.algorithm_id" :label="`${item.name} · ${item.algorithm_id}`" :value="item.algorithm_id" />
        </el-select>
      </div>
      <div v-else>
        <label>当前算法</label>
        <strong class="selected-algorithm-title">{{ selectedAlgorithm?.name || selectedAlgorithmId || '未选择' }}</strong>
      </div>
      <div class="management-actions">
        <el-button :icon="Medal" :disabled="!selectedAlgorithmId" @click="openCredit">贡献分析</el-button>
        <el-button :icon="Refresh" :loading="loading" @click="loadAlgorithms">刷新</el-button>
      </div>
    </div>

    <el-alert v-if="selectedAlgorithm" :closable="false" type="info" show-icon>
      <template #title>
        当前 active：{{ selectedAlgorithm.active_version_id || '无' }} · 注册表状态：{{ statusLabel(selectedAlgorithm.status) }}
      </template>
    </el-alert>
    <el-alert v-if="selectedAlgorithm && !canManage" :closable="false" type="warning" show-icon title="当前账号仅可访问和调用该模型，不能修改版本或发布状态。" />
    <AttributionBadges v-if="selectedAlgorithm" :attributions="rowAttributions(selectedAlgorithm)" />

    <el-alert v-if="selectedAlgorithm?.source === 'remote_interface'" :closable="false" type="info" show-icon>
      <template #title>来源：{{ algorithmSourceLabel(selectedAlgorithm.source) }} · 接口版本需先完成样例连通性测试，再激活。</template>
    </el-alert>

    <el-table v-loading="loading" :data="versions" border empty-text="暂无可治理版本">
      <el-table-column prop="version" label="Version" width="100" />
      <el-table-column prop="status" label="状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row) }}</el-tag></template></el-table-column>
      <el-table-column label="Runtime" min-width="165"><template #default="{ row }"><code>{{ runtimeBackend(row) }}</code></template></el-table-column>
      <el-table-column label="Health" width="105"><template #default="{ row }"><el-tag size="small" :type="runtimeHealth(row) === 'ready' ? 'success' : 'info'">{{ runtimeHealth(row) }}</el-tag></template></el-table-column>
      <el-table-column label="追溯" width="88">
        <template #default="{ row }">
          <el-popover trigger="click" placement="bottom" width="320">
            <template #reference>
              <el-button text :icon="ViewIcon">追溯</el-button>
            </template>
            <div class="trace-popover">
              <div>
                <span>运行后端</span>
                <code>{{ runtimeBackend(row) }}</code>
              </div>
              <div>
                <span>健康状态</span>
                <code>{{ runtimeHealth(row) }}</code>
              </div>
              <div>
                <span>入口函数</span>
                <code>{{ row.entrypoint || '-' }}</code>
              </div>
              <div>
                <span>可见性</span>
                <code>{{ visibilityLabel(row.visibility) }}</code>
              </div>
              <div>
                <span>受管资源</span>
                <code>{{ row.resource_assets?.length || 0 }} 项</code>
              </div>
            </div>
          </el-popover>
        </template>
      </el-table-column>
      <el-table-column label="来源" min-width="170"><template #default="{ row }"><AttributionBadges :attributions="rowAttributions(row)" /></template></el-table-column>
      <el-table-column label="创建人" width="110">
        <template #default="{ row }">
          {{ (selectedAlgorithm?.developer || selectedAlgorithm?.owner || row.uploaded_by || row.created_by) }}
        </template>
      </el-table-column>
      <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" min-width="290" fixed="right">
        <template #default="{ row }">
          <template v-if="canManage">
            <el-button
              v-if="selectedAlgorithm?.source === 'remote_interface' && canEditRemoteInterfaceVersion(row)"
              size="small"
              :icon="Edit"
              @click="openInterfaceConfig(row)"
            >编辑配置</el-button>
            <el-button v-if="selectedAlgorithm?.source !== 'remote_interface' && row.status === 'built'" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, deployAlgorithmVersion)">部署</el-button>
            <el-button v-if="selectedAlgorithm?.source !== 'remote_interface' && ['active','deployed_staging'].includes(row.status)" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, redeployAlgorithmVersion)">重部署</el-button>
            <el-button v-if="row.status === 'deployed_staging'" type="primary" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, activateAlgorithmVersion)">激活</el-button>
            <el-button v-if="row.status !== 'active' && selectedAlgorithm?.active_version_id !== row.version_id" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, rollbackAlgorithmVersion, `确认回滚到 ${row.version}？`)">回滚</el-button>
            <el-button v-if="['active','deployed_staging'].includes(row.status)" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, freezeAlgorithmVersion, `冻结版本 ${row.version} 后，新任务将不能选择它。`)">冻结</el-button>
            <el-button v-if="row.status !== 'decommissioned'" type="danger" plain size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, decommissionAlgorithmVersion, `下线版本 ${row.version}？历史记录仍会保留。`)">下线</el-button>
            <el-button v-else type="danger" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, deleteAlgorithmVersion, `确认删除已下线版本 ${row.version}？上传包和版本记录会删除，历史运行记录仍会保留。`)">删除</el-button>
          </template>
          <el-button size="small" :loading="actionVersionId === row.version_id" @click="openLogs(row)">日志</el-button>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="!loading && !algorithms.length" class="empty-state">
      <strong>还没有可治理的垂类模型</strong>
      <span>先完成算法上传或接口配置。</span>
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
    <AlgorithmCreditDrawer v-model:visible="creditVisible" :algorithm-id="selectedAlgorithmId" :refresh-key="refreshKey" />
  </div>
</template>

<style scoped>
.management-panel { display: grid; gap: 16px; }
.management-toolbar { display: flex; justify-content: space-between; align-items: end; gap: 12px; user-select: none; }
.management-toolbar > div { display: grid; gap: 6px; }
.management-toolbar .management-actions { display: flex; flex-direction: row; align-items: center; gap: 8px; }
.management-toolbar label { color: var(--app-ink-muted); font-size: 12px; }
.selected-algorithm-title { color: var(--app-ink); font-size: 15px; overflow-wrap: anywhere; }
code { font-family: var(--app-mono-font); font-size: 12px; }
.log-block { margin: 0; white-space: pre-wrap; word-break: break-word; font-family: var(--app-mono-font); font-size: 12px; }
.trace-popover { display: grid; gap: 10px; }
.trace-popover div { display: grid; gap: 4px; }
.trace-popover span { color: var(--app-ink-muted); font-size: 12px; }
.trace-popover code { white-space: pre-wrap; word-break: break-all; }
.empty-state { display: grid; gap: 4px; padding: 32px; text-align: center; color: var(--app-ink-muted); }
.empty-state strong { color: var(--app-ink); }
@media (max-width: 720px) { .management-toolbar { align-items: stretch; flex-direction: column; } .management-toolbar :deep(.el-select) { width: 100% !important; } }
</style>
