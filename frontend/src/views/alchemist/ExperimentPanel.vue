<script setup>
import { ref, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  addExperiment,
  generateInitialDesign,
  getExperiments,
  getExperimentsSummary,
  getVariables,
} from '../../api/alchemistApi'
import { suggestExperiments } from '../../api/polyAgentApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const designMethods = [
  { label: '拉丁超立方采样 (LHS)', value: 'lhs' },
  { label: 'Sobol 序列', value: 'sobol' },
  { label: '随机采样', value: 'random' },
  { label: 'Halton 序列', value: 'halton' },
  { label: 'Hammersly 序列', value: 'hammersly' },
  { label: '全因子设计', value: 'full_factorial' },
  { label: '部分因子设计', value: 'fractional_factorial' },
  { label: '中心复合设计 (CCD)', value: 'ccd' },
  { label: 'Box-Behnken 设计', value: 'box_behnken' },
  { label: 'Plackett-Burman 设计', value: 'plackett_burman' },
  { label: '广义子集设计 (GSD)', value: 'gsd' },
]

const selectedMethod = ref('lhs')
const nExperiments = ref(10)
const loading = ref(false)
const designMatrix = ref([])
const variables = ref([])
const experimentOutputs = ref([])
const experimentNoises = ref([])
const experimentSummary = ref({ has_data: false, n_experiments: 0 })

async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) { /* 静默失败 */ }
}

async function loadExperimentSummary() {
  try {
    experimentSummary.value = await getExperimentsSummary(props.sessionId)
  } catch (e) {
    experimentSummary.value = { has_data: false, n_experiments: 0 }
  }
}

async function handleGenerateDesign() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    loading.value = true
    const config = { method: selectedMethod.value }
    if (needsPointCount()) {
      config.n_points = nExperiments.value
    }
    const data = await generateInitialDesign(props.sessionId, config)
    designMatrix.value = data.points || data.design_matrix || data.experiments || []
    experimentOutputs.value = designMatrix.value.map(() => '')
    experimentNoises.value = designMatrix.value.map(() => '')
    ElMessage.success(`生成 ${designMatrix.value.length} 组实验方案`)
  } catch (e) {
    ElMessage.error(`生成实验设计失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleAddMeasuredExperiments() {
  if (designMatrix.value.length === 0) {
    ElMessage.warning('请先生成实验设计方案')
    return
  }

  const invalidIndex = experimentOutputs.value.findIndex(value => !isFiniteNumber(value))
  if (invalidIndex >= 0) {
    ElMessage.warning(`第 ${invalidIndex + 1} 行输出值为空或不是有效数字`)
    return
  }

  const invalidNoiseIndex = experimentNoises.value.findIndex(value => value !== '' && !isFiniteNumber(value))
  if (invalidNoiseIndex >= 0) {
    ElMessage.warning(`第 ${invalidNoiseIndex + 1} 行噪声值不是有效数字`)
    return
  }

  try {
    loading.value = true
    const startIteration = experimentSummary.value.n_experiments || 0
    const reason = `${getSelectedMethodLabel()} 初始设计`
    const experiments = designMatrix.value.map((row, index) => {
      const payload = {
        inputs: { ...row },
        output: Number(experimentOutputs.value[index]),
        iteration: startIteration + index,
        reason,
      }
      if (experimentNoises.value[index] !== '') {
        payload.noise = Number(experimentNoises.value[index])
      }
      return payload
    })

    for (const experiment of experiments) {
      await addExperiment(props.sessionId, experiment)
    }
    await loadExperimentSummary()
    ElMessage.success(`已添加 ${experiments.length} 条实验数据，Reason 已记录为"${reason}"`)
  } catch (e) {
    ElMessage.error(`添加实验数据失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

/** LLM 建议相关状态 */
const llmLoading = ref(false)
const llmSuggestions = ref([])
const llmReasoning = ref('')

/** 调用 LLM 辅助生成实验建议。 */
async function handleLlmSuggest() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    llmLoading.value = true
    llmSuggestions.value = []
    llmReasoning.value = ''
    // 获取完整实验数据
    let experiments = []
    try {
      const expData = await getExperiments(props.sessionId)
      experiments = expData.experiments || []
    } catch { /* 无实验数据则传空 */ }
    const data = await suggestExperiments({
      variables: variables.value,
      experiments: experiments,
      n_suggestions: 3,
    })
    if (data.suggestions && data.suggestions.length > 0) {
      designMatrix.value = data.suggestions
      experimentOutputs.value = data.suggestions.map(() => '')
      experimentNoises.value = data.suggestions.map(() => '')
      ElMessage.success(`LLM 建议了 ${data.suggestions.length} 组实验条件`)
    }
    llmSuggestions.value = data.suggestions || []
    llmReasoning.value = data.reasoning || ''
  } catch (e) {
    ElMessage.error(`LLM 建议失败: ${e.message}`)
  } finally {
    llmLoading.value = false
  }
}

/** 判断当前设计方法是否需要手动指定实验点数量。 */
function needsPointCount() {
  return ['random', 'lhs', 'sobol', 'halton', 'hammersly'].includes(selectedMethod.value)
}

/** 判断输入值是否为有限数字。 */
function isFiniteNumber(value) {
  if (value === '' || value === null || value === undefined) return false
  return Number.isFinite(Number(value))
}

function getColumnNames() {
  if (designMatrix.value.length === 0) return []
  const row = designMatrix.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) {
    return Object.keys(row)
  }
  return variables.value.map(v => v.name)
}

function getSelectedMethodLabel() {
  const found = designMethods.find(method => method.value === selectedMethod.value)
  return found ? found.label : selectedMethod.value
}

watch(() => props.sessionId, () => {
  designMatrix.value = []
  experimentOutputs.value = []
  experimentNoises.value = []
  loadVariables()
  loadExperimentSummary()
})

onMounted(() => {
  loadVariables()
  loadExperimentSummary()
})
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">实验设计</h3></div>
    <div class="panel-body">
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">设计方法</div>
          <el-select v-model="selectedMethod" style="width:220px">
            <el-option v-for="m in designMethods" :key="m.value" :label="m.label" :value="m.value" />
          </el-select>
        </div>
        <div v-if="needsPointCount()">
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">实验数量</div>
          <el-input-number v-model="nExperiments" :min="2" :max="1000" style="width:120px" />
        </div>
        <div>
          <el-button type="primary" @click="handleGenerateDesign" :loading="loading">生成实验设计</el-button>
          <el-button type="success" @click="handleAddMeasuredExperiments" :disabled="designMatrix.length === 0" :loading="loading">添加为实验数据</el-button>
          <el-button @click="handleLlmSuggest" :loading="llmLoading" type="warning" plain>LLM 建议</el-button>
        </div>
      </div>

      <el-alert v-if="llmReasoning" type="success" :closable="true" show-icon style="margin-bottom:12px">
        <template #title>LLM 建议理由：{{ llmReasoning }}</template>
      </el-alert>

      <el-alert
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom:12px"
      >
        <template #title>
          当前真实实验数据 {{ experimentSummary.n_experiments || 0 }} 条；GP 建模至少需要 5 条带输出值的实验数据。
        </template>
      </el-alert>

      <el-table :data="designMatrix" border stripe empty-text="请先生成实验设计方案" max-height="400">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
        <el-table-column label="输出值 Output" min-width="150">
          <template #default="{ $index }">
            <el-input-number
              v-model="experimentOutputs[$index]"
              :controls="false"
              placeholder="必填"
              style="width: 100%"
            />
          </template>
        </el-table-column>
        <el-table-column label="噪声 Noise" min-width="140">
          <template #default="{ $index }">
            <el-input-number
              v-model="experimentNoises[$index]"
              :controls="false"
              placeholder="可选"
              style="width: 100%"
            />
          </template>
        </el-table-column>
      </el-table>

    </div>
  </div>
</template>
