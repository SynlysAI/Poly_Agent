<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  View, MagicStick, Aim, Histogram, SetUp, FolderOpened,
  ChatLineRound, Promotion, Loading, Check, Fold, Expand,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage, getIntegrationStatus, listAlgorithmRuns,
  listCampaigns, listComputations, listResearchRuns, chatWithLLM,
} from '../api/polyAgentApi'
import {
  isResearchEngineContainerCampaign,
  mapAlgorithmRunToGlobalTask, mapCampaignToGlobalTask,
  mapComputationRunToGlobalTask, mapResearchRunToGlobalTask,
} from '../tasks/taskModules'
import { authState } from '../auth/authState'

const router = useRouter()
const loading = ref(false)
const computationRows = ref([])
const campaignRows = ref([])
const algorithmRuns = ref([])
const researchRuns = ref([])
const integrationItems = ref([])
const computationsTotal = ref(0)
const campaignsTotal = ref(0)
const algorithmRunsTotal = ref(0)
const researchRunsTotal = ref(0)
const dashboardActiveTab = ref('modules')

// ------ Stats ------
const stats = computed(() => {
  const visibleCampaignRows = campaignRows.value.filter((item) => !isResearchEngineContainerCampaign(item))
  const allItems = [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...visibleCampaignRows.map(mapCampaignToGlobalTask),
    ...algorithmRuns.value.map(mapAlgorithmRunToGlobalTask),
    ...researchRuns.value.map(mapResearchRunToGlobalTask),
  ]
  const totalCount = computationsTotal.value + campaignsTotal.value + algorithmRunsTotal.value + researchRunsTotal.value
  const runningCount = allItems.filter((item) => item.status === 'running').length
  const completedCount = allItems.filter((item) => item.status === 'completed').length
  const blockedCount = allItems.filter((item) => item.status === 'blocked_approval').length
  const integrationsUp = integrationItems.value.filter(
    (item) => item.status === 'up' || item.status === 'available',
  ).length

  return [
    { title: '总任务数', value: String(totalCount), color: '#3b82f6' },
    { title: '已完成', value: String(completedCount), color: '#16a34a' },
    { title: '运行中', value: String(runningCount), color: '#d97706' },
    { title: '待审批', value: String(blockedCount), color: '#ef4444' },
    { title: '模型服务', value: String(integrationsUp), color: '#7c3aed' },
  ]
})

// ------ Recent Tasks ------
const recentTasks = computed(() =>
  [
    ...computationRows.value.map(mapComputationRunToGlobalTask),
    ...campaignRows.value.filter((item) => !isResearchEngineContainerCampaign(item)).map(mapCampaignToGlobalTask),
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

// ------ AI Chat Panel ------
const chatMessages = ref([
  { role: 'assistant', content: '你好！我是 PolyAgent 智能助手。你可以向我咨询材料研发相关的问题，比如：\n\n• 如何提交一个计算任务？\n• 怎样设计一个贝叶斯优化实验？\n• 想了解某个聚合物的力学性能预测\n• 帮我分析材料的介电常数数据' },
])
const chatInput = ref('')
const chatSending = ref(false)
const chatBodyRef = ref(null)
const assistantCollapsed = ref(false)
const assistantToggleLabel = computed(() => (assistantCollapsed.value ? '展开 AI 智能助手' : '隐藏 AI 智能助手'))

function toggleAssistantPanel() {
  assistantCollapsed.value = !assistantCollapsed.value
}

async function sendChatMessage() {
  const text = chatInput.value.trim()
  if (!text || chatSending.value) return
  chatMessages.value.push({ role: 'user', content: text })
  chatInput.value = ''
  chatSending.value = true
  // 滚动到底部
  setTimeout(() => {
    if (chatBodyRef.value) {
      chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
    }
  }, 50)
  try {
    const data = await chatWithLLM(chatMessages.value.map(m => ({ role: m.role, content: m.content })))
    chatMessages.value.push({ role: 'assistant', content: data.content || data.message || '抱歉，未能获得有效回复。' })
  } catch (e) {
    chatMessages.value.push({ role: 'assistant', content: `对话出错：${e.message || '未知错误'}` })
  } finally {
    chatSending.value = false
    setTimeout(() => {
      if (chatBodyRef.value) {
        chatBodyRef.value.scrollTop = chatBodyRef.value.scrollHeight
      }
    }, 50)
  }
}

function handleChatKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    sendChatMessage()
  }
}

// ------ Module Cards ------
const canAccessAdminFeatures = computed(() => !authState.authEnabled || authState.role === 'admin')

const moduleCards = computed(() => {
  const cards = [
    {
      id: 'research-engine',
      icon: MagicStick,
      title: '研发引擎',
      description: '材料研发的算法编排平台，支持人工调用和自动编排两种模式。',
      highlights: ['定义研发任务与优化目标', '浏览 8+ 种材料算法', 'AutoResearch 十阶段自动推进'],
      route: '/research-engine',
      color: '#7c3aed',
    },
    {
      id: 'task-submit',
      icon: Aim,
      title: '任务提交',
      description: '统一的工具调用入口，涵盖计算任务、湿实验优化和垂类模型。',
      highlights: ['提交 DFT/xTB/ORCA 计算', '启动贝叶斯优化 Campaign', '使用 Alchemist 实验设计'],
      route: '/tasks/submit',
      color: '#3b82f6',
    },
    {
      id: 'task-center',
      icon: Histogram,
      title: '任务中心',
      description: '全局任务管理器，追踪所有模块的任务状态和进度。',
      highlights: ['按模块/状态筛选任务', '查看任务详情与结果', '追踪任务执行进度'],
      route: '/tasks/center',
      color: '#16a34a',
    },
    {
      id: 'tools',
      icon: SetUp,
      title: '工具服务',
      description: '查看计算工具链和后端服务的运行状态与集成配置。',
      highlights: ['RDKit / xTB / ORCA 状态', '算法清单与 Schema', '集成服务配置管理'],
      route: '/tools',
      color: '#d97706',
    },
  ]
  if (canAccessAdminFeatures.value) {
    cards.push({
      id: 'database',
      icon: FolderOpened,
      title: '数据库管理',
      description: '系统数据库管理，包含用户、邀请码和审计日志。',
      highlights: ['用户与权限管理', '邀请码管理', '审计日志查询'],
      route: '/database',
      color: '#dc2626',
    })
  }
  return cards
})

// ------ Data Loading ------
async function loadDashboardData() {
  loading.value = true
  try {
    const [computations, campaigns, algoRuns, researchRunsData, status] = await Promise.all([
      listComputations({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listCampaigns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listAlgorithmRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      listResearchRuns({ page: 1, page_size: 5 }).catch(() => ({ items: [], total: 0 })),
      getIntegrationStatus().catch(() => ({ items: [] })),
    ])
    computationRows.value = computations.items || []
    campaignRows.value = campaigns.items || []
    algorithmRuns.value = algoRuns.items || []
    researchRuns.value = researchRunsData.items || []
    integrationItems.value = status.items || []
    computationsTotal.value = computations.total || 0
    campaignsTotal.value = campaigns.total || 0
    algorithmRunsTotal.value = algoRuns.total || 0
    researchRunsTotal.value = researchRunsData.total || 0
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
  <div class="dashboard-view">
    <div class="dashboard-layout" :class="{ 'assistant-collapsed': assistantCollapsed }">
      <main class="dashboard-main">
        <div class="panel dashboard-overview-panel">
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

        <div class="panel dashboard-workspace-panel">
          <el-tabs v-model="dashboardActiveTab" class="dashboard-tabs">
            <el-tab-pane label="功能模块" name="modules">
              <div class="dashboard-tab-body">
                <div class="module-card-grid">
                  <div
                    v-for="card in moduleCards"
                    :key="card.id"
                    class="module-card"
                    :style="{ '--card-accent': card.color }"
                  >
                    <div class="module-card-header">
                      <div class="module-card-icon" :style="{ background: card.color }">
                        <el-icon :size="22"><component :is="card.icon" /></el-icon>
                      </div>
                      <div class="module-card-title-group">
                        <div class="module-card-title">{{ card.title }}</div>
                        <div class="module-card-desc">{{ card.description }}</div>
                      </div>
                    </div>
                    <div class="module-card-body">
                      <div v-for="(h, i) in card.highlights" :key="i" class="module-card-highlight">
                        <el-icon :size="14"><Check /></el-icon>
                        <span>{{ h }}</span>
                      </div>
                    </div>
                    <div class="module-card-footer">
                      <el-button type="primary" plain size="small" @click="router.push(card.route)">进入</el-button>
                    </div>
                  </div>
                </div>
              </div>
            </el-tab-pane>
            <el-tab-pane label="最近任务" name="recent">
              <div class="dashboard-tab-body">
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
            </el-tab-pane>
          </el-tabs>
        </div>
      </main>

      <aside class="dashboard-assistant" :class="{ collapsed: assistantCollapsed }">
        <button
          v-if="assistantCollapsed"
          type="button"
          class="assistant-rail"
          :aria-label="assistantToggleLabel"
          :title="assistantToggleLabel"
          @click="toggleAssistantPanel"
        >
          <el-icon :size="18"><ChatLineRound /></el-icon>
          <span class="assistant-rail-label">AI 助手</span>
          <el-icon :size="16"><Expand /></el-icon>
        </button>
        <div v-else class="panel chat-panel">
          <div class="panel-header chat-header">
            <div class="chat-toggle-left">
              <el-icon :size="18"><ChatLineRound /></el-icon>
              <span class="chat-toggle-title">AI 智能助手</span>
            </div>
            <div class="chat-header-actions">
              <el-tag size="small" type="success" effect="plain">PolyAgent</el-tag>
              <el-button
                circle
                text
                class="chat-collapse-button"
                :aria-label="assistantToggleLabel"
                :title="assistantToggleLabel"
                @click="toggleAssistantPanel"
              >
                <el-icon><Fold /></el-icon>
              </el-button>
            </div>
          </div>
          <div class="chat-body-wrapper">
            <div ref="chatBodyRef" class="chat-body">
              <div
                v-for="(msg, idx) in chatMessages"
                :key="idx"
                class="chat-message"
                :class="msg.role === 'user' ? 'chat-message-user' : 'chat-message-assistant'"
              >
                <div class="chat-bubble">
                  <div class="chat-bubble-text">{{ msg.content }}</div>
                </div>
              </div>
              <div v-if="chatSending" class="chat-message chat-message-assistant">
                <div class="chat-bubble chat-bubble-loading">
                  <el-icon class="is-loading"><Loading /></el-icon>
                  <span>思考中...</span>
                </div>
              </div>
            </div>
            <div class="chat-input-area">
              <el-input
                v-model="chatInput"
                type="textarea"
                :rows="3"
                placeholder="输入你的问题..."
                :disabled="chatSending"
                resize="none"
                @keydown="handleChatKeydown"
              />
              <el-button
                type="primary"
                :icon="Promotion"
                :disabled="!chatInput.trim() || chatSending"
                :loading="chatSending"
                @click="sendChatMessage"
              >
                发送
              </el-button>
            </div>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.dashboard-view {
  max-width: 1440px;
}

.dashboard-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 360px);
  grid-template-areas:
    "overview assistant"
    "workspace assistant";
  gap: 16px;
  align-items: start;
  transition: grid-template-columns 0.2s ease;
}

.dashboard-layout.assistant-collapsed {
  grid-template-columns: minmax(0, 1fr) 52px;
}

.dashboard-main {
  display: contents;
}

.dashboard-overview-panel {
  grid-area: overview;
}

.dashboard-workspace-panel {
  grid-area: workspace;
  overflow: hidden;
}

.dashboard-assistant {
  grid-area: assistant;
  position: sticky;
  top: 0;
  align-self: stretch;
  min-width: 0;
  height: 100%;
}

.dashboard-assistant.collapsed {
  width: 52px;
}

/* ---- Chat Panel ---- */
.chat-panel {
  height: 100%;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.chat-toggle-left {
  display: flex;
  align-items: center;
  gap: 10px;
}
.chat-toggle-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--app-ink);
}
.chat-header-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.chat-collapse-button {
  width: 28px;
  height: 28px;
  color: var(--app-ink-muted);
}
.chat-collapse-button:hover {
  color: var(--app-primary);
  background: var(--app-primary-light);
}

.assistant-rail {
  width: 52px;
  height: 100%;
  min-height: 168px;
  border: 1px solid #dfebfa;
  border-radius: var(--app-radius-lg);
  background: #ffffff;
  box-shadow: 0 10px 24px rgba(22, 59, 110, 0.06);
  color: var(--app-sidebar-from);
  cursor: pointer;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  padding: 14px 0;
  transition: border-color 0.2s ease, background 0.2s ease, color 0.2s ease;
}
.assistant-rail:hover {
  border-color: var(--app-primary);
  background: #f8fbff;
  color: var(--app-primary);
}
.assistant-rail:focus-visible {
  outline: 2px solid var(--app-primary);
  outline-offset: 2px;
}
.assistant-rail-label {
  writing-mode: vertical-rl;
  text-orientation: mixed;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0;
}

.chat-body-wrapper {
  border-top: 1px solid var(--app-border-soft);
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}
.chat-body {
  flex: 1;
  min-height: 0;
  max-height: none;
  overflow-y: auto;
  padding: 12px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chat-message {
  display: flex;
  max-width: 85%;
}
.chat-message-user {
  align-self: flex-end;
}
.chat-message-assistant {
  align-self: flex-start;
}
.chat-bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.chat-message-user .chat-bubble {
  background: #3b82f6;
  color: #fff;
  border-bottom-right-radius: 4px;
}
.chat-message-assistant .chat-bubble {
  background: #f8fbff;
  color: var(--app-ink-body);
  border: 1px solid var(--app-border-soft);
  border-bottom-left-radius: 4px;
}
.chat-bubble-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--app-ink-muted);
}
.chat-input-area {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid var(--app-border-soft);
  align-items: flex-end;
}

/* ---- Dashboard Tabs ---- */
.dashboard-tabs {
  --el-tabs-header-height: 58px;
}
.dashboard-tabs :deep(.el-tabs__header) {
  margin: 0;
  padding: 0 18px;
  border-bottom: 1px solid #edf2fa;
}
.dashboard-tabs :deep(.el-tabs__nav-wrap::after) {
  height: 0;
}
.dashboard-tabs :deep(.el-tabs__item) {
  height: 58px;
  padding: 0 24px 0 0;
  color: var(--app-ink-body);
  font-size: 16px;
  font-weight: 700;
}
.dashboard-tabs :deep(.el-tabs__item.is-active) {
  color: var(--app-primary);
}
.dashboard-tabs :deep(.el-tabs__active-bar) {
  height: 2px;
  background: var(--app-primary);
}
.dashboard-tab-body {
  padding: 16px 18px 18px;
}

/* ---- Module Cards Grid ---- */
.module-card-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}
@media (max-width: 1100px) {
  .module-card-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 700px) {
  .module-card-grid {
    grid-template-columns: 1fr;
  }
}

.module-card {
  background: #ffffff;
  border: 1px solid var(--app-border-soft);
  border-top: 3px solid var(--card-accent);
  border-radius: var(--app-radius-md);
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: border-color 0.2s, background 0.2s;
}
.module-card:hover {
  border-color: var(--card-accent);
  background: #f8fbff;
}

.module-card-header {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}
.module-card-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  flex-shrink: 0;
}
.module-card-title-group {
  flex: 1;
  min-width: 0;
}
.module-card-title {
  font-weight: 600;
  font-size: 15px;
  color: var(--app-ink);
  margin-bottom: 4px;
}
.module-card-desc {
  font-size: 13px;
  color: var(--app-ink-body);
  line-height: 1.5;
}

.module-card-body {
  display: flex;
  flex-direction: column;
  gap: 6px;
  flex: 1;
}
.module-card-highlight {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--app-ink-body);
}
.module-card-highlight .el-icon {
  color: var(--card-accent);
  flex-shrink: 0;
}

.module-card-footer {
  display: flex;
  justify-content: flex-end;
  padding-top: 4px;
}

@media (max-width: 1100px) {
  .dashboard-layout,
  .dashboard-layout.assistant-collapsed {
    grid-template-columns: 1fr;
    grid-template-areas:
      "overview"
      "workspace"
      "assistant";
  }

  .dashboard-assistant {
    position: static;
    height: auto;
  }

  .dashboard-assistant.collapsed {
    width: auto;
  }

  .assistant-rail {
    width: 100%;
    height: auto;
    min-height: 52px;
    flex-direction: row;
    padding: 12px 16px;
  }

  .assistant-rail-label {
    writing-mode: horizontal-tb;
  }

  .chat-body {
    min-height: 280px;
    max-height: 420px;
  }

  .chat-panel {
    height: auto;
  }
}
</style>
