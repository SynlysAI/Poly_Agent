<script setup>
import { onMounted, onActivated, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { UploadFilled } from '@element-plus/icons-vue'
import {
  addExperiment,
  getExperiments,
  getExperimentsSummary,
  getVariables,
  previewCSV,
  uploadCSV,
} from '../../api/alchemistApi'

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

// ── CSV 导入 ──
const csvImportVisible = ref(false)
const csvPreviewData = ref(null)
const csvTargetColumn = ref('Output')
const csvImporting = ref(false)
const csvFileRef = ref(null)

function openCsvImport() {
  csvTargetColumn.value = 'Output'
  csvPreviewData.value = null
  csvImportVisible.value = true
}

/** 选择文件后自动预览 */
async function handleCsvFileSelected(event) {
  const file = event.target.files[0]
  if (!file) return
  try {
    const data = await previewCSV(props.sessionId, file)
    csvPreviewData.value = { ...data, _file: file }
    if (!data.has_output && data.recommended_target) {
      csvTargetColumn.value = data.recommended_target
    }
  } catch (e) {
    ElMessage.error(`CSV 预览失败: ${e.message}`)
    csvPreviewData.value = null
  }
}

/** 确认导入 */
async function handleCsvUpload() {
  if (!csvPreviewData.value || !csvPreviewData.value._file) {
    ElMessage.warning('请先选择 CSV 文件')
    return
  }
  const fileName = csvPreviewData.value._file.name
  const nRows = csvPreviewData.value.n_rows || '?'

  try {
    csvImporting.value = true
    const data = await uploadCSV(props.sessionId, csvPreviewData.value._file, csvTargetColumn.value)
    ElMessage.success(`已从 CSV 导入 ${data.n_experiments} 条实验数据（文件: ${fileName}，${nRows} 行）`)
    csvImportVisible.value = false
    csvPreviewData.value = null
    await loadExperimentData()
    // 清空 file input 以便同一文件可重新选择
    if (csvFileRef.value) csvFileRef.value.value = ''
  } catch (e) {
    ElMessage.error(`CSV 导入失败: ${e.message}`)
  } finally {
    csvImporting.value = false
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
        <el-button size="small" @click="openCsvImport">
          <el-icon><UploadFilled /></el-icon>
          导入 CSV
        </el-button>
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

    <!-- CSV 导入对话框 -->
    <el-dialog v-model="csvImportVisible" title="从 CSV 导入实验数据" width="560px">
      <div v-if="!csvPreviewData">
        <div style="text-align:center;padding:20px">
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:12px">
            CSV 应包含与变量名称匹配的列，加上目标列（如 "Output"）和可选的 "Noise" 列。
          </div>
          <input
            ref="csvFileRef"
            type="file"
            accept=".csv"
            style="display:none"
            @change="handleCsvFileSelected"
          />
          <el-button type="primary" @click="() => csvFileRef && csvFileRef.click()">
            <el-icon><UploadFilled /></el-icon>
            选择 CSV 文件
          </el-button>
        </div>
      </div>

      <div v-else>
        <el-descriptions border :column="2" size="small" style="margin-bottom:16px">
          <el-descriptions-item label="文件名">{{ csvPreviewData._file.name }}</el-descriptions-item>
          <el-descriptions-item label="数据行数">{{ csvPreviewData.n_rows }}</el-descriptions-item>
          <el-descriptions-item label="CSV 列">
            <span style="font-size:12px">{{ (csvPreviewData.columns || []).join(', ') }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="Output 列">
            <el-tag v-if="csvPreviewData.has_output" type="success" size="small">已存在</el-tag>
            <span v-else style="color:#dc2626;font-size:12px">未找到</span>
          </el-descriptions-item>
        </el-descriptions>

        <div v-if="!csvPreviewData.has_output" style="margin-bottom:12px">
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:6px">
            CSV 中没有 "Output" 列，请选择作为目标值的列：
          </div>
          <el-select v-model="csvTargetColumn" style="width:100%">
            <el-option
              v-for="col in (csvPreviewData.available_targets || csvPreviewData.columns || [])"
              :key="col"
              :label="col"
              :value="col"
            />
          </el-select>
        </div>

        <div style="text-align:right;margin-top:8px">
          <el-button @click="csvPreviewData = null; csvTargetColumn = 'Output'">重新选择</el-button>
          <el-button type="primary" @click="handleCsvUpload" :loading="csvImporting">
            确认导入
          </el-button>
        </div>
      </div>
    </el-dialog>

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
