<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  Aim, ChatLineRound, Check, FolderOpened, Histogram, MagicStick, Promotion, SetUp, View,
} from '@element-plus/icons-vue'

import {
  getApiErrorMessage,
  getIntegrationStatus,
  listAlgorithmRuns,
  listCampaigns,
  listComputations,
  listResearchRuns,
} from '../api/polyAgentApi'
import {
  isResearchEngineContainerCampaign,
  mapAlgorithmRunToGlobalTask,
  mapCampaignToGlobalTask,
  mapComputationRunToGlobalTask,
  mapResearchRunToGlobalTask,
} from '../tasks/taskModules'

const router = useRouter()
const loading = ref(false)
const activeView = ref('chat')
const computationRows = ref([])
const campaignRows = ref([])
const algorithmRuns = ref([])
const researchRuns = ref([])
const integrationItems = ref([])
const computationsTotal = ref(0)
const campaignsTotal = ref(0)
const algorithmRunsTotal = ref(0)
const researchRunsTotal = ref(0)
const chatMode = ref('qa')
const chatInput = ref('')

const dashboardViewOptions = [
  { label: '问答', value: 'chat' },
  { label: '看板', value: 'board' },
]

const chatModeOptions = [
  { label: '科研问答', value: 'qa' },
  { label: '深度思考', value: 'deep' },
  { label: '模型管理', value: 'model' },
]

const homeGreetings = {
  default: {
    title: '今天想推进哪条高分子研发路线？',
    subtitle: '描述材料体系、目标性质或实验约束，Poly Agent 会帮你定位模型、计算和优化入口。',
    placeholder: '例如：帮我为含氟聚合物设计 Tg 预测和后续验证流程...',
    suggestions: ['如何为 Tg 预测模型准备输入？', '哪些垂类模型可直接调用？', '帮我规划一个 AI4S 材料发现任务'],
  },
  morning: {
    title: '上午好，先看模型还是实验闭环？',
    subtitle: '从性质预测、计算验证到贝叶斯优化，把 AI4S 研发动作拆成可追踪任务。',
    placeholder: '输入你的聚合物结构、物性目标或实验设计问题...',
    suggestions: ['上传的预测模型现在怎么运行？', '如何把预测结果接到 AutoResearch？', '查看最近失败的计算任务'],
  },
  noon: {
    title: '中午好，要先梳理材料数据还是任务队列？',
    subtitle: '把上午积累的结构、配方和计算结果整理成下一步可执行动作。',
    placeholder: '例如：根据现有候选材料，安排下午的预测和验证任务...',
    suggestions: ['帮我整理下一步实验建议', '查看最近失败的计算任务', '哪些算法是真实适配器？'],
  },
  afternoon: {
    title: '下午好，继续推进材料研发任务吗？',
    subtitle: '围绕性质预测、计算验证和优化建议，快速进入问答、任务提交或研发编排。',
    placeholder: '例如：为一批候选聚合物安排预测、xTB 计算和优化建议...',
    suggestions: ['如何开始一个 ResearchEngine 示例？', '计算智能和垂类预测怎么衔接？', '如何查看待审批任务？'],
  },
  evening: {
    title: '晚上好，要复盘今天的材料数据吗？',
    subtitle: '可以从知识库、垂类模型和计算结果出发，形成明天的实验或算法调用建议。',
    placeholder: '输入数据来源、目标性质或需要比较的材料系列...',
    suggestions: ['查询知识库里的高分子体系', '帮我整理下一步实验建议', '查看今天的任务进展'],
  },
  night: {
    title: '需要把材料问题拆成可执行任务吗？',
    subtitle: '围绕高分子结构、配方、工艺和目标性能，快速进入问答、任务提交或研发编排。',
    placeholder: '例如：为一批候选聚合物安排预测、xTB 计算和优化建议...',
    suggestions: ['如何开始一个 ResearchEngine 示例？', '计算智能和垂类预测怎么衔接？', '如何查看待审批任务？'],
  },
}

function getTimeGreeting(date = new Date()) {
  const hour = date.getHours()
  if (hour >= 5 && hour < 12) return homeGreetings.morning
  if (hour >= 12 && hour < 14) return homeGreetings.noon
  if (hour >= 14 && hour < 18) return homeGreetings.afternoon
  if (hour >= 18 && hour < 24) return homeGreetings.evening
  if (hour >= 0 && hour < 5) return homeGreetings.night
  return homeGreetings.default
}

const homeGreeting = ref(getTimeGreeting())

const currentSuggestions = computed(() => homeGreeting.value.suggestions)

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
  const integrationsUp = integrationItems.value.filter((item) => item.status === 'up' || item.status === 'available').length

  return [
    { title: '总任务数', value: String(totalCount), color: '#3b82f6' },
    { title: '已完成', value: String(completedCount), color: '#16a34a' },
    { title: '运行中', value: String(runningCount), color: '#d97706' },
    { title: '待审批', value: String(blockedCount), color: '#ef4444' },
    { title: '模型服务', value: String(integrationsUp), color: '#7c3aed' },
  ]
})

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

const attentionTasks = computed(() =>
  recentTasks.value
    .filter((item) => ['blocked_approval', 'failed', 'running', 'queued'].includes(item.status))
    .slice(0, 6),
)

const serviceHealthCards = computed(() =>
  integrationItems.value.slice(0, 6).map((item) => ({
    service: item.service,
    status: item.status,
    message: item.details?.message || item.details?.reason || item.details?.version || item.status,
  })),
)

const moduleCards = computed(() => [
  {
    id: 'research-engine',
    icon: MagicStick,
    title: '研发引擎',
    description: '材料研发的算法编排平台，支持人工调用和自动编排两种模式。',
    highlights: ['定义研发任务与优化目标', '浏览材料算法', 'AutoResearch 自动推进'],
    route: '/research-engine',
    color: '#2563eb',
  },
  {
    id: 'task-submit',
    icon: Aim,
    title: '任务提交',
    description: '统一的工具调用入口，涵盖计算任务、湿实验优化和垂类模型。',
    highlights: ['提交计算任务', '启动贝叶斯优化', '上传预测模型'],
    route: '/tasks/submit',
    color: '#16a34a',
  },
  {
    id: 'task-center',
    icon: Histogram,
    title: '任务中心',
    description: '全局任务管理器，追踪所有模块的任务状态和进度。',
    highlights: ['筛选任务', '查看结果', '追踪进度'],
    route: '/tasks/center',
    color: '#d97706',
  },
  {
    id: 'tools',
    icon: SetUp,
    title: '工具服务',
    description: '查看计算工具链和后端服务的运行状态与集成配置。',
    highlights: ['工具链状态', '算法清单', '集成配置'],
    route: '/tools',
    color: '#0f766e',
  },
  {
    id: 'database',
    icon: FolderOpened,
    title: '数据管理',
    description: '统一查看材料数据资产、计算结果和 Mongo 结构化索引。',
    highlights: ['数据分级', '计算数据', '物性覆盖'],
    route: '/database/data-catalog',
    color: '#dc2626',
  },
])

function getStatusTag(status) {
  const map = { queued: 'info', running: 'warning', completed: 'success', failed: 'danger', cancelled: 'info', draft: 'info', paused: 'info', archived: 'info', blocked_approval: 'danger' }
  return map[status] || 'info'
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function goToTask(task) {
  if (task.route) router.push(task.route)
}

function openDialogue(prompt) {
  const text = String(prompt || chatInput.value).trim()
  if (!text) return
  router.push({
    path: '/dialogue',
    query: {
      prompt: text,
      mode: chatMode.value,
    },
  })
}

function handleChatKeydown(event) {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault()
    openDialogue()
  }
}

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
    <header class="dashboard-switchbar">
      <el-segmented v-model="activeView" :options="dashboardViewOptions" />
    </header>

    <section v-if="activeView === 'chat'" class="lui-hero">
      <div class="hero-copy">
        <p class="hero-kicker">Poly Agent 工作台</p>
        <h1>{{ homeGreeting.title }}</h1>
        <p>{{ homeGreeting.subtitle }}</p>
      </div>

      <div class="lui-composer">
        <div class="composer-input">
          <el-icon class="composer-mark"><ChatLineRound /></el-icon>
          <el-input
            v-model="chatInput"
            type="textarea"
            :rows="5"
            :placeholder="homeGreeting.placeholder"
            resize="none"
            @keydown="handleChatKeydown"
          />
        </div>
        <div class="composer-toolbar">
          <el-segmented v-model="chatMode" :options="chatModeOptions" />
          <el-button
            type="primary"
            :icon="Promotion"
            :disabled="!chatInput.trim()"
            @click="openDialogue()"
          >
            发送
          </el-button>
        </div>
      </div>

      <div class="suggestion-row" aria-label="推荐问题">
        <button v-for="question in currentSuggestions" :key="question" type="button" @click="openDialogue(question)">
          {{ question }}
        </button>
      </div>
    </section>

    <template v-else>
      <section class="dashboard-section">
        <div class="stat-grid" v-loading="loading">
          <div v-for="stat in stats" :key="stat.title" class="stat-card">
            <div class="stat-title">{{ stat.title }}</div>
            <div class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</div>
          </div>
        </div>
      </section>

      <section class="dashboard-section">
        <div class="section-heading">
          <h2>关键入口</h2>
          <p>保留常用路径，状态信息集中在看板中浏览。</p>
        </div>
        <div class="module-card-grid">
          <button v-for="card in moduleCards" :key="card.id" type="button" class="module-card" :style="{ '--card-accent': card.color }" @click="router.push(card.route)">
            <div class="module-card-header">
              <div class="module-card-icon">
                <el-icon :size="22"><component :is="card.icon" /></el-icon>
              </div>
              <div class="module-card-title-group">
                <strong>{{ card.title }}</strong>
                <span>{{ card.description }}</span>
              </div>
            </div>
            <div class="module-card-body">
              <span v-for="highlight in card.highlights" :key="highlight"><el-icon><Check /></el-icon>{{ highlight }}</span>
            </div>
          </button>
        </div>
      </section>

      <section class="dashboard-section command-grid">
        <div class="panel command-panel command-panel-primary">
          <div class="command-panel-header">
            <div>
              <h2>待处理任务</h2>
              <p>审批、失败和运行中的任务优先显示在这里。</p>
            </div>
            <el-button text type="primary" @click="router.push('/tasks/center')">全部任务</el-button>
          </div>
          <div v-if="attentionTasks.length" class="attention-list">
            <button v-for="task in attentionTasks" :key="task.task_id" type="button" class="attention-item" @click="goToTask(task)">
              <span>
                <strong>{{ task.title }}</strong>
                <small>{{ task.module_name }} · {{ task.task_id }}</small>
              </span>
              <el-tag :type="getStatusTag(task.status)" size="small">{{ task.status_text || task.status }}</el-tag>
            </button>
          </div>
          <el-empty v-else description="暂无需要处理的任务" :image-size="80" />
        </div>

        <div class="panel command-panel">
          <div class="command-panel-header">
            <div>
              <h2>服务健康</h2>
              <p>计算 worker、工具链和知识服务的最近状态。</p>
            </div>
            <el-button text type="primary" @click="router.push('/tools')">工具服务</el-button>
          </div>
          <div v-if="serviceHealthCards.length" class="service-health-list">
            <div v-for="item in serviceHealthCards" :key="item.service" class="service-health-item">
              <span>
                <strong>{{ item.service }}</strong>
                <small>{{ item.message }}</small>
              </span>
              <el-tag size="small" :type="['up', 'available', 'built_in'].includes(item.status) ? 'success' : item.status === 'disabled' ? 'info' : 'warning'">
                {{ item.status }}
              </el-tag>
            </div>
          </div>
          <el-empty v-else description="暂无服务状态" :image-size="80" />
        </div>
      </section>

      <section class="panel recent-panel">
        <div class="panel-header">
          <h2 class="panel-title">最近任务</h2>
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
      </section>
    </template>
  </div>
</template>

<style scoped>
.dashboard-view { max-width: 1440px; margin: 0 auto; display: grid; gap: 16px; }
.dashboard-switchbar { display: flex; align-items: center; justify-content: flex-start; min-height: 32px; }
.lui-hero { min-height: calc(100vh - 188px); display: grid; align-content: center; justify-items: center; gap: 16px; padding: 34px 16px 28px; }
.hero-copy { max-width: 760px; text-align: center; }
.hero-kicker { margin: 0 0 8px; color: var(--app-primary-active); font-size: 13px; font-weight: 700; }
h1, h2 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
h1 { font-size: 38px; line-height: 1.18; }
h2 { font-size: 16px; line-height: 1.35; }
.hero-copy p:last-child, .section-heading p, .command-panel-header p { margin: 8px 0 0; color: var(--app-ink-muted); font-size: 14px; line-height: 1.65; }
.lui-composer { width: min(820px, 100%); border: 1px solid #bcd5fb; border-radius: var(--app-radius-lg); background: rgba(255, 255, 255, 0.96); box-shadow: 0 18px 44px rgba(22, 59, 110, 0.09); padding: 14px; }
.composer-input { display: grid; grid-template-columns: 26px minmax(0, 1fr); gap: 8px; align-items: start; }
.composer-mark { margin-top: 8px; color: var(--app-primary-active); font-size: 20px; }
.composer-input :deep(.el-textarea__inner) { min-height: 116px !important; border: 0; box-shadow: none; font-size: 15px; line-height: 1.7; }
.composer-toolbar { display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 10px; border-top: 1px solid var(--app-border-soft); }
.suggestion-row { width: min(820px, 100%); display: flex; justify-content: center; gap: 8px; flex-wrap: wrap; }
.suggestion-row button { max-width: 100%; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-pill); background: rgba(255, 255, 255, 0.86); color: var(--app-ink-body); padding: 8px 12px; font: inherit; font-size: 13px; cursor: pointer; }
.suggestion-row button:hover { border-color: #bfdbfe; color: var(--app-primary-active); }
.dashboard-section { display: grid; gap: 14px; }
.section-heading { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; }
.stat-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.module-card-grid { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 12px; }
.module-card { min-width: 0; display: grid; gap: 12px; padding: 14px; border: 1px solid var(--app-border); border-radius: var(--app-radius-md); background: #fff; color: inherit; text-align: left; cursor: pointer; transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease; }
.module-card:hover { border-color: #bfdbfe; box-shadow: 0 10px 22px rgba(37, 99, 235, 0.08); transform: translateY(-1px); }
.module-card:focus-visible { outline: 3px solid var(--app-primary-light); outline-offset: 2px; }
.module-card-header { display: grid; grid-template-columns: 42px minmax(0, 1fr); gap: 10px; align-items: start; }
.module-card-icon { width: 42px; height: 42px; display: grid; place-items: center; border-radius: var(--app-radius-sm); background: color-mix(in srgb, var(--card-accent) 12%, white); color: var(--card-accent); }
.module-card-title-group { min-width: 0; display: grid; gap: 4px; }
.module-card-title-group strong { color: var(--app-ink); font-size: 15px; }
.module-card-title-group span { display: -webkit-box; overflow: hidden; color: var(--app-ink-muted); font-size: 12px; line-height: 1.55; -webkit-line-clamp: 2; -webkit-box-orient: vertical; }
.module-card-body { display: grid; gap: 5px; }
.module-card-body span { display: inline-flex; align-items: center; gap: 5px; color: var(--app-ink-body); font-size: 12px; }
.module-card-body .el-icon { color: var(--card-accent); }
.command-grid { grid-template-columns: minmax(0, 1.1fr) minmax(320px, 0.9fr); align-items: start; }
.command-panel { padding: 16px; min-height: 320px; }
.command-panel-header { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 14px; }
.attention-list, .service-health-list { display: grid; gap: 10px; }
.attention-item, .service-health-item { width: 100%; display: grid; grid-template-columns: minmax(0, 1fr) auto; align-items: center; gap: 12px; padding: 12px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #fff; text-align: left; }
.attention-item { cursor: pointer; }
.attention-item:hover { border-color: #bfdbfe; background: #f8fbff; }
.attention-item span, .service-health-item span { min-width: 0; display: grid; gap: 3px; }
.attention-item strong, .service-health-item strong { overflow: hidden; color: var(--app-ink); font-size: 13px; text-overflow: ellipsis; white-space: nowrap; }
.attention-item small, .service-health-item small { overflow: hidden; color: var(--app-ink-muted); font-size: 12px; text-overflow: ellipsis; white-space: nowrap; }
.recent-panel { overflow: hidden; }
@media (max-width: 1280px) {
  .stat-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .module-card-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .dashboard-switchbar { justify-content: center; }
  .lui-hero { min-height: auto; padding: 24px 0 18px; }
  h1 { font-size: 30px; }
  .composer-toolbar, .section-heading, .command-panel-header { align-items: stretch; flex-direction: column; }
  .stat-grid, .module-card-grid, .command-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  h1 { font-size: 25px; }
  .lui-composer { padding: 10px; }
  .composer-input { grid-template-columns: 1fr; }
  .composer-mark { display: none; }
  .stat-grid { grid-template-columns: 1fr; }
}
</style>
