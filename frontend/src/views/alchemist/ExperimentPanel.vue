<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import {
  addExperiment,
  generateInitialDesign,
  getExperiments,
  getExperimentsSummary,
  getVariables,
} from '../../api/alchemistApi'
import { suggestExperiments } from '../../api/polyAgentApi'
import OptimalDesignPanel from './OptimalDesignPanel.vue'

const props = defineProps({
  sessionId: { type: String, required: true }
})

// ── Tab 切换 ──
const activeTab = ref('doe')

// ── DoE 方法配置 ──
const designMethods = [
  {
    label: '拉丁超立方采样 (LHS)',
    value: 'lhs',
    category: 'space_filling',
    desc: '均匀覆盖各维度，最广泛使用的空间填充方法',
  },
  {
    label: '随机采样',
    value: 'random',
    category: 'space_filling',
    desc: '均匀随机采样，适合对搜索空间无先验知识的情况',
  },
  {
    label: 'Sobol 序列',
    value: 'sobol',
    category: 'space_filling',
    desc: 'Sobol 低差异序列，分布比随机采样更均匀',
  },
  {
    label: 'Halton 序列',
    value: 'halton',
    category: 'space_filling',
    desc: 'Halton 确定性准随机序列，计算简单',
  },
  {
    label: 'Hammersly 序列',
    value: 'hammersly',
    category: 'space_filling',
    desc: 'Hammersly 确定性准随机序列，与 Halton 类似',
  },
  {
    label: '全因子设计',
    value: 'full_factorial',
    category: 'classical',
    desc: '覆盖所有因子水平组合，实验量随因子数快速增长',
  },
  {
    label: '部分因子设计',
    value: 'fractional_factorial',
    category: 'classical',
    desc: '2 水平部分因子筛选设计，大幅减少实验量。不支持分类变量',
    categorical_unsupported: true,
  },
  {
    label: '中心复合设计 (CCD)',
    value: 'ccd',
    category: 'classical',
    desc: '经典响应面方法，含中心点和轴向点。不支持分类变量',
    categorical_unsupported: true,
  },
  {
    label: 'Box-Behnken 设计',
    value: 'box_behnken',
    category: 'classical',
    desc: '响应面方法，避免极端因子组合。不支持分类变量',
    categorical_unsupported: true,
  },
  {
    label: 'Plackett-Burman 设计',
    value: 'plackett_burman',
    category: 'screening',
    desc: '超高效 2 水平筛选设计，仅连续变量',
    categorical_unsupported: true,
  },
  {
    label: '广义子集设计 (GSD)',
    value: 'gsd',
    category: 'screening',
    desc: '支持连续/分类/离散混合变量的高效筛选设计',
  },
]

const selectedMethod = ref('lhs')
const nExperiments = ref(10)
const randomSeed = ref(null)
const lhsCriterion = ref('maximin')
const nLevels = ref(2)
const nCenter = ref(1)
const generatorsInput = ref('')
const ccdAlpha = ref('orthogonal')
const ccdFace = ref('circumscribed')
const gsdReduction = ref(2)

const selectedMethodInfo = computed(() =>
  designMethods.find(m => m.value === selectedMethod.value) || designMethods[0]
)

/** 空间填充方法需要手动指定 n_points */
const needsPointCount = computed(() =>
  ['random', 'lhs', 'sobol', 'halton', 'hammersly'].includes(selectedMethod.value)
)

/** 全因子/GSD 有水平数参数 */
const needsNLevels = computed(() =>
  ['full_factorial', 'gsd'].includes(selectedMethod.value)
)

/** 经典 RSM 方法有中心点参数 */
const needsNCenter = computed(() =>
  ['full_factorial', 'fractional_factorial', 'ccd', 'box_behnken'].includes(selectedMethod.value)
)

/** 检查是否有分类变量不兼容 */
const hasCategoricalVariables = computed(() =>
  variables.value.some(v => v.type === 'categorical')
)

const showCategoricalWarning = computed(() =>
  selectedMethodInfo.value.categorical_unsupported && hasCategoricalVariables.value
)

// ── 状态 ──
const loading = ref(false)
const designMatrix = ref([])
const variables = ref([])
const experimentOutputs = ref([])
const experimentNoises = ref([])
const experimentSummary = ref({ has_data: false, n_experiments: 0 })

// ── 数据加载 ──
async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch { /* 静默失败 */ }
}

async function loadExperimentSummary() {
  try {
    experimentSummary.value = await getExperimentsSummary(props.sessionId)
  } catch {
    experimentSummary.value = { has_data: false, n_experiments: 0 }
  }
}

// ── 生成初始设计 ──
async function handleGenerateDesign() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  if (showCategoricalWarning.value) {
    ElMessage.warning(`${selectedMethodInfo.value.label} 不支持分类变量，请改用支持混合变量的方法（如 GSD、LHS、全因子设计）`)
    return
  }
  try {
    loading.value = true
    const config = { method: selectedMethod.value }
    if (needsPointCount.value) {
      config.n_points = nExperiments.value
    }
    if (selectedMethod.value === 'lhs') {
      config.lhs_criterion = lhsCriterion.value
    }
    if (['random', 'lhs', 'sobol', 'halton', 'hammersly'].includes(selectedMethod.value)) {
      if (randomSeed.value != null) config.random_seed = randomSeed.value
    }
    if (needsNLevels.value) {
      config.n_levels = nLevels.value
    }
    if (needsNCenter.value) {
      config.n_center = nCenter.value
    }
    if (selectedMethod.value === 'fractional_factorial' && generatorsInput.value.trim()) {
      config.generators = generatorsInput.value.trim()
    }
    if (selectedMethod.value === 'ccd') {
      config.ccd_alpha = ccdAlpha.value
      config.ccd_face = ccdFace.value
    }
    if (selectedMethod.value === 'gsd') {
      config.gsd_reduction = gsdReduction.value
    }

    const data = await generateInitialDesign(props.sessionId, config)
    designMatrix.value = data.points || data.design_matrix || data.experiments || []
    experimentOutputs.value = designMatrix.value.map(() => '')
    experimentNoises.value = designMatrix.value.map(() => '')
    const infoMsg = data.design_info
      ? ` (${data.design_info.structure || data.n_points} 点)`
      : ''
    ElMessage.success(`生成 ${designMatrix.value.length} 组实验方案${infoMsg}`)
  } catch (e) {
    ElMessage.error(`生成实验设计失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

// ── 添加实验数据 ──
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

// ── LLM 建议 ──
const llmLoading = ref(false)
const llmReasoning = ref('')

async function handleLlmSuggest() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    llmLoading.value = true
    llmReasoning.value = ''
    let experiments = []
    try {
      const expData = await getExperiments(props.sessionId)
      experiments = expData.experiments || []
    } catch { /* 无实验数据则传空 */ }
    const data = await suggestExperiments({
      variables: variables.value,
      experiments,
      n_suggestions: 3,
    })
    if (data.suggestions && data.suggestions.length > 0) {
      designMatrix.value = data.suggestions
      experimentOutputs.value = data.suggestions.map(() => '')
      experimentNoises.value = data.suggestions.map(() => '')
      ElMessage.success(`LLM 建议了 ${data.suggestions.length} 组实验条件`)
    }
    llmReasoning.value = data.reasoning || ''
  } catch (e) {
    ElMessage.error(`LLM 建议失败: ${e.message}`)
  } finally {
    llmLoading.value = false
  }
}

// ── 工具函数 ──
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

// ── 分类变量不兼容提示 ──
const incompatibleMethods = computed(() =>
  designMethods
    .filter(m => m.categorical_unsupported)
    .map(m => m.label)
    .join('、')
)

// ── 生命周期 ──
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
    <div class="panel-header">
      <h3 class="panel-title">实验设计</h3>
    </div>
    <div class="panel-body">
      <!-- Tab 切换 -->
      <el-tabs v-model="activeTab" style="margin-bottom:12px">
        <el-tab-pane label="初始设计" name="doe" />
        <el-tab-pane label="最优设计" name="oed" />
      </el-tabs>

      <!-- 初始设计 (DoE) -->
      <div v-if="activeTab === 'doe'">
        <!-- 设计方法 + 参数 -->
        <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:12px;flex-wrap:wrap">
          <div>
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">设计方法</div>
            <el-select v-model="selectedMethod" style="width:240px">
              <el-option-group v-for="group in [
                { label: '空间填充方法', methods: designMethods.filter(m => m.category === 'space_filling') },
                { label: '经典 RSM 方法', methods: designMethods.filter(m => m.category === 'classical') },
                { label: '筛选方法', methods: designMethods.filter(m => m.category === 'screening') },
              ]" :key="group.label" :label="group.label">
                <el-option
                  v-for="m in group.methods"
                  :key="m.value"
                  :label="m.label"
                  :value="m.value"
                />
              </el-option-group>
            </el-select>
            <div style="font-size:11px;color:var(--app-ink-muted);margin-top:4px;max-width:240px">
              {{ selectedMethodInfo.desc }}
            </div>
          </div>

          <!-- 点数量（空间填充方法） -->
          <div v-if="needsPointCount">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">实验数量</div>
            <el-input-number v-model="nExperiments" :min="2" :max="1000" style="width:120px" />
          </div>

          <!-- LHS 准则 -->
          <div v-if="selectedMethod === 'lhs'">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">LHS 准则</div>
            <el-select v-model="lhsCriterion" style="width:130px">
              <el-option label="Maximin" value="maximin" />
              <el-option label="Correlation" value="correlation" />
              <el-option label="Ratio" value="ratio" />
            </el-select>
          </div>

          <!-- 随机种子 -->
          <div v-if="['random', 'lhs', 'sobol', 'halton', 'hammersly'].includes(selectedMethod)">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">随机种子</div>
            <el-input-number v-model="randomSeed" :min="0" placeholder="可选" style="width:120px" />
          </div>

          <!-- 每因子水平数（全因子/GSD） -->
          <div v-if="needsNLevels">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">
              {{ selectedMethod === 'gsd' ? '每因子水平数' : '水平数' }}
            </div>
            <el-input-number
              v-model="nLevels"
              :min="2"
              :max="selectedMethod === 'gsd' ? 5 : 3"
              style="width:100px"
            />
          </div>

          <!-- 中心点数量（经典RSM方法） -->
          <div v-if="needsNCenter">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">中心点重复</div>
            <el-input-number v-model="nCenter" :min="0" :max="10" style="width:100px" />
          </div>

          <!-- 生成器（部分因子设计） -->
          <div v-if="selectedMethod === 'fractional_factorial'">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">生成器字符串</div>
            <el-input v-model="generatorsInput" placeholder="如 a b ab" style="width:140px" />
          </div>

          <!-- CCD Alpha -->
          <div v-if="selectedMethod === 'ccd'">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">Alpha 类型</div>
            <el-select v-model="ccdAlpha" style="width:130px">
              <el-option label="正交 (Orthogonal)" value="orthogonal" />
              <el-option label="可旋转 (Rotatable)" value="rotatable" />
            </el-select>
          </div>

          <!-- CCD Face -->
          <div v-if="selectedMethod === 'ccd'">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">面类型</div>
            <el-select v-model="ccdFace" style="width:150px">
              <el-option label="外接 (Circumscribed)" value="circumscribed" />
              <el-option label="内接 (Inscribed)" value="inscribed" />
              <el-option label="面心 (Faced)" value="faced" />
            </el-select>
          </div>

          <!-- GSD 缩减因子 -->
          <div v-if="selectedMethod === 'gsd'">
            <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">缩减因子</div>
            <el-select v-model="gsdReduction" style="width:100px">
              <el-option v-for="r in [2,3,4,5]" :key="r" :label="String(r)" :value="r" />
            </el-select>
          </div>

          <div style="display:flex;gap:8px">
            <el-button type="primary" @click="handleGenerateDesign" :loading="loading">生成实验设计</el-button>
            <el-button type="success" @click="handleAddMeasuredExperiments" :disabled="designMatrix.length === 0" :loading="loading">添加为实验数据</el-button>
            <el-button @click="handleLlmSuggest" :loading="llmLoading" type="warning" plain>LLM 建议</el-button>
          </div>
        </div>

        <!-- 分类变量不兼容警告 -->
        <el-alert
          v-if="showCategoricalWarning"
          type="warning"
          :closable="true"
          show-icon
          style="margin-bottom:12px"
        >
          <template #title>
            {{ selectedMethodInfo.label }} 不支持分类变量。当前搜索空间包含分类变量，请改用支持混合变量的方法，如 GSD、LHS、Sobol 序列或全因子设计。
          </template>
        </el-alert>

        <!-- 分类变量提示（不兼容方法之外） -->
        <el-alert
          v-if="hasCategoricalVariables && !showCategoricalWarning"
          type="info"
          :closable="false"
          show-icon
          style="margin-bottom:12px"
        >
          <template #title>
            注意：以下方法不支持分类变量：{{ incompatibleMethods }}。
          </template>
        </el-alert>

        <!-- LLM 建议理由 -->
        <el-alert v-if="llmReasoning" type="success" :closable="true" show-icon style="margin-bottom:12px">
          <template #title>LLM 建议理由：{{ llmReasoning }}</template>
        </el-alert>

        <!-- 实验数据摘要 -->
        <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px">
          <template #title>
            当前真实实验数据 {{ experimentSummary.n_experiments || 0 }} 条；GP 建模至少需要 5 条带输出值的实验数据。
          </template>
        </el-alert>

        <!-- 设计矩阵表格 -->
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

      <!-- 最优设计 (OED) -->
      <div v-if="activeTab === 'oed'">
        <OptimalDesignPanel :session-id="sessionId" :key="sessionId" />
      </div>
    </div>
  </div>
</template>
