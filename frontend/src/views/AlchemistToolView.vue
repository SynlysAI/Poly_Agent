<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { createSession, deleteSession, importSession, exportSession, listSessions } from '../api/alchemistApi'
import VariablePanel from './alchemist/VariablePanel.vue'
import ExperimentPanel from './alchemist/ExperimentPanel.vue'
import ExperimentDataPanel from './alchemist/ExperimentDataPanel.vue'
import ModelPanel from './alchemist/ModelPanel.vue'
import AcquisitionPanel from './alchemist/AcquisitionPanel.vue'
import VisualizationPanel from './alchemist/VisualizationPanel.vue'

/** 当前步骤索引（0-5） */
const activeStep = ref(0)

/** 当前选中的 Session ID */
const currentSessionId = ref(null)

/** Session 加载状态 */
const loading = ref(false)

/** 步骤列表 */
const steps = [
  { title: '变量定义', description: '定义搜索空间中的变量' },
  { title: '实验设计', description: '生成初始实验方案' },
  { title: '实验数据', description: '管理带输出值的数据' },
  { title: 'GP 建模', description: '训练高斯过程代理模型' },
  { title: '采集优化', description: '贝叶斯优化采集函数' },
  { title: '可视化', description: '模型诊断与结果展示' },
]

/** 当前步骤对应的组件 */
const currentPanelComponent = computed(() => {
  const panels = [VariablePanel, ExperimentPanel, ExperimentDataPanel, ModelPanel, AcquisitionPanel, VisualizationPanel]
  return panels[activeStep.value]
})

/** 服务端已有的 Session 列表 */
const sessions = ref([])

/** 新建 Session 对话框 */
const createDialogVisible = ref(false)
const createForm = ref({ name: '', description: '', tags: '' })

/** 加载服务端 Session 列表 */
async function loadSessions() {
  try {
    const data = await listSessions()
    sessions.value = Array.isArray(data) ? data : []
  } catch (e) {
    sessions.value = []
  }
}

/** 打开新建 Session 对话框 */
function openCreateDialog() {
  createForm.value = { name: '', description: '', tags: '' }
  createDialogVisible.value = true
}

/** 确认新建 Session */
async function handleCreateSession() {
  try {
    loading.value = true
    const payload = {}
    if (createForm.value.name.trim()) payload.name = createForm.value.name.trim()
    if (createForm.value.description.trim()) payload.description = createForm.value.description.trim()
    if (createForm.value.tags.trim()) {
      payload.tags = createForm.value.tags.split(/[,，]/).map(s => s.trim()).filter(Boolean)
    }
    const data = await createSession(payload)
    currentSessionId.value = data.session_id
    createDialogVisible.value = false
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
      const data = await importSession(file)
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

/** 删除当前 Session */
async function handleDeleteSession() {
  if (!currentSessionId.value) {
    ElMessage.warning('请先选择一个 Session')
    return
  }
  try {
    await ElMessageBox.confirm(
      `确定要永久删除 Session ${currentSessionId.value.slice(0, 8)} 及其所有数据吗？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '确认删除', cancelButtonText: '取消' }
    )
    await deleteSession(currentSessionId.value)
    currentSessionId.value = null
    await loadSessions()
    ElMessage.success('Session 已删除')
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(`删除 Session 失败: ${e.message}`)
    }
  }
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
    a.download = `alchemist_session_${currentSessionId.value.slice(0, 8)}.json`
    a.click()
    URL.revokeObjectURL(url)
    ElMessage.success('Session 导出成功')
  } catch (e) {
    ElMessage.error(`Session 导出失败: ${e.message}`)
  }
}

onMounted(() => {
  loadSessions()
})
</script>

<template>
  <div class="alchemist-tool">
    <!-- Session 管理栏 -->
    <div class="panel session-toolbar">
      <div class="session-info">
        <span class="session-label">当前 Session</span>
        <el-select
          v-model="currentSessionId"
          placeholder="请选择或新建 Session"
          style="width:280px"
          filterable
          clearable
        >
          <el-option
            v-for="s in sessions"
            :key="s.session_id"
            :label="s.name || s.session_id"
            :value="s.session_id"
          />
        </el-select>
      </div>
      <div class="session-actions">
        <el-button type="primary" @click="openCreateDialog">新建</el-button>
        <el-button @click="handleImportSession">导入</el-button>
        <el-button @click="handleExportSession" :disabled="!currentSessionId">导出</el-button>
        <el-button @click="handleDeleteSession" :disabled="!currentSessionId" type="danger" plain>删除</el-button>
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
          <p style="color:var(--app-ink-muted);font-size:15px">请先创建或选择一个 Session 以开始使用实验设计与优化工具</p>
        </div>
        <div v-else>
          <keep-alive>
            <component :is="currentPanelComponent" :session-id="currentSessionId" :key="`${currentSessionId}-${activeStep}`" />
          </keep-alive>
        </div>
      </div>
    </div>

    <!-- 新建 Session 弹窗 -->
    <el-dialog v-model="createDialogVisible" title="新建 Session" width="480px">
      <el-form label-width="80px">
        <el-form-item label="名称">
          <el-input v-model="createForm.name" placeholder="例如：催化剂筛选实验" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="createForm.description" type="textarea" :rows="2" placeholder="可选，简要描述本次优化目标" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="createForm.tags" placeholder="可选，逗号分隔，如：催化剂, CO2还原" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="createDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleCreateSession" :loading="loading">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.session-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
  padding: 12px 16px;
}

.session-info {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.session-label {
  color: var(--app-ink);
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
}

.session-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.session-actions :deep(.el-button) {
  min-width: 72px;
  height: 34px;
  margin-left: 0;
  padding: 0 15px;
  font-size: 14px;
  font-weight: 600;
}

.session-actions :deep(.el-button--primary) {
  box-shadow: 0 6px 14px rgba(45, 108, 223, 0.22);
}

@media (max-width: 720px) {
  .session-toolbar {
    align-items: flex-start;
    flex-direction: column;
  }

  .session-actions {
    justify-content: flex-start;
  }
}

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
