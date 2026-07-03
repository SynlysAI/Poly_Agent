<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { CloseBold, MagicStick, Plus, Refresh, SwitchButton, Upload, VideoPause } from '@element-plus/icons-vue'

import {
  archiveCampaign,
  completeCampaign,
  createCampaign,
  failCampaign,
  generateSuggestion,
  getApiErrorMessage,
  importChemosDemoCandidates,
  listCampaigns,
  pauseCampaign,
  resumeCampaign,
} from '../api/polyAgentApi'

const router = useRouter()
const campaigns = ref([])
const total = ref(0)
const loading = ref(false)
const creating = ref(false)
const createVisible = ref(false)
const actionLoadingId = ref('')

const filters = reactive({
  page: 1,
  page_size: 20,
})

const form = reactive({
  name: `Mock laser campaign ${new Date().toISOString().slice(0, 10)}`,
  objective: 'gain_factor',
  computationPreset: 'mock_laser',
})

const computationPresetOptions = [
  { value: 'mock_laser', label: 'Mock laser' },
  { value: 'orca_fixture', label: 'ORCA fixture' },
  { value: 'orca_external_fake', label: 'ORCA fake external' },
]

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusTag(status) {
  const map = { draft: 'info', running: 'warning', paused: 'info', completed: 'success', failed: 'danger', archived: 'info' }
  return map[status] || 'info'
}

function computationPresetLabel(row) {
  const raw = row?.planner_config?.computation_preset || 'mock_laser'
  const key = typeof raw === 'string' ? raw : raw?.preset_key
  return computationPresetOptions.find((item) => item.value === key)?.label || key || 'Mock laser'
}

function canImport(row) {
  return ['draft', 'running'].includes(row.status)
}

function canGenerate(row) {
  return row.status === 'running'
}

function statusActions(row) {
  if (row.status === 'running') {
    return [
      { label: 'Pause', action: 'pause', icon: VideoPause },
      { label: 'Complete', action: 'complete', icon: SwitchButton },
      { label: 'Fail', action: 'fail', icon: CloseBold },
      { label: 'Archive', action: 'archive', icon: CloseBold },
    ]
  }
  if (row.status === 'paused') {
    return [
      { label: 'Resume', action: 'resume', icon: SwitchButton },
      { label: 'Complete', action: 'complete', icon: SwitchButton },
      { label: 'Fail', action: 'fail', icon: CloseBold },
      { label: 'Archive', action: 'archive', icon: CloseBold },
    ]
  }
  if (row.status === 'draft') {
    return [
      { label: 'Archive', action: 'archive', icon: CloseBold },
      { label: 'Fail', action: 'fail', icon: CloseBold },
    ]
  }
  if (['completed', 'failed'].includes(row.status)) {
    return [{ label: 'Archive', action: 'archive', icon: CloseBold }]
  }
  return []
}

async function loadCampaigns() {
  loading.value = true
  try {
    const data = await listCampaigns(filters)
    campaigns.value = data.items || []
    total.value = data.total || 0
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function handleStatusAction(campaign, action) {
  const actionMap = {
    pause: pauseCampaign,
    resume: resumeCampaign,
    archive: archiveCampaign,
    complete: completeCampaign,
    fail: failCampaign,
  }
  try {
    const { value } = await ElMessageBox.prompt('请输入状态变更原因', `Campaign ${action}`, {
      confirmButtonText: action,
      cancelButtonText: '取消',
      inputType: 'textarea',
    })
    actionLoadingId.value = `${campaign.campaign_id}:${action}`
    await actionMap[action](campaign.campaign_id, { reason: value?.trim() || null })
    ElMessage.success(`Campaign 已${action}`)
    await loadCampaigns()
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoadingId.value = ''
  }
}

async function handleCreateCampaign() {
  creating.value = true
  try {
    const campaign = await createCampaign({
      name: form.name,
      planner_type: 'fallback',
      objectives: [{ name: form.objective, direction: 'max', required: true }],
      planner_config: { batch_size: 1, computation_preset: form.computationPreset },
    })
    ElMessage.success(`Campaign 已创建：${campaign.campaign_id}`)
    createVisible.value = false
    await loadCampaigns()
    await router.push(`/optimization/campaigns/${campaign.campaign_id}`)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    creating.value = false
  }
}

async function handleImportChemos(campaign) {
    actionLoadingId.value = `${campaign.campaign_id}:import`
  try {
    const data = await importChemosDemoCandidates(campaign.campaign_id)
    ElMessage.success(`已导入 ${data.imported_count} 个 ChemOS demo 候选`)
    await loadCampaigns()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoadingId.value = ''
  }
}

async function handleGenerateSuggestion(campaign) {
    actionLoadingId.value = `${campaign.campaign_id}:suggest`
  try {
    const data = await generateSuggestion(campaign.campaign_id, { batch_size: 1 })
    ElMessage.success(`已生成 ${data.items?.length || 0} 个 suggestion`)
    await router.push(`/optimization/campaigns/${campaign.campaign_id}`)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    actionLoadingId.value = ''
  }
}

onMounted(loadCampaigns)
</script>

<template>
  <div class="campaigns-view">
    <section class="panel">
      <div class="panel-header task-header">
        <div>
          <h3 class="panel-title">Optimization Campaigns</h3>
          <p class="panel-subtitle">管理候选库、推荐、计算回填 observation 和闭环历史。</p>
        </div>
        <div class="header-actions">
          <el-button :icon="Refresh" :loading="loading" @click="loadCampaigns">刷新</el-button>
          <el-button type="primary" :icon="Plus" @click="createVisible = true">新建 Campaign</el-button>
        </div>
      </div>
      <div class="panel-body">
        <el-table :data="campaigns" v-loading="loading" stripe>
          <el-table-column prop="campaign_id" label="Campaign ID" min-width="210" />
          <el-table-column prop="name" label="名称" min-width="220" />
          <el-table-column prop="status" label="状态" width="110">
            <template #default="{ row }">
              <el-tag size="small" :type="statusTag(row.status)">{{ row.status }}</el-tag>
            </template>
          </el-table-column>
          <el-table-column label="目标" min-width="180">
            <template #default="{ row }">
              <span>{{ row.objectives?.map((item) => item.name).join(', ') || '-' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="Preset" min-width="150">
            <template #default="{ row }">{{ computationPresetLabel(row) }}</template>
          </el-table-column>
          <el-table-column label="候选数" width="100">
            <template #default="{ row }">{{ row.search_space?.candidate_count || 0 }}</template>
          </el-table-column>
          <el-table-column label="更新时间" min-width="180">
            <template #default="{ row }">{{ formatDate(row.updated_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" min-width="300" fixed="right">
            <template #default="{ row }">
              <el-button text type="primary" size="small" @click="$router.push(`/optimization/campaigns/${row.campaign_id}`)">详情</el-button>
              <el-button text type="primary" size="small" :icon="Upload" :disabled="!canImport(row)" :loading="actionLoadingId === `${row.campaign_id}:import`" @click="handleImportChemos(row)">导入 ChemOS</el-button>
              <el-button text type="primary" size="small" :icon="MagicStick" :disabled="!canGenerate(row)" :loading="actionLoadingId === `${row.campaign_id}:suggest`" @click="handleGenerateSuggestion(row)">生成推荐</el-button>
              <el-dropdown v-if="statusActions(row).length" trigger="click">
                <el-button text type="primary" size="small">状态</el-button>
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item
                      v-for="item in statusActions(row)"
                      :key="item.action"
                      :icon="item.icon"
                      :disabled="actionLoadingId === `${row.campaign_id}:${item.action}`"
                      @click="handleStatusAction(row, item.action)"
                    >
                      {{ item.label }}
                    </el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </template>
          </el-table-column>
        </el-table>
        <div class="pagination-row">
          <el-pagination
            v-model:current-page="filters.page"
            v-model:page-size="filters.page_size"
            layout="total, sizes, prev, pager, next"
            :total="total"
            :page-sizes="[10, 20, 50]"
            @change="loadCampaigns"
          />
        </div>
      </div>
    </section>

    <el-dialog v-model="createVisible" title="新建 Campaign" width="520px">
      <el-form label-width="110px">
        <el-form-item label="名称">
          <el-input v-model="form.name" />
        </el-form-item>
        <el-form-item label="目标">
          <el-input v-model="form.objective" />
        </el-form-item>
        <el-form-item label="计算 preset">
          <el-select v-model="form.computationPreset">
            <el-option
              v-for="item in computationPresetOptions"
              :key="item.value"
              :label="item.label"
              :value="item.value"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreateCampaign">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.campaigns-view {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.task-header,
.header-actions {
  display: flex;
  align-items: center;
}

.task-header {
  gap: 16px;
}

.header-actions {
  gap: 10px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.pagination-row {
  display: flex;
  justify-content: flex-end;
  margin-top: 14px;
}
</style>
