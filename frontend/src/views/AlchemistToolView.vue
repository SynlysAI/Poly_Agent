<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Setting } from '@element-plus/icons-vue'
import { listSessions, createSession, uploadSession, exportSession } from '../api/alchemistApi'
import VariablePanel from './alchemist/VariablePanel.vue'
import ExperimentPanel from './alchemist/ExperimentPanel.vue'
import ModelPanel from './alchemist/ModelPanel.vue'
import AcquisitionPanel from './alchemist/AcquisitionPanel.vue'
import VisualizationPanel from './alchemist/VisualizationPanel.vue'
import LlmConfigDialog from './alchemist/components/LlmConfigDialog.vue'

/** 当前步骤索引（0-4） */
const activeStep = ref(0)

/** Session 列表 */
const sessions = ref([])

/** 当前选中的 Session ID */
const currentSessionId = ref(null)

/** Session 加载状态 */
const loading = ref(false)

/** LLM 配置弹窗 */
const llmDialogVisible = ref(false)

/** 步骤列表 */
const steps = [
  { title: '变量定义', description: '定义搜索空间中的变量' },
  { title: '实验设计', description: '生成初始实验方案' },
  { title: 'GP 建模', description: '训练高斯过程代理模型' },
  { title: '采集优化', description: '贝叶斯优化采集函数' },
  { title: '可视化', description: '模型诊断与结果展示' },
]

/** 当前 Session 名称 */
const currentSessionName = computed(() => {
  if (!currentSessionId.value) return '未选择'
  const s = sessions.value.find(s => s.session_id === currentSessionId.value)
  return s ? (s.name || s.session_id) : currentSessionId.value
})

/** 当前步骤对应的组件 */
const currentPanelComponent = computed(() => {
  const panels = [VariablePanel, ExperimentPanel, ModelPanel, AcquisitionPanel, VisualizationPanel]
  return panels[activeStep.value]
})

/** 加载 Session 列表 */
async function loadSessions() {
  try {
    const data = await listSessions()
    sessions.value = Array.isArray(data) ? data : []
  } catch (e) {
    ElMessage.error(`加载 Session 列表失败: ${e.message}`)
  }
}

/** 新建 Session */
async function handleCreateSession() {
  try {
    loading.value = true
    const data = await createSession()
    currentSessionId.value = data.session_id
    await loadSessions()
    ElMessage.success('Session 创建成功')
  } catch (e) {
    ElMessage.error(`创建 Session 失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** 导入 Session 文件 */
async function handleImportSession() {
  const input = document.createElement('input')
  input.type = 'file'
  input.accept = '.json'
  input.onchange = async (e) => {
    const file = e.target.files[0]
    if (!file) return
    try {
      loading.value = true
      const data = await uploadSession(file)
      currentSessionId.value = data.session_id
      await loadSessions()
      ElMessage.success('Session 导入成功')
    } catch (e) {
      ElMessage.error(`Session 导入失败: ${e.message}`)
    } finally {
      loading.value = false
    }
  }
  input.click()
}

/** 导出当前 Session */
async function handleExportSession() {
  if (!currentSessionId.value) {
    ElMessage.warning('请先选择一个 Session')
    return
  }
  try {
    const blob = await exportSession(currentSessionId.value)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `session_${currentSessionId.value}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Session 导出成功')
  } catch (e) {
    ElMessage.error(`Session 导出失败: ${e.message}`)
  }
}

/** 切换 Session */
function handleSessionChange(sessionId) {
  currentSessionId.value = sessionId
}

onMounted(() => {
  loadSessions()
})
</script>

<template>
  <div class="alchemist-tool">
    <!-- Session 管理栏 -->
    <div class="panel" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px">
        <span style="font-weight:600;font-size:14px;color:var(--app-ink);white-space:nowrap">当前 Session：</span>
        <el-select
          v-model="currentSessionId"
          placeholder="请选择或创建 Session"
          style="flex:1;max-width:400px"
          @change="handleSessionChange"
        >
          <el-option
            v-for="s in sessions"
            :key="s.session_id"
            :label="s.name || s.session_id"
            :value="s.session_id"
          />
        </el-select>
        <el-button type="primary" size="small" @click="handleCreateSession" :loading="loading">新建</el-button>
        <el-button size="small" @click="handleImportSession">导入</el-button>
        <el-button size="small" @click="handleExportSession" :disabled="!currentSessionId">导出</el-button>
        <el-button size="small" @click="llmDialogVisible = true">
          <el-icon style="margin-right:4px"><Setting /></el-icon>
          LLM 配置
        </el-button>
      </div>
    </div>

    <!-- 步骤导航 + 内容区 -->
    <div style="display:flex;gap:16px">
      <!-- 左侧步骤导航 -->
      <div class="panel" style="width:200px;flex-shrink:0">
        <div class="panel-header">
          <h3 class="panel-title">优化流程</h3>
        </div>
        <div class="panel-body" style="padding:8px">
          <div
            v-for="(step, index) in steps"
            :key="index"
            class="step-item"
            :class="{ active: activeStep === index }"
            @click="activeStep = index"
          >
            <div class="step-index">{{ index + 1 }}</div>
            <div class="step-content">
              <div class="step-title">{{ step.title }}</div>
              <div class="step-desc">{{ step.description }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 右侧内容区 -->
      <div style="flex:1;min-width:0">
        <div v-if="!currentSessionId" class="panel" style="padding:60px;text-align:center">
          <p style="color:var(--app-ink-muted);font-size:15px">请先创建或选择一个 Session 以开始使用主动学习优化工具</p>
        </div>
        <div v-else>
          <component :is="currentPanelComponent" :session-id="currentSessionId" :key="`${activeStep}-${currentSessionId}`" />
        </div>
      </div>
    </div>

    <!-- LLM 配置弹窗 -->
    <LlmConfigDialog v-model:visible="llmDialogVisible" />
  </div>
</template>

<style scoped>
.step-item {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 10px 8px;
  border-radius: var(--app-radius-md);
  cursor: pointer;
  transition: background 0.15s;
  margin-bottom: 2px;
}

.step-item:hover {
  background: var(--app-stat-bg);
}

.step-item.active {
  background: var(--app-primary-light);
}

.step-index {
  width: 24px;
  height: 24px;
  border-radius: 50%;
  background: var(--app-hairline);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
  color: var(--app-ink-muted);
  flex-shrink: 0;
}

.step-item.active .step-index {
  background: var(--app-primary);
  color: #fff;
}

.step-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--app-ink);
  line-height: 1.3;
}

.step-desc {
  font-size: 11px;
  color: var(--app-ink-muted);
  margin-top: 2px;
}
</style>
