<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { View } from '@element-plus/icons-vue'

import { getApiErrorMessage, getIntegrationStatus, listAlgorithmRuns, listCampaigns, listComputations, listResearchRuns } from '../api/polyAgentApi'
import { mapAlgorithmRunToGlobalTask, mapCampaignToGlobalTask, mapComputationRunToGlobalTask, mapResearchRunToGlobalTask } from '../tasks/taskModules'

const router = useRouter()
const loading = ref(false)
const computationRows = ref([])
const campaignRows = ref([])
const algorithmRuns = ref([])
const researchRuns = ref([])
const integrationItems = ref([])
const computationsTotal = ref(0)
const campaignsTotal = ref(0)

const stats = computed(() => {
  const allItems = [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...campaignRows.value.map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ]
  const runningCount = allItems.filter((item) => item.status === 'running').length
  const completedCount = allItems.filter((item) => item.status === 'completed').length
  const blockedCount = allItems.filter((item) => item.status === 'blocked_approval').length
  const integrationsUp = integrationItems.value.filter(
    (item) => item.status === 'up' || item.status === 'available',
  ).length

  return [
    { title: '总任务数', value: String(computationsTotal.value + campaignsTotal.value), color: '#3b82f6' },
    { title: '已完成', value: String(completedCount), color: '#16a34a' },
    { title: '运行中', value: String(runningCount), color: '#d97706' },
    { title: '待审批', value: String(blockedCount), color: '#d97706' },
    { title: '模型服务', value: String(integrationsUp), color: '#7c3aed' },
  ]
})

const recentTasks = computed(() =>
  [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...campaignRows.value.map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ]
    .sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
    .slice(0, 10),
)

function getStatusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info', draft: 'info', paused: 'info', archived: 'info', blocked_approval: 'danger' }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function goToTask(task) {
  if (task.route) {
    router.push(task.route)
  }
}

async function loadDashboardData() {
  loading.value = true
  try {
    const [computations, campaigns, algoRuns, researchRunsData, status] = await Promise.all([
      listComputations({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listCampaigns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listAlgorithmRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [] })),
      listResearchRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [] })),
      getIntegrationStatus().catch(() => ({ items: [] })),
    ])
    computationRows.value = computations.items || []
    campaignRows.value = campaigns.items || []
    algorithmRuns.value = algoRuns.items || []
    researchRuns.value = researchRunsData.items || []
    integrationItems.value = status.items || []
    computationsTotal.value = computations.total || 0
    campaignsTotal.value = campaigns.total || 0
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadDashboardData()
})
</script>

<template>
  <div>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-header">
        <h3 class="panel-title">工作台概览</h3>
      </div>
      <div class="panel-body">
        <div class="stat-grid" v-loading="loading">
          <div v-for="stat in stats" :key="stat.title" class="stat-card">
            <div class="stat-title">{{ stat.title }}</div>
            <div class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="page-grid">
      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title">最近任务</h3>
        </div>
        <div class="panel-body">
          <el-table :data="recentTasks" v-loading="loading" stripe style="width:100%">
            <el-table-column prop="task_id" label="任务编号" min-width="190" />
            <el-table-column prop="task_type" label="任务类型" min-width="120" />
            <el-table-column prop="module_name" label="模块" min-width="120" />
            <el-table-column label="状态" min-width="100">
              <template #default="{ row }">
                <el-tag :type="getStatusTag(row.status)" size="small">{{ row.status_text || row.status }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column label="提交时间" min-width="170">
              <template #default="{ row }">{{ formatDate(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="100">
              <template #default="{ row }">
                <el-button text type="primary" size="small" :icon="View" @click="goToTask(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title">快捷操作</h3>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:10px">
          <el-button type="primary" @click="$router.push('/tasks/submit')" style="width:100%">新建任务</el-button>
          <el-button @click="$router.push('/tasks/center')" style="width:100%">查看任务中心</el-button>
          <el-button @click="$router.push('/dialogue')" style="width:100%">问答对话</el-button>
          <el-button @click="$router.push('/tools')" style="width:100%">工具服务</el-button>
          <el-button type="primary" @click="$router.push('/research-engine')" style="width:100%">ResearchEngine 研发引擎</el-button>
        </div>
      </div>
    </div>
  </div>
</template>
