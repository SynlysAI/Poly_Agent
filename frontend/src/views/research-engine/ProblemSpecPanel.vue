<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Plus, View as ViewIcon, InfoFilled, ArrowDown } from '@element-plus/icons-vue'

import {
  archiveProblemSpec,
  createProblemSpec,
  freezeProblemSpec,
  getApiErrorMessage,
  getProblemSpec,
  listAlgorithms,
  listProblemSpecs,
  updateProblemSpec,
} from '../../api/polyAgentApi'

const emit = defineEmits(['spec-selected'])

const props = defineProps({
  currentProblemSpecId: { type: String, default: '' },
})

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

function createEmptyForm() {
  return {
    name: '',
    material_family: 'fluoropolymer',
    problem_type: 'formulation_process_optimization',
    allowed_execution_modes: ['manual_workbench', 'autoresearch'],
    decision_status: 'pending_execution_decision',
    variables: [],
    objectives: [{ name: '', direction: 'maximize', unit: '', weight: 1.0, description: '' }],
    constraints: [],
    measurements: [],
    campaign_id: null,
    description: '',
  }
}

const form = ref(createEmptyForm())

const executionModeOptions = [
  { label: '人工算法工作台', value: 'manual_workbench' },
  { label: 'AutoResearch 自动编排', value: 'autoresearch' },
]

const decisionStatusOptions = [
  { label: '待选择执行路径', value: 'pending_execution_decision' },
  { label: '已选择执行路径', value: 'decision_made' },
]

const decisionStatusLabelMap = {
  pending_execution_decision: '待选择执行路径',
  decision_made: '已选择执行路径',
}

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

// ------ 快速模板 ------
const SPEC_TEMPLATES = [
  {
    label: '氟基高分子电解质优化',
    data: {
      material_family: 'fluoropolymer',
      problem_type: 'formulation_process_optimization',
      allowed_execution_modes: ['manual_workbench', 'autoresearch'],
      variables: [
        { name: 'fluorine_content', type: 'continuous', role: 'formulation', unit: 'wt%', bounds: [20, 60], categories: null, description: '氟含量' },
        { name: 'curing_temp', type: 'continuous', role: 'process', unit: '°C', bounds: [100, 250], categories: null, description: '固化温度' },
        { name: 'film_thickness', type: 'continuous', role: 'structure', unit: 'μm', bounds: [10, 100], categories: null, description: '膜厚' },
      ],
      objectives: [
        { name: 'ionic_conductivity', direction: 'maximize', unit: 'S/cm', weight: 1.0, description: '离子电导率' },
        { name: 'mechanical_strength', direction: 'maximize', unit: 'MPa', weight: 0.5, description: '机械强度' },
      ],
      constraints: [
        { name: 'cost_limit', type: 'hard', expression: 'fluorine_content * 2 + curing_temp * 0.5 < 400', description: '综合成本约束' },
      ],
      measurements: [
        { name: 'Ionic Conductivity', condition: '25°C, 100% RH', method: 'EIS 阻抗谱' },
        { name: 'Tensile Strength', condition: '23°C, 50% RH, 50mm/min', method: '万能试验机' },
      ],
      description: '优化氟基高分子电解质的离子电导率与机械强度，控制成本在合理范围内。',
    },
  },
  {
    label: '碳基复合材料力学优化',
    data: {
      material_family: 'carbon_polymer',
      problem_type: 'structure_property_prediction',
      allowed_execution_modes: ['manual_workbench'],
      variables: [
        { name: 'fiber_content', type: 'continuous', role: 'formulation', unit: 'vol%', bounds: [10, 40], categories: null, description: '纤维含量' },
        { name: 'molding_pressure', type: 'continuous', role: 'process', unit: 'MPa', bounds: [5, 30], categories: null, description: '成型压力' },
      ],
      objectives: [
        { name: 'tensile_modulus', direction: 'maximize', unit: 'GPa', weight: 1.0, description: '拉伸模量' },
        { name: 'density', direction: 'minimize', unit: 'g/cm³', weight: 0.3, description: '密度' },
      ],
      constraints: [
        { name: 'min_strength', type: 'hard', expression: 'tensile_modulus > 50', description: '最低模量要求' },
      ],
      measurements: [
        { name: 'Tensile Modulus', condition: '23°C, 标准大气压', method: 'ASTM D638' },
      ],
      description: '优化碳纤维增强复合材料的拉伸模量，同时轻量化。',
    },
  },
  {
    label: '硅基聚合物热稳定性优化',
    data: {
      material_family: 'silicon_polymer',
      problem_type: 'formulation_process_optimization',
      allowed_execution_modes: ['manual_workbench', 'autoresearch'],
      variables: [
        { name: 'siloxane_ratio', type: 'continuous', role: 'formulation', unit: 'mol%', bounds: [30, 70], categories: null, description: '硅氧烷比例' },
        { name: 'crosslinker_content', type: 'continuous', role: 'formulation', unit: 'wt%', bounds: [0.5, 5], categories: null, description: '交联剂含量' },
        { name: 'cure_time', type: 'continuous', role: 'process', unit: 'h', bounds: [1, 24], categories: null, description: '固化时间' },
      ],
      objectives: [
        { name: 'tga_onset', direction: 'maximize', unit: '°C', weight: 1.0, description: '热分解起始温度' },
      ],
      constraints: [
        { name: 'tg_range', type: 'hard', expression: 'tga_onset > 300 AND tga_onset < 500', description: '分解温度合理范围' },
      ],
      measurements: [
        { name: 'TGA Decomposition', condition: 'N2 氛围, 10°C/min', method: 'TGA' },
        { name: 'DSC Tg', condition: 'N2 氛围, 10°C/min', method: 'DSC' },
      ],
      description: '提高硅基聚合物热稳定性，同时保持加工性。',
    },
  },
  {
    label: '氟碳共聚物配方优化',
    data: {
      material_family: 'fluoro_carbon_copolymer',
      problem_type: 'material_discovery',
      allowed_execution_modes: ['autoresearch'],
      variables: [
        { name: 'F_monomer_ratio', type: 'continuous', role: 'formulation', unit: 'mol%', bounds: [10, 80], categories: null, description: '含氟单体比例' },
        { name: 'initiator_conc', type: 'continuous', role: 'formulation', unit: 'ppm', bounds: [100, 1000], categories: null, description: '引发剂浓度' },
        { name: 'temp', type: 'discrete', role: 'process', unit: '°C', bounds: [60, 200], categories: null, description: '反应温度' },
      ],
      objectives: [
        { name: 'water_contact_angle', direction: 'maximize', unit: '°', weight: 1.0, description: '疏水性（水接触角）' },
        { name: 'dielectric_constant', direction: 'minimize', unit: '', weight: 0.8, description: '介电常数' },
      ],
      constraints: [],
      measurements: [
        { name: 'Contact Angle', condition: '23°C, 去离子水', method: '接触角仪' },
        { name: 'Dielectric Constant', condition: '1kHz, 23°C', method: '阻抗分析仪' },
      ],
      description: '发现新型氟碳共聚物配方，平衡疏水性与介电性能。',
    },
  },
]

function applyTemplate(template) {
  const t = template.data
  form.value.material_family = t.material_family
  form.value.problem_type = t.problem_type
  form.value.allowed_execution_modes = [...t.allowed_execution_modes]
  form.value.decision_status = 'pending_execution_decision'
  form.value.variables = JSON.parse(JSON.stringify(t.variables))
  form.value.objectives = JSON.parse(JSON.stringify(t.objectives))
  form.value.constraints = JSON.parse(JSON.stringify(t.constraints))
  form.value.measurements = JSON.parse(JSON.stringify(t.measurements))
  form.value.description = t.description || ''
  ElMessage.success(`已应用模板: ${template.label}`)
}

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
    form.value = createEmptyForm()
    return
  }
  isNew.value = false
  isViewing.value = false
  selectedSpecId.value = specId
  loadSpecDetail(specId, 'select')
}

async function loadSpecDetail(specId, source = 'select') {
  loading.value = true
  try {
    detail.value = await getProblemSpec(specId)
    form.value = {
      name: detail.value.name,
      material_family: detail.value.material_family,
      problem_type: detail.value.problem_type,
      allowed_execution_modes: [...(detail.value.allowed_execution_modes || ['manual_workbench', 'autoresearch'])],
      decision_status: detail.value.decision_status || 'pending_execution_decision',
      variables: JSON.parse(JSON.stringify(detail.value.variables || [])),
      objectives: JSON.parse(JSON.stringify(detail.value.objectives || [])),
      constraints: JSON.parse(JSON.stringify(detail.value.constraints || [])),
      measurements: JSON.parse(JSON.stringify(detail.value.measurements || [])),
      campaign_id: detail.value.campaign_id,
      description: detail.value.description || '',
    }
    emit('spec-selected', detail.value, { source })
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

watch(
  () => props.currentProblemSpecId,
  (specId) => {
    if (!specId || specId === selectedSpecId.value) return
    isNew.value = false
    isViewing.value = false
    selectedSpecId.value = specId
    loadSpecDetail(specId, 'restore')
  },
  { immediate: true },
)

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
    emit('spec-selected', data, { source: 'freeze' })
    ElMessage.success('研发任务已冻结')
  } catch (error) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(getApiErrorMessage(error))
  }
}

async function handleArchiveSpec(spec) {
  try {
    await ElMessageBox.confirm(`确定要归档研发任务「${spec.name}」吗？归档后默认历史列表将不再显示，但追溯记录会保留。`, '归档确认', {
      confirmButtonText: '归档',
      cancelButtonText: '取消',
      type: 'warning',
    })
    await archiveProblemSpec(spec.problem_spec_id, { reason: '用户从研发任务历史列表归档' })
    ElMessage.success('研发任务已归档')
    if (selectedSpecId.value === spec.problem_spec_id) {
      selectedSpecId.value = ''
      detail.value = null
      form.value = createEmptyForm()
      emit('spec-selected', null, { source: 'archive' })
    }
    await loadSpecs()
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

function decisionStatusLabel(value) {
  return decisionStatusLabelMap[value] || value || '-'
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
          <span class="option-row">
            <span class="option-main">
              <span>{{ spec.name }}</span>
              <el-tag size="small" :type="statusTag(spec.status)" style="margin-left:8px">{{ spec.status }}</el-tag>
            </span>
            <el-button
              text
              type="danger"
              size="small"
              :icon="Delete"
              aria-label="归档研发任务"
              @click.stop="handleArchiveSpec(spec)"
            />
          </span>
        </el-option>
      </el-select>
      <el-tag v-if="detail" :type="statusTag(detail.status)" size="small">
        {{ detail.status === 'draft' ? '草稿' : detail.status === 'frozen' ? '已冻结' : detail.status }}
      </el-tag>
      <!-- 快速模板 -->
      <el-dropdown v-if="canEdit" trigger="click" @command="applyTemplate">
        <el-button size="small" type="warning" plain>
          快速模板 <el-icon style="margin-left:4px"><ArrowDown /></el-icon>
        </el-button>
        <template #dropdown>
          <el-dropdown-menu>
            <el-dropdown-item
              v-for="tpl in SPEC_TEMPLATES"
              :key="tpl.label"
              :command="tpl"
            >
              {{ tpl.label }}
            </el-dropdown-item>
          </el-dropdown-menu>
        </template>
      </el-dropdown>
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
          <el-form-item label="允许执行路径" style="flex:1">
            <el-select v-model="form.allowed_execution_modes" multiple :disabled="!canEdit">
              <el-option v-for="item in executionModeOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="决策状态" style="flex:1">
            <el-select v-model="form.decision_status" :disabled="!canEdit">
              <el-option v-for="item in decisionStatusOptions" :key="item.value" :label="item.label" :value="item.value" />
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
          <span>约束条件 <el-tag size="small" type="info" effect="plain">可选</el-tag></span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addConstraint">添加约束</el-button>
        </div>
        <!-- 空态引导 -->
        <div v-if="!form.constraints.length" class="empty-section-hint">
          <div class="empty-hint-header">
            <el-icon><InfoFilled /></el-icon>
            <span>尚未定义约束条件。如果不添加约束，优化将在变量的边界范围内自由搜索。</span>
          </div>
          <div class="empty-hint-examples">
            <p class="empty-hint-label">硬约束表达式范例：</p>
            <ul>
              <li><code>temperature &lt; 300 AND temperature &gt; 20</code> — 温度范围约束</li>
              <li><code>fluorine_content &gt; 0.3</code> — 氟含量下限</li>
              <li><code>concentration &gt;= 0.1 AND concentration &lt;= 0.5</code> — 浓度范围</li>
              <li><code>molecular_weight BETWEEN 10000 AND 50000</code> — 分子量范围</li>
              <li><code>cost_per_kg &lt; 50</code> — 成本约束</li>
            </ul>
            <p class="empty-hint-syntax">支持的运算符：<code>&lt; &gt; &lt;= &gt;= == != AND OR BETWEEN...AND IN [...]</code></p>
          </div>
          <p class="empty-hint-action">点击上方"添加约束"按钮开始定义约束条件。</p>
        </div>
        <div v-for="(c, idx) in form.constraints" :key="'c-' + idx" class="inline-form-row">
          <el-input v-model="c.name" placeholder="约束名" style="width:140px" :disabled="!canEdit" />
          <el-select v-model="c.type" style="width:100px" :disabled="!canEdit">
            <el-option label="硬约束" value="hard" />
            <el-option label="软约束" value="soft" />
          </el-select>
          <el-input v-model="c.expression" placeholder="表达式，如 temperature < 300" style="flex:1" :disabled="!canEdit" />
          <el-input v-model="c.description" placeholder="描述（可选）" style="width:140px" :disabled="!canEdit" />
          <el-button v-if="canEdit" text type="danger" size="small" :icon="Delete" @click="removeConstraint(idx)" />
        </div>

        <!-- 测量条件 -->
        <div class="section-label">
          <span>测量条件 <el-tag size="small" type="info" effect="plain">可选</el-tag></span>
          <el-button v-if="canEdit" text type="primary" size="small" :icon="Plus" @click="addMeasurement">添加测量</el-button>
        </div>
        <!-- 空态引导 -->
        <div v-if="!form.measurements.length" class="empty-section-hint">
          <div class="empty-hint-header">
            <el-icon><InfoFilled /></el-icon>
            <span>尚未定义测量条件。如果不填测量条件，算法将仅基于目标函数值进行优化，不区分测量场景。填写测量条件可帮助算法区分不同测试环境下的表现。</span>
          </div>
          <div class="empty-hint-examples">
            <p class="empty-hint-label">测量条件范例：</p>
            <ul>
              <li><code>DSC 测量 Tg</code> / 条件: 升温速率 10°C/min, N₂ 氛围 / 方法: DSC</li>
              <li><code>拉伸强度</code> / 条件: 23°C, 50% RH, 50mm/min / 方法: 万能试验机 (ASTM D638)</li>
              <li><code>介电常数</code> / 条件: 1kHz, 23°C / 方法: 阻抗分析仪</li>
              <li><code>TGA 热分解温度</code> / 条件: N₂, 10°C/min / 方法: TGA</li>
            </ul>
          </div>
          <p class="empty-hint-action">点击上方"添加测量"按钮开始定义测量条件。</p>
        </div>
        <div v-for="(m, idx) in form.measurements" :key="'m-' + idx" class="inline-form-row">
          <el-input v-model="m.name" placeholder="测量项名" style="width:140px" :disabled="!canEdit" />
          <el-input v-model="m.condition" placeholder="条件，如 23°C, 50% RH" style="width:180px" :disabled="!canEdit" />
          <el-input v-model="m.method" placeholder="方法，如 DSC / 万能试验机" style="flex:1" :disabled="!canEdit" />
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
        <el-descriptions-item label="决策状态">{{ decisionStatusLabel(detail.decision_status) }}</el-descriptions-item>
        <el-descriptions-item label="允许执行路径">{{ (detail.allowed_execution_modes || []).join(', ') }}</el-descriptions-item>
      </el-descriptions>
    </div>

    <!-- JSON 预览 dialog -->
    <el-drawer v-model="jsonPreviewVisible" title="ProblemSpec JSON 预览" size="520px">
      <pre class="json-preview">{{ JSON.stringify(detail || form, null, 2) }}</pre>
    </el-drawer>
  </div>
</template>

<style scoped>
.option-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  width: 100%;
}

.option-main {
  min-width: 0;
  display: flex;
  align-items: center;
}

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

/* ---- 空态引导 ---- */
.empty-section-hint {
  background: rgba(59, 130, 246, 0.04);
  border: 1px dashed rgba(59, 130, 246, 0.25);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 8px;
}
.empty-hint-header {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 13px;
  color: var(--app-ink-body);
  line-height: 1.6;
  margin-bottom: 10px;
}
.empty-hint-header .el-icon {
  color: #3b82f6;
  flex-shrink: 0;
  margin-top: 2px;
}
.empty-hint-examples {
  background: rgba(255,255,255,0.04);
  border-radius: 6px;
  padding: 10px 14px;
  margin-bottom: 8px;
}
.empty-hint-label {
  margin: 0 0 6px;
  font-weight: 600;
  font-size: 13px;
  color: var(--app-ink);
}
.empty-hint-examples ul {
  margin: 0;
  padding-left: 18px;
}
.empty-hint-examples li {
  font-size: 13px;
  color: var(--app-ink-body);
  line-height: 1.8;
}
.empty-hint-examples code {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
  padding: 1px 6px;
  border-radius: 3px;
  font-family: var(--app-mono-font);
  font-size: 12px;
}
.empty-hint-syntax {
  margin: 8px 0 0;
  font-size: 12px;
  color: var(--app-ink-muted);
}
.empty-hint-syntax code {
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
  padding: 1px 4px;
  border-radius: 3px;
  font-family: var(--app-mono-font);
  font-size: 11px;
}
.empty-hint-action {
  margin: 0;
  font-size: 12px;
  color: var(--app-ink-muted);
  font-style: italic;
}
</style>
