<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  CircleCheck, Clock, View, Cpu, SetUp,
  DataAnalysis, Promotion,
} from '@element-plus/icons-vue'

import { getApiErrorMessage, getIntegrationStatus, listCampaigns, listComputations } from '../api/polyAgentApi'
import {
  TASK_MODULES,
  isResearchEngineContainerCampaign,
  mapCampaignToGlobalTask,
  mapComputationRunToGlobalTask,
} from '../tasks/taskModules'

const router = useRouter()
const recentTasks = ref([])
const integrations = ref([])
const loading = ref(false)
const activeTab = ref('computation')

// ------ Category Tabs Configuration ------
const taskCategories = [
  {
    id: 'computation',
    label: '计算智能',
    icon: Cpu,
    entries: [
      {
        id: 'computation-submit',
        name: '提交计算任务',
        description: '创建可追踪的真实 DFT/xTB/ORCA 计算任务，支持 SMILES 分子结构输入。',
        actionText: '新建计算任务',
        route: '/computations/submit',
        tags: ['SMILES', 'xTB', 'ORCA', 'CREST', 'Timeline'],
      },
      {
        id: 'computation-runs',
        name: '计算任务管理',
        description: '查看和管理已提交的计算任务，追踪 workflow 执行进度和 artifact。',
        actionText: '进入管理中心',
        route: '/computations/runs',
        tags: ['状态追踪', 'Artifact', 'Timeline', 'Worker'],
      },
    ],
  },
  {
    id: 'wetlab',
    label: '湿实验优化',
    icon: SetUp,
    entries: [
      {
        id: 'wetlab-campaigns',
        name: 'Campaign 闭环管理',
        description: '管理候选库、生成推荐建议、提交计算验证并回填 observation 形成实验闭环。',
        actionText: '进入 Campaign',
        route: '/optimization/campaigns',
        tags: ['候选库', 'Suggestion', 'Observation'],
      },
      {
        id: 'wetlab-alchemist',
        name: 'Alchemist 实验设计',
        description: '定义变量空间、生成实验设计、训练 GP 模型并执行贝叶斯采集优化。',
        actionText: '进入 Alchemist',
        route: '/optimization/alchemist',
        tags: ['变量定义', 'GP 建模', '采集优化'],
      },
    ],
  },
  {
    id: 'vertical',
    label: '垂类预测模型',
    icon: DataAnalysis,
    entries: [
      {
        id: 'vertical-prediction',
        name: '垂类预测模型',
        description: '聚合物热学、力学、流变等垂类性质预测模型入口，后续接入模型服务。',
        actionText: '即将上线',
        route: null,
        tags: ['热学性能', '力学性能', '流变性能', '即将上线'],
        comingSoon: true,
      },
    ],
  },
]

// ------ Dock Data (right sidebar, unchanged) ------
const onlineModules = computed(() => TASK_MODULES.filter(
  (module) => module.id !== 'research-engine' && (module.status === 'online' || module.status === 'preview'),
))

const serviceStatusLines = computed(() => {
  const worker = integrations.value.find((item) => item.service === 'computation-worker')
  const alchemist = integrations.value.find((item) => item.service === 'alchemist-backend')
  return [
    worker?.status === 'up' ? '计算 worker 在线' : `计算 worker ${worker?.status || '未检查'}`,
    alchemist?.status === 'up' ? 'Alchemist 后端在线' : `Alchemist 后端 ${alchemist?.status || '未检查'}`,
  ]
})

function openModule(module) {
  if (module.routes?.submit) {
    router.push(module.routes.submit)
    return
  }
  ElMessage.info(`${module.name} 正在接入中`)
}

function navigateTo(route) {
  if (!route) {
    ElMessage.info('该功能即将上线，敬请期待')
    return
  }
  router.push(route)
}

async function loadDockData() {
  loading.value = true
  try {
    const [runs, campaigns, status] = await Promise.all([
      listComputations({ page: 1, page_size: 5 }).catch(() => ({ items: [] })),
      listCampaigns({ page: 1, page_size: 5 }).catch(() => ({ items: [] })),
      getIntegrationStatus().catch(() => ({ items: [] })),
    ])
    recentTasks.value = [
      ...(runs.items || []).map(mapComputationRunToGlobalTask),
      ...(campaigns.items || []).filter((item) => !isResearchEngineContainerCampaign(item)).map(mapCampaignToGlobalTask),
    ]
      .sort((a, b) => new Date(b.updated_at || b.created_at || 0).getTime() - new Date(a.updated_at || a.created_at || 0).getTime())
      .slice(0, 5)
    integrations.value = status.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

onMounted(() => {
  loadDockData()
})
</script>

<template>
  <div class="task-launcher">
    <!-- Main Content: Category Tabs + Card Grid -->
    <section class="panel task-catalog">
      <div class="panel-header launcher-header">
        <div>
          <h3 class="panel-title">任务提交</h3>
          <p class="panel-subtitle">统一的工具调用入口。计算任务、湿实验优化和垂类模型都从这里进入。</p>
        </div>
      </div>
      <div class="panel-body">
        <!-- Category Tabs -->
        <el-tabs v-model="activeTab" class="category-tabs">
          <el-tab-pane
            v-for="cat in taskCategories"
            :key="cat.id"
            :label="cat.label"
            :name="cat.id"
          >
            <template #label>
              <span class="tab-label">
                <el-icon><component :is="cat.icon" /></el-icon>
                <span>{{ cat.label }}</span>
              </span>
            </template>
          </el-tab-pane>
        </el-tabs>

        <!-- Entry Card Grid for Active Tab -->
        <div class="entry-grid">
          <template v-for="cat in taskCategories" :key="cat.id">
            <article
              v-if="activeTab === cat.id"
              v-for="entry in cat.entries"
              :key="entry.id"
              class="entry-card"
              :class="{ 'entry-card-disabled': entry.comingSoon }"
            >
              <div class="entry-card-top">
                <div class="entry-icon">
                  <el-icon :size="20"><component :is="cat.icon" /></el-icon>
                </div>
                <div class="entry-tags">
                  <el-tag
                    v-for="tag in entry.tags"
                    :key="tag"
                    size="small"
                    :type="entry.comingSoon ? 'info' : undefined"
                    effect="plain"
                  >
                    {{ tag }}
                  </el-tag>
                </div>
              </div>
              <h4 class="entry-name">{{ entry.name }}</h4>
              <p class="entry-desc">{{ entry.description }}</p>
              <div class="entry-footer">
                <el-button
                  :type="entry.comingSoon ? 'info' : 'primary'"
                  size="small"
                  :disabled="entry.comingSoon"
                  @click="navigateTo(entry.route)"
                >
                  <el-icon v-if="!entry.comingSoon"><Promotion /></el-icon>
                  {{ entry.actionText }}
                </el-button>
              </div>
            </article>
          </template>
        </div>
      </div>
    </section>

    <!-- Right Sidebar Dock (unchanged) -->
    <aside class="launcher-dock">
      <section class="panel">
        <div class="panel-header dock-header">
          <h3 class="panel-title">在线任务</h3>
          <el-button text :loading="loading" @click="loadDockData">刷新</el-button>
        </div>
        <div class="panel-body dock-list">
          <button v-for="module in onlineModules" :key="module.id" type="button" class="dock-module" @click="openModule(module)">
            <span class="dock-module-icon"><el-icon><component :is="module.icon" /></el-icon></span>
            <span>
              <strong>{{ module.name }}</strong>
              <small>{{ module.statusText }}</small>
            </span>
          </button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">服务状态</h3>
        </div>
        <div class="panel-body">
          <div class="status-line">
            <div v-for="line in serviceStatusLines" :key="line" class="status-line-item">
              <el-icon><CircleCheck /></el-icon>
              <span>{{ line }}</span>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-header">
          <h3 class="panel-title">最近任务</h3>
        </div>
        <div class="panel-body recent-list">
          <button
            v-for="task in recentTasks"
            :key="task.task_id"
            type="button"
            class="recent-item"
            @click="$router.push(task.route)"
          >
            <span>
              <strong>{{ task.title }}</strong>
              <small>{{ task.module_name }} · {{ task.status_text }} · {{ formatDate(task.created_at) }}</small>
            </span>
            <el-icon><View /></el-icon>
          </button>
          <div v-if="!recentTasks.length" class="empty-inline">
            <el-icon><Clock /></el-icon>
            <span>暂无任务</span>
          </div>
        </div>
      </section>
    </aside>
  </div>
</template>

<style scoped>
.task-launcher {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 320px;
  gap: 16px;
  align-items: start;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

/* ---- Category Tabs ---- */
.category-tabs {
  margin-bottom: 4px;
}
.tab-label {
  display: flex;
  align-items: center;
  gap: 6px;
}

/* ---- Entry Card Grid ---- */
.entry-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
  gap: 14px;
  margin-top: 4px;
}

.entry-card {
  min-height: 200px;
  padding: 16px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  display: flex;
  flex-direction: column;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.entry-card:hover {
  border-color: #3b82f6;
  box-shadow: 0 2px 12px rgba(59, 130, 246, 0.1);
}
.entry-card-disabled {
  opacity: 0.6;
  cursor: default;
}
.entry-card-disabled:hover {
  border-color: var(--app-border-soft);
  box-shadow: none;
}

.entry-card-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 12px;
}
.entry-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: var(--app-radius-sm);
  background: var(--app-primary-light);
  color: var(--app-primary-active);
  flex-shrink: 0;
}
.entry-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  justify-content: flex-end;
}

.entry-name {
  margin: 0 0 8px;
  color: var(--app-ink);
  font-size: 16px;
  font-weight: 600;
}
.entry-desc {
  flex: 1;
  margin: 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
}
.entry-footer {
  margin-top: 12px;
  display: flex;
  justify-content: flex-end;
}

/* ---- Dock (unchanged) ---- */
.launcher-dock {
  display: flex;
  flex-direction: column;
  gap: 16px;
  position: sticky;
  top: 74px;
}

.dock-header {
  min-height: 58px;
}

.dock-list,
.recent-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.dock-module,
.recent-item {
  width: 100%;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  color: var(--app-ink);
  cursor: pointer;
  display: flex;
  align-items: center;
  text-align: left;
}

.dock-module {
  gap: 10px;
  min-height: 56px;
  padding: 8px 10px;
}

.dock-module-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: var(--app-radius-sm);
  background: var(--app-primary-light);
  color: var(--app-primary-active);
}

.dock-module strong,
.recent-item strong {
  display: block;
  font-size: 13px;
}

.recent-item span {
  min-width: 0;
}

.dock-module small,
.recent-item small {
  display: block;
  margin-top: 2px;
  color: var(--app-ink-muted);
  font-size: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.status-line {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.status-line-item {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--app-ink-body);
  font-weight: 600;
}

.status-line-item .el-icon {
  color: #16a34a;
}

.recent-item {
  justify-content: space-between;
  gap: 10px;
  min-height: 58px;
  padding: 8px 10px;
}

.empty-inline {
  min-height: 48px;
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--app-ink-muted);
  font-size: 13px;
}

@media (max-width: 1200px) {
  .task-launcher {
    grid-template-columns: 1fr;
  }

  .launcher-dock {
    position: static;
  }
}

@media (max-width: 640px) {
  .entry-grid {
    grid-template-columns: 1fr;
  }
}
</style>
