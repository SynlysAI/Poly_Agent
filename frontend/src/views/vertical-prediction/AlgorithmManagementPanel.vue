<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import {
  activateAlgorithmVersion,
  decommissionAlgorithmVersion,
  deployAlgorithmVersion,
  freezeAlgorithmVersion,
  getApiErrorMessage,
  listAlgorithms,
  listAlgorithmVersions,
  rollbackAlgorithmVersion,
} from '../../api/polyAgentApi'

const props = defineProps({ refreshKey: { type: Number, default: 0 } })
const emit = defineEmits(['changed'])

const loading = ref(false)
const actionVersionId = ref('')
const algorithms = ref([])
const selectedAlgorithmId = ref('')
const versions = ref([])

const selectedAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === selectedAlgorithmId.value) || null)

watch(() => props.refreshKey, loadAlgorithms)
watch(selectedAlgorithmId, loadVersions)

async function loadAlgorithms() {
  loading.value = true
  try {
    const data = await listAlgorithms({ algorithm_family: 'vertical_prediction', page: 1, page_size: 100 })
    algorithms.value = (data.items || []).filter((item) => item.source === 'uploaded_package')
    if (!algorithms.value.some((item) => item.algorithm_id === selectedAlgorithmId.value)) {
      selectedAlgorithmId.value = algorithms.value[0]?.algorithm_id || ''
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

function formatDate(value) {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

onMounted(loadAlgorithms)
</script>

<template>
  <div class="management-panel">
    <div class="management-toolbar">
      <div>
        <label for="algorithm-select">算法资产</label>
        <el-select id="algorithm-select" v-model="selectedAlgorithmId" filterable placeholder="选择已上传算法" style="width: 320px">
          <el-option v-for="item in algorithms" :key="item.algorithm_id" :label="`${item.name} · ${item.algorithm_id}`" :value="item.algorithm_id" />
        </el-select>
      </div>
      <el-button :icon="Refresh" :loading="loading" @click="loadAlgorithms">刷新</el-button>
    </div>

    <el-alert v-if="selectedAlgorithm" :closable="false" type="info" show-icon>
      <template #title>
        当前 active：{{ selectedAlgorithm.active_version_id || '无' }} · 注册表状态：{{ statusLabel(selectedAlgorithm.status) }}
      </template>
    </el-alert>

    <el-table v-loading="loading" :data="versions" border empty-text="暂无上传版本">
      <el-table-column prop="version" label="Version" width="100" />
      <el-table-column prop="status" label="状态" width="105"><template #default="{ row }"><el-tag :type="statusType(row.status)">{{ statusLabel(row.status) }}</el-tag></template></el-table-column>
      <el-table-column label="Package SHA256" min-width="170"><template #default="{ row }"><el-tooltip :content="row.package_sha256"><code>{{ shortDigest(row.package_sha256) }}</code></el-tooltip></template></el-table-column>
      <el-table-column label="Image Digest" min-width="170"><template #default="{ row }"><el-tooltip :content="row.image_digest || '-' "><code>{{ shortDigest(row.image_digest) }}</code></el-tooltip></template></el-table-column>
      <el-table-column prop="created_by" label="创建人" width="110" />
      <el-table-column label="创建时间" width="170"><template #default="{ row }">{{ formatDate(row.created_at) }}</template></el-table-column>
      <el-table-column label="操作" min-width="290" fixed="right">
        <template #default="{ row }">
          <el-button v-if="row.status === 'built'" size="small" :loading="actionVersionId === row.version_id" @click="runAction(row, deployAlgorithmVersion)">部署</el-button>
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
  </div>
</template>

<style scoped>
.management-panel { display: grid; gap: 16px; }
.management-toolbar { display: flex; justify-content: space-between; align-items: end; gap: 12px; }
.management-toolbar > div { display: grid; gap: 6px; }
.management-toolbar label { color: var(--app-ink-muted); font-size: 12px; }
code { font-family: var(--app-mono-font); font-size: 12px; }
.empty-state { display: grid; gap: 4px; padding: 32px; text-align: center; color: var(--app-ink-muted); }
.empty-state strong { color: var(--app-ink); }
@media (max-width: 720px) { .management-toolbar { align-items: stretch; flex-direction: column; } .management-toolbar :deep(.el-select) { width: 100% !important; } }
</style>
