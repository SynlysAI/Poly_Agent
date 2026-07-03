<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { CircleCheck, Clock, Search, View } from '@element-plus/icons-vue'

import { getApiErrorMessage, getIntegrationStatus, listCampaigns, listComputations } from '../api/polyAgentApi'
import { TASK_CATEGORIES, TASK_MODULES, getTaskStatusTagType, mapCampaignToGlobalTask, mapComputationRunToGlobalTask } from '../tasks/taskModules'

const router = useRouter()
const keyword = ref('')
const category = ref('全部')
const recentTasks = ref([])
const integrations = ref([])
const loading = ref(false)

const filteredModules = computed(() => {
  const normalizedKeyword = keyword.value.trim().toLowerCase()
  return TASK_MODULES.filter((module) => {
    const matchesCategory = category.value === '全部' || module.category === category.value
    const haystack = `${module.name} ${module.category} ${module.description}`.toLowerCase()
    const matchesKeyword = !normalizedKeyword || haystack.includes(normalizedKeyword)
    return matchesCategory && matchesKeyword
  })
})

const onlineModules = computed(() => TASK_MODULES.filter((module) => module.status === 'online' || module.status === 'preview'))

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

function openModuleCenter(module) {
  if (module.routes?.center) {
    router.push(module.routes.center)
    return
  }
  ElMessage.info(`${module.name} 暂无可用任务中心`)
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
      ...(campaigns.items || []).map(mapCampaignToGlobalTask),
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
    <section class="panel task-catalog">
      <div class="panel-header launcher-header">
        <div>
          <h3 class="panel-title">任务提交</h3>
          <p class="panel-subtitle">选择要启动的任务类型。计算智能、湿实验优化和垂类预测都从这里进入。</p>
        </div>
      </div>
      <div class="panel-body">
        <div class="launcher-toolbar">
          <el-input v-model="keyword" class="launcher-search" clearable placeholder="搜索任务类型、模块或能力">
            <template #prefix><el-icon><Search /></el-icon></template>
          </el-input>
          <el-segmented v-model="category" :options="TASK_CATEGORIES" />
        </div>

        <div class="module-grid">
          <article v-for="module in filteredModules" :key="module.id" class="module-card">
            <div class="module-card-top">
              <div class="module-icon">
                <el-icon><component :is="module.icon" /></el-icon>
              </div>
              <el-tag size="small" :type="getTaskStatusTagType(module.status)">{{ module.statusText }}</el-tag>
            </div>
            <div class="module-category">{{ module.category }}</div>
            <h4>{{ module.name }}</h4>
            <p>{{ module.description }}</p>
            <div class="module-actions">
              <el-button type="primary" size="small" @click="openModule(module)">{{ module.primaryActionText }}</el-button>
              <el-button size="small" @click="openModuleCenter(module)">{{ module.centerActionText }}</el-button>
            </div>
          </article>
        </div>
      </div>
    </section>

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

.launcher-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.launcher-search {
  max-width: 360px;
}

.module-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
}

.module-card {
  min-height: 220px;
  padding: 14px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.module-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.module-icon,
.dock-module-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-sm);
  background: var(--app-primary-light);
  color: var(--app-primary-active);
}

.module-icon {
  width: 36px;
  height: 36px;
  font-size: 18px;
}

.module-category {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 600;
}

.module-card h4 {
  margin: 8px 0;
  color: var(--app-ink);
  font-size: 16px;
}

.module-card p {
  flex: 1;
  margin: 0;
  color: var(--app-ink-body);
  font-size: 13px;
  line-height: 1.6;
}

.module-actions {
  display: flex;
  gap: 8px;
  margin-top: 14px;
}

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
  width: 32px;
  height: 32px;
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

@media (max-width: 960px) {
  .module-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 640px) {
  .launcher-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .launcher-search {
    max-width: none;
  }

  .module-grid {
    grid-template-columns: 1fr;
  }
}
</style>
