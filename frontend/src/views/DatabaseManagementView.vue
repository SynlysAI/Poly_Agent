<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Cpu, DataAnalysis, Document, Monitor, Refresh, SetUp,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage,
  getIntegrationStatus,
  listAlgorithmPackages,
  listAuditEvents,
  listCampaigns,
  listComputations,
} from '../api/polyAgentApi'
import AlgorithmManagementPanel from './vertical-prediction/AlgorithmManagementPanel.vue'
import AlgorithmUploadPanel from './vertical-prediction/AlgorithmUploadPanel.vue'

const activeSection = ref('vertical-models')
const verticalModelTab = ref('governance')
const verticalRefreshKey = ref(0)
const loading = ref(false)
const sectionCache = ref({})

const activeData = computed(() => sectionCache.value[activeSection.value] || { items: [], total: 0 })

function sectionCount(key) {
  const entry = sectionCache.value[key]
  return entry ? entry.total : '-'
}

const sections = [
  { key: 'vertical-models', name: '垂类模型', icon: DataAnalysis },
  { key: 'audit-events', name: '审计事件', icon: Document },
  { key: 'computations', name: '计算任务', icon: Cpu },
  { key: 'campaigns', name: '优化任务', icon: SetUp },
  { key: 'services', name: '服务状态', icon: Monitor },
]

const sectionTitle = computed(() => sections.find((s) => s.key === activeSection.value)?.name || '')

// ── Column definitions per section ──

const auditEventColumns = [
  { prop: 'event_type', label: '事件类型', minWidth: 130 },
  { prop: 'actor_user_id', label: '操作人', minWidth: 150 },
  { prop: 'entity_type', label: '实体类型', minWidth: 120 },
  { prop: 'entity_id', label: '实体 ID', minWidth: 180 },
]

const computationColumns = [
  { prop: 'run_id', label: 'Run ID', minWidth: 190 },
  { prop: 'workflow_type', label: 'Workflow', minWidth: 140 },
  { prop: 'engine', label: 'Engine', minWidth: 90 },
  { prop: 'status', label: '状态', minWidth: 100 },
]

const campaignColumns = [
  { prop: 'campaign_id', label: 'Campaign ID', minWidth: 210 },
  { prop: 'name', label: '名称', minWidth: 200 },
  { prop: 'status', label: '状态', minWidth: 100 },
  { prop: 'planner_type', label: 'Planner', minWidth: 110 },
]

const serviceColumns = [
  { prop: 'service', label: 'Service', minWidth: 180 },
  { prop: 'status', label: '状态', minWidth: 110 },
]

const tableColumns = computed(() => {
  const map = {
    'audit-events': auditEventColumns,
    computations: computationColumns,
    campaigns: campaignColumns,
    services: serviceColumns,
  }
  return map[activeSection.value] || []
})

// ── Helpers ──

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusTag(status) {
  const map = { active: 'success', disabled: 'danger', used_up: 'info', expired: 'warning', up: 'success', available: 'success', completed: 'success', running: 'warning', failed: 'danger', queued: 'info', cancelled: 'info', draft: 'info', paused: 'info', archived: 'info', degraded: 'warning', not_configured: 'info', not_available: 'info', unknown: 'info', down: 'danger' }
  return map[status] || 'info'
}

function statusLabel(status) {
  const map = { active: '正常', disabled: '已禁用', used_up: '已用完', expired: '已过期', up: '可用', available: '可用', not_configured: '未配置', not_available: '未安装', degraded: '异常', down: '不可用', unknown: '未知' }
  return map[status] || status
}

function truncate(str, max) {
  if (!str) return '-'
  return String(str).length > max ? String(str).slice(0, max) + '…' : str
}

// ── Data loading ──

async function loadSectionData() {
  loading.value = true
  try {
    const key = activeSection.value
    switch (key) {
      case 'audit-events': {
        const res = await listAuditEvents({ page: 1, page_size: 50 })
        sectionCache.value = { ...sectionCache.value, [key]: { items: res.items || [], total: res.total || 0 } }
        break
      }
      case 'vertical-models': {
        const res = await listAlgorithmPackages({ page: 1, page_size: 1 })
        sectionCache.value = { ...sectionCache.value, [key]: { items: [], total: res.total || 0 } }
        break
      }
      case 'computations': {
        const res = await listComputations({ page: 1, page_size: 50 })
        sectionCache.value = { ...sectionCache.value, [key]: { items: res.items || [], total: res.total || 0 } }
        break
      }
      case 'campaigns': {
        const res = await listCampaigns({ page: 1, page_size: 50 })
        sectionCache.value = { ...sectionCache.value, [key]: { items: res.items || [], total: res.total || 0 } }
        break
      }
      case 'services': {
        const res = await getIntegrationStatus()
        sectionCache.value = { ...sectionCache.value, [key]: { items: res.items || [], total: res.items?.length || 0 } }
        break
      }
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

// ── Actions ──

function handleVerticalModelChanged() {
  verticalRefreshKey.value += 1
  loadSectionData()
}

watch(activeSection, () => {
  loadSectionData()
})

onMounted(() => {
  loadSectionData()
})
</script>

<template>
  <div style="display:flex;gap:16px;height:calc(100vh - 100px)">
    <!-- Left sidebar -->
    <div class="panel" style="width:220px;flex-shrink:0;display:flex;flex-direction:column">
      <div class="panel-header">
        <h3 class="panel-title">系统管理</h3>
      </div>
      <div class="panel-body" style="flex:1;overflow-y:auto;padding:8px">
        <div
          v-for="section in sections"
          :key="section.key"
          @click="activeSection = section.key"
          :style="{
            padding: '10px 12px',
            borderRadius: 'var(--app-radius-sm)',
            cursor: 'pointer',
            marginBottom: '4px',
            background: activeSection === section.key ? 'var(--app-primary-light)' : 'transparent',
            color: activeSection === section.key ? 'var(--app-primary)' : 'var(--app-ink-body)',
            fontWeight: activeSection === section.key ? '600' : '400',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }"
        >
          <el-icon><component :is="section.icon" /></el-icon>
          <div style="flex:1">
            <div>{{ section.name }}</div>
            <div style="font-size:11px;margin-top:2px;opacity:0.7">{{ sectionCount(section.key) }} 条记录</div>
          </div>
        </div>
      </div>
    </div>

    <!-- Right content area -->
    <div class="panel" style="flex:1;display:flex;flex-direction:column">
      <div class="panel-header" style="display:flex;align-items:center;justify-content:space-between">
        <h3 class="panel-title">{{ sectionTitle }}</h3>
        <div style="display:flex;gap:8px">
          <el-button size="small" :icon="Refresh" :loading="loading" @click="loadSectionData">刷新</el-button>
        </div>
      </div>
      <div class="panel-body" style="flex:1;overflow:auto">
        <div v-if="activeSection === 'vertical-models'" class="vertical-admin">
          <el-alert
            type="info"
            :closable="false"
            show-icon
            title="管理员可在这里统一上传垂类模型、激活版本、回滚、冻结或下线；普通任务入口只保留模型体验和调用。"
          />
          <el-tabs v-model="verticalModelTab">
            <el-tab-pane label="版本治理" name="governance">
              <AlgorithmManagementPanel :refresh-key="verticalRefreshKey" @changed="handleVerticalModelChanged" />
            </el-tab-pane>
            <el-tab-pane label="上传模型" name="upload">
              <AlgorithmUploadPanel @changed="handleVerticalModelChanged" />
            </el-tab-pane>
          </el-tabs>
        </div>

        <!-- Audit event table -->
        <el-table v-else-if="activeSection === 'audit-events'" :data="activeData.items" v-loading="loading" stripe>
          <el-table-column prop="event_type" label="事件类型" min-width="130" />
          <el-table-column prop="actor_user_id" label="操作人" min-width="170" />
          <el-table-column prop="entity_type" label="实体类型" min-width="120" />
          <el-table-column prop="entity_id" label="实体 ID" min-width="220" />
          <el-table-column prop="request_id" label="Request ID" min-width="150">
            <template #default="{ row }">{{ truncate(row.request_id, 16) }}</template>
          </el-table-column>
          <el-table-column label="时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
        </el-table>

        <!-- Computation table -->
        <el-table v-else-if="activeSection === 'computations'" :data="activeData.items" v-loading="loading" stripe>
          <el-table-column prop="run_id" label="Run ID" min-width="200" />
          <el-table-column label="分子" min-width="180">
            <template #default="{ row }">{{ row.molecule?.name || '-' }}</template>
          </el-table-column>
          <el-table-column prop="workflow_type" label="Workflow" min-width="140" />
          <el-table-column prop="engine" label="Engine" min-width="90" />
          <el-table-column label="状态" min-width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="created_by" label="创建人" min-width="140" />
        </el-table>

        <!-- Campaign table -->
        <el-table v-else-if="activeSection === 'campaigns'" :data="activeData.items" v-loading="loading" stripe>
          <el-table-column prop="campaign_id" label="Campaign ID" min-width="220" />
          <el-table-column prop="name" label="名称" min-width="200" />
          <el-table-column label="状态" min-width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="planner_type" label="Planner" min-width="110" />
          <el-table-column label="目标" min-width="180">
            <template #default="{ row }">{{ row.objectives?.map((o) => o.name).join(', ') || '-' }}</template>
          </el-table-column>
          <el-table-column label="创建时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
          </el-table-column>
          <el-table-column prop="created_by" label="创建人" min-width="140" />
        </el-table>

        <!-- Services table -->
        <el-table v-else-if="activeSection === 'services'" :data="activeData.items" v-loading="loading" stripe>
          <el-table-column prop="service" label="Service" min-width="200" />
          <el-table-column label="状态" min-width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status)">{{ statusLabel(row.status) }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="详情" min-width="220">
            <template #default="{ row }">
              <span style="font-size:12px;color:var(--app-ink-muted)">{{ row.details?.version || row.details?.path || row.details?.url || row.details?.root || row.details?.reason || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="检查时间" min-width="170">
            <template #default="{ row }">{{ formatDate(row.checked_at) }}</template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.vertical-admin {
  display: grid;
  gap: 14px;
}
</style>
