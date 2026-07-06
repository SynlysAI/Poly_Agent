<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, View as ViewIcon } from '@element-plus/icons-vue'

import {
  createProblemSpec,
  freezeProblemSpec,
  getApiErrorMessage,
  getProblemSpec,
  listAlgorithms,
  listProblemSpecs,
  updateProblemSpec,
} from '../../api/polyAgentApi'

const emit = defineEmits(['spec-selected'])

const loading = ref(false)
const saving = ref(false)
const specs = ref([])
const selectedSpecId = ref('')
const detail = ref(null)
const algorithms = ref([])
const jsonPreviewVisible = ref(false)

// 新模式还是编辑模式
const isNew = ref(false)
const isViewing = ref(false)

const form = ref({
  name: '',
  material_family: 'fluoropolymer',
  problem_type: 'formulation_process_optimization',
  execution_mode: 'hybrid',
  variables: [],
  objectives: [{ name: '', direction: 'maximize', unit: '', weight: 1.0, description: '' }],
  constraints: [],
  measurements: [],
  campaign_id: null,
  description: '',
})

const materialFamilyOptions = [
  { label: '氟基高分子', value: 'fluoropolymer' },
  { label: '碳基高分子', value: 'carbon_polymer' },
  { label: '硅基高分子', value: 'silicon_polymer' },
  { label: '含氟-碳共聚体系', value: 'fluoro_carbon_copolymer' },
  { label: '通用', value: 'universal' },
]

const problemTypeOptions = [
  { label: '配方/工艺优化', value: 'formulation_process_optimization' },
  { label: '结构-性质预测', value: 'structure_property_prediction' },
  { label: '材料发现', value: 'material_discovery' },
  { label: '反应条件优化', value: 'reaction_condition_optimization' },
]

const executionModeOptions = [
  { label: '人工通道', value: 'manual' },
  { label: '自动编排', value: 'autoresearch' },
  { label: '双通道并行', value: 'hybrid' },
]

const variableTypeOptions = [
  { label: '连续', value: 'continuous' },
  { label: '分类', value: 'categorical' },
  { label: '离散', value: 'discrete' },
  { label: '组成', value: 'composition' },
]

const variableRoleOptions = [
  { label: '结构', value: 'structure' },
  { label: '工艺', value: 'process' },
  { label: '配方', value: 'formulation' },
  { label: '测量', value: 'measurement' },
]

const canFreeze = computed(() => detail.value?.status === 'draft')
const canEdit = computed(() => !detail.value || detail.value.status === 'draft')

function addVariable() {
  form.value.variables.push({ name: '', type: 'continuous', role: 'structure', unit: '', bounds: [0, 1], categories: null, description: '' })
}

function removeVariable(index) {
  form.value.variables.splice(index, 1)
}

function addObjective() {
  form.value.objectives.push({ name: '', direction: 'maximize', unit: '', weight: 1.0, description: '' })
}

function removeObjective(index) {
  form.value.objectives.splice(index, 1)
}

function addConstraint() {
  form.value.constraints.push({ name: '', type: 'hard', expression: '', description: '' })
}

function removeConstraint(index) {
  form.value.constraints.splice(index, 1)
}

function addMeasurement() {
  form.value.measurements.push({ name: '', condition: '', method: '' })
}

function removeMeasurement(index) {
  form.value.measurements.splice(index, 1)
}

async function loadSpecs() {
  loading.value = true
  try {
    const data = await listProblemSpecs({ page: 1, page_size: 50 })
    specs.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function loadAlgorithms() {
  try {
    const data = await listAlgorithms({ page: 1, page_size: 100 })
    algorithms.value = data.items || []
  } catch {
    algorithms.value = []
  }
}

function selectSpec(specId) {
  if (specId === '__new__') {
    isNew.value = true
    isViewing.value = false
    detail.value = null
    selectedSpecId.value = ''
    form.value = {
      name: '',
      material_family: 'fluoropolymer',
      problem_type: 'formulation_process_optimization',
      execution_mode: 'hybrid',
      variables: [],
      objectives: [{ name: '', direction: 'maximize', unit: '', weight: 1.0, description: '' }],
      constraints: [],
      measurements: [],
      campaign_id: null,
      description: '',
    }
    return
  }
  isNew.value = false
  isViewing.value = false
  selectedSpecId.value = specId
  loadSpecDetail(specId)
}

async function loadSpecDetail(specId) {
  loading.value = true
  try {
    detail.value = await getProblemSpec(specId)
    form.value = {
      name: detail.value.name,
      material_family: detail.value.material_family,
      problem_type: detail.value.problem_type,
      execution_mode: detail.value.execution_mode,
      variables: JSON.parse(JSON.stringify(detail.value.variables || [])),
      objectives: JSON.parse(JSON.stringify(detail.value.objectives || [])),
      constraints: JSON.parse(JSON.stringify(detail.value.constraints || [])),
      measurements: JSON.parse(JSON.stringify(detail.value.measurements || [])),
      campaign_id: detail.value.campaign_id,
      description: detail.value.description || '',
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    const payload = {
      ...form.value,
      objectives: form.value.objectives.filter(o => o.name.trim()),
    }
    if (isNew.value) {
      const data = await createProblemSpec(payload)
      detail.value = data
      isNew.value = false
      selectedSpecId.value = data.problem_spec_id
      emit('spec-selected', data)
      ElMessage.success('研发任务创建成功')
      await loadSpecs()
    } else {
      const data = await updateProblemSpec(detail.value.problem_spec_id, payload)
      detail.value = data
      emit('spec-selected', data)
      ElMessage.success('研发任务已更新')
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    saving.value = false
  }
}

async function handleFreeze() {
  try {
    await ElMessageBox.confirm('冻结后不可直接修改，只能复制为新版本后编辑。确定冻结？', '冻结确认', {
      confirmButtonText: '冻结',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const data = await freezeProblemSpec(detail.value.problem_spec_id)
    detail.value = data
    ElMessage.success('研发任务已冻结')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  }
}

function formatDate(value) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function statusTag(status) {
  const map = { draft: 'info', frozen: 'warning', active: 'success', archived: 'info' }
  return map[status] || 'info'
}

function materialFamilyLabel(value) {
  const found = materialFamilyOptions.find(o => o.value === value)
  return found?.label || value
}

loadSpecs()
loadAlgorithms()
</script>

<template>
  <div class="problem-spec-panel">
    <!-- 选择/新建 ProblemSpec -->
    <div class="spec-selector">
      <el-select
        v-model="selectedSpecId"
        placeholder="选择已有研发任务或新建"
        style="width: 360px"
        @change="selectSpec"
      >
        <el-option label="+ 新建研发任务" value="__new__" />
        <el-option
          v-for="spec in specs"
          :key="spec.problem_spec_id"
          :label="spec.name"
          :value="spec.problem_spec_id"
        >
          <span>{{ spec.name }}</span>
          <el-tag size="small" :type="statusTag(spec.status)" style="margin-left:8px">{{ spec.status }}</el-tag>
        </el-option>
      </el-select>
      <el-tag v-if="detail" :type="statusTag(detail.status)" size="small">
        {{ detail.status === 'draft' ? '草稿' : detail.status === 'frozen' ? '已冻结' : detail.status }}
      </el-tag>
    </div>

    <!-- ProblemSpec 表单 -->
    <div v-if="isNew || detail" class="spec-form" v-loading="loading">
      <el-form label-position="top">
        <div class="form-row">
          <el-form-item label="研发任务名称" style="flex:2">
            <el-input v-model="form.name" placeholder="例如：氟基高分子电解质优化" :disabled="!canEdit" />
          </el-form-item>
          <el-form-item label="材料体系" style="flex:1">
            <el-select v-model="form.material_family" :disabled="!canEdit">
              <el-option v-for="item in materialFamilyOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </div>
        <div class="form-row">
          <el-form-item label="问题类型" style="flex:1">
            <el-select v-model="form.problem_type" :disabled="!canEdit">
              <el-option v-for="item in problemTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="执行模式" style="flex:1">
            <el-select v-model="form.execution_mode" :disabled="!canEdit">
              <el-option v-for="item in executionModeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
        </div>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="2" placeholder="简要描述研发目标与背景" :disabled="!canEdit" />
        </el-form-item>

        <!-- 变量 -->
        <div class="section-label">
          <span>变量定义</span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addVariable">添加变量</el-button>
        </div>
        <div v-for="(v, idx) in form.variables" :key="'var-' + idx" class="inline-form-row">
          <el-input v-model="v.name" placeholder="变量名" style="width:140px" :disabled="!canEdit" />
          <el-select v-model="v.type" style="width:100px" :disabled="!canEdit">
            <el-option v-for="item in variableTypeOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-select v-model="v.role" style="width:90px" :disabled="!canEdit">
            <el-option v-for="item in variableRoleOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
          <el-input v-model="v.unit" placeholder="单位" style="width:80px" :disabled="!canEdit" />
          <el-input v-if="v.type === 'continuous'" v-model="v.bounds[0]" placeholder="min" style="width:70px" :disabled="!canEdit" />
          <el-input v-if="v.type === 'continuous'" v-model="v.bounds[1]" placeholder="max" style="width:70px" :disabled="!canEdit" />
          <el-input v-model="v.description" placeholder="描述（可选）" style="flex:1" :disabled="!canEdit" />
          <el-button v-if="canEdit" text type="danger" size="small" :icon="Delete" @click="removeVariable(idx)" />
        </div>

        <!-- 目标 -->
        <div class="section-label">
          <span>优化目标</span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addObjective">添加目标</el-button>
        </div>
        <div v-for="(obj, idx) in form.objectives" :key="'obj-' + idx" class="inline-form-row">
          <el-input v-model="obj.name" placeholder="目标名" style="width:140px" :disabled="!canEdit" />
          <el-select v-model="obj.direction" style="width:110px" :disabled="!canEdit">
            <el-option label="最大化" value="maximize" />
            <el-option label="最小化" value="minimize" />
          </el-select>
          <el-input v-model="obj.unit" placeholder="单位" style="width:80px" :disabled="!canEdit" />
          <el-input-number v-model="obj.weight" :min="0" :max="10" :step="0.1" style="width:90px" :disabled="!canEdit" />
          <el-input v-model="obj.description" placeholder="描述（可选）" style="flex:1" :disabled="!canEdit" />
          <el-button v-if="canEdit && form.objectives.length > 1" text type="danger" size="small" :icon="Delete" @click="removeObjective(idx)" />
        </div>

        <!-- 约束 -->
        <div class="section-label">
          <span>约束条件</span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addConstraint">添加约束</el-button>
        </div>
        <div v-for="(c, idx) in form.constraints" :key="'c-' + idx" class="inline-form-row">
          <el-input v-model="c.name" placeholder="约束名" style="width:140px" :disabled="!canEdit" />
          <el-select v-model="c.type" style="width:100px" :disabled="!canEdit">
            <el-option label="硬约束" value="hard" />
            <el-option label="软约束" value="soft" />
          </el-select>
          <el-input v-model="c.expression" placeholder="表达式" style="flex:1" :disabled="!canEdit" />
          <el-button v-if="canEdit" text type="danger" size="small" :icon="Delete" @click="removeConstraint(idx)" />
        </div>

        <!-- 测量条件 -->
        <div class="section-label">
          <span>测量条件</span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addMeasurement">添加测量</el-button>
        </div>
        <div v-for="(m, idx) in form.measurements" :key="'m-' + idx" class="inline-form-row">
          <el-input v-model="m.name" placeholder="测量项名" style="width:140px" :disabled="!canEdit" />
          <el-input v-model="m.condition" placeholder="条件" style="width:160px" :disabled="!canEdit" />
          <el-input v-model="m.method" placeholder="方法" style="flex:1" :disabled="!canEdit" />
          <el-button v-if="canEdit" text type="danger" size="small" :icon="Delete" @click="removeMeasurement(idx)" />
        </div>

        <!-- 操作按钮 -->
        <div class="form-actions">
          <el-button v-if="canEdit" type="primary" :loading="saving" @click="handleSave">
            {{ isNew ? '创建草稿' : '保存修改' }}
          </el-button>
          <el-button v-if="canFreeze" type="warning" @click="handleFreeze">冻结规格</el-button>
          <el-button :icon="ViewIcon" @click="jsonPreviewVisible = true">JSON 预览</el-button>
        </div>
      </el-form>

      <!-- 详情信息 -->
      <el-descriptions v-if="detail && !isNew" :column="3" border size="small" style="margin-top:16px">
        <el-descriptions-item label="ID">{{ detail.problem_spec_id }}</el-descriptions-item>
        <el-descriptions-item label="版本">{{ detail.schema_version }}</el-descriptions-item>
        <el-descriptions-item label="创建者">{{ detail.created_by }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ formatDate(detail.created_at) }}</el-descriptions-item>
        <el-descriptions-item label="更新时间">{{ formatDate(detail.updated_at) }}</el-descriptions-item>
        <el-descriptions-item label="冻结版本">{{ detail.frozen_version }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- JSON 预览 dialog -->
    <el-drawer v-model="jsonPreviewVisible" title="ProblemSpec JSON 预览" size="520px">
      <pre class="json-preview">{{ JSON.stringify(detail || form, null, 2) }}</pre>
    </el-drawer>
  </div>
</template>

<style scoped>
.problem-spec-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.spec-selector {
  display: flex;
  align-items: center;
  gap: 12px;
}

.spec-form {
  min-height: 200px;
}

.form-row {
  display: flex;
  gap: 16px;
}

.section-label {
  margin: 16px 0 8px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid var(--app-border-soft);
  padding-bottom: 6px;
  font-weight: 600;
  font-size: 14px;
  color: var(--app-ink);
}

.inline-form-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}

.form-actions {
  display: flex;
  gap: 10px;
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid var(--app-border-soft);
}

.json-preview {
  margin: 0;
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: calc(100vh - 100px);
  overflow: auto;
}
</style>
