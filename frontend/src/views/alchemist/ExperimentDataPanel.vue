<script setup>
import { onMounted, onActivated, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { addExperiment, getExperiments, getExperimentsSummary, getVariables } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const loading = ref(false)
const experiments = ref([])
const summary = ref({ has_data: false, n_experiments: 0 })
const variables = ref([])
const dialogVisible = ref(false)
const saving = ref(false)
const formData = ref({
  inputs: {},
  output: null,
  noise: 0,
  iteration: null,
  reason: 'Manual',
})

async function loadExperimentData() {
  try {
    loading.value = true
    const [listData, summaryData] = await Promise.all([
      getExperiments(props.sessionId),
      getExperimentsSummary(props.sessionId),
    ])
    experiments.value = listData.experiments || []
    summary.value = summaryData || { has_data: false, n_experiments: 0 }
  } catch (e) {
    experiments.value = []
    summary.value = { has_data: false, n_experiments: 0 }
    ElMessage.error(`加载实验数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) {
    variables.value = []
  }
}

function openAddDialog() {
  const inputs = {}
  variables.value.forEach(variable => {
    inputs[variable.name] = getDefaultValue(variable)
  })
  formData.value = {
    inputs,
    output: null,
    noise: 0,
    iteration: experiments.value.length,
    reason: 'Manual',
  }
  dialogVisible.value = true
}

async function handleSaveExperiment() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  if (!isFiniteNumber(formData.value.output)) {
    ElMessage.warning('Output 不能为空，且必须是有效数字')
    return
  }
  if (formData.value.noise !== null && formData.value.noise !== '' && !isFiniteNumber(formData.value.noise)) {
    ElMessage.warning('Noise 必须是有效数字')
    return
  }

  const inputs = {}
  for (const variable of variables.value) {
    const value = formData.value.inputs[variable.name]
    if (value === '' || value === null || value === undefined) {
      ElMessage.warning(`变量 ${variable.name} 不能为空`)
      return
    }
    inputs[variable.name] = normalizeInputValue(variable, value)
  }

  const payload = {
    inputs,
    output: Number(formData.value.output),
    reason: formData.value.reason || 'Manual',
  }
  if (formData.value.noise !== null && formData.value.noise !== '') {
    payload.noise = Number(formData.value.noise)
  }
  if (formData.value.iteration !== null && formData.value.iteration !== '') {
    payload.iteration = Number(formData.value.iteration)
  }

  try {
    saving.value = true
    await addExperiment(props.sessionId, payload)
    ElMessage.success('实验数据已添加')
    dialogVisible.value = false
    await loadExperimentData()
  } catch (e) {
    ElMessage.error(`添加实验数据失败: ${e.message}`)
  } finally {
    saving.value = false
  }
}

function getColumnNames() {
  if (experiments.value.length === 0) return []
  return Object.keys(experiments.value[0])
}

function formatCellValue(value) {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? value : Number(value.toFixed(6))
  }
  return value ?? '-'
}

function formatStatValue(value) {
  if (value === null || value === undefined) return '-'
  if (typeof value === 'number') return Number(value.toFixed(6))
  return value
}

function getDefaultValue(variable) {
  if (variable.type === 'categorical') {
    return (variable.categories || variable.values || [])[0] || ''
  }
  if (variable.type === 'discrete') {
    return (variable.allowed_values || variable.values || [])[0] ?? ''
  }
  return variable.min ?? variable.low ?? 0
}

function getVariableOptions(variable) {
  return variable.categories || variable.allowed_values || variable.values || []
}

function normalizeInputValue(variable, value) {
  if (variable.type === 'real') return Number(value)
  if (variable.type === 'integer') return Number.parseInt(value, 10)
  if (variable.type === 'discrete') return Number(value)
  return value
}

function isFiniteNumber(value) {
  if (value === '' || value === null || value === undefined) return false
  return Number.isFinite(Number(value))
}

watch(() => props.sessionId, () => {
  experiments.value = []
  variables.value = []
  loadVariables()
  loadExperimentData()
})

onMounted(() => {
  loadVariables()
  loadExperimentData()
})

onActivated(() => {
  if (props.sessionId) {
    loadExperimentData()
  }
})
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">实验数据</h3>
      <div style="display:flex;gap:8px">
        <el-button type="primary" size="small" @click="openAddDialog">新增实验数据</el-button>
        <el-button size="small" @click="loadExperimentData" :loading="loading">刷新</el-button>
      </div>
    </div>
    <div class="panel-body">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom:12px"
      >
        <template #title>
          这里显示已经带 Output 的真实实验数据；导出 Session 时保存的训练数据就是这部分。
        </template>
      </el-alert>

      <div class="summary-grid">
        <div class="summary-item">
          <span class="summary-label">实验数量</span>
          <strong>{{ summary.n_experiments || experiments.length || 0 }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">Output 最小值</span>
          <strong>{{ formatStatValue(summary.target_stats?.min) }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">Output 最大值</span>
          <strong>{{ formatStatValue(summary.target_stats?.max) }}</strong>
        </div>
        <div class="summary-item">
          <span class="summary-label">Output 均值</span>
          <strong>{{ formatStatValue(summary.target_stats?.mean) }}</strong>
        </div>
      </div>

      <el-table
        :data="experiments"
        border
        stripe
        empty-text="暂无实验数据，请先在实验设计页填写 Output 并添加为实验数据"
        max-height="520"
        v-loading="loading"
      >
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :label="col" min-width="110">
          <template #default="{ row }">
            {{ formatCellValue(row[col]) }}
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" title="新增实验数据" width="640px">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom:14px"
      >
        <template #title>
          填写一次已完成实验的变量条件和 Output。保存后这条数据会参与 GP 建模，并随 Session 导出。
        </template>
      </el-alert>

      <el-form label-width="110px">
        <el-form-item v-for="variable in variables" :key="variable.name" :label="variable.name">
          <el-select
            v-if="variable.type === 'categorical' || variable.type === 'discrete'"
            v-model="formData.inputs[variable.name]"
            style="width:100%"
          >
            <el-option
              v-for="option in getVariableOptions(variable)"
              :key="option"
              :label="String(option)"
              :value="option"
            />
          </el-select>
          <el-input-number
            v-else
            v-model="formData.inputs[variable.name]"
            :precision="variable.type === 'integer' ? 0 : undefined"
            style="width:100%"
          />
        </el-form-item>
        <el-form-item label="Output">
          <el-input-number v-model="formData.output" :controls="false" style="width:100%" />
        </el-form-item>
        <el-form-item label="Noise">
          <el-input-number v-model="formData.noise" :controls="false" style="width:100%" />
        </el-form-item>
        <el-form-item label="Iteration">
          <el-input-number v-model="formData.iteration" :min="0" :precision="0" style="width:100%" />
        </el-form-item>
        <el-form-item label="Reason">
          <el-input v-model="formData.reason" placeholder="Manual / Initial design / Acquisition" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSaveExperiment" :loading="saving">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(120px, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}

.summary-item {
  border: 1px solid var(--app-hairline);
  border-radius: 7px;
  background: var(--app-stat-bg);
  padding: 10px 12px;
}

.summary-label {
  color: var(--app-ink-muted);
  display: block;
  font-size: 12px;
  margin-bottom: 4px;
}

.summary-item strong {
  color: var(--app-ink);
  font-size: 16px;
}

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(120px, 1fr));
  }
}
</style>
