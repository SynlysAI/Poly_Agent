<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { InfoFilled, MagicStick } from '@element-plus/icons-vue'
import {
  getOptimalDesignInfo,
  generateOptimalDesign,
  getVariables,
  stageExperiments,
  getExperimentsSummary,
  llmSuggestEffectsSSE,
} from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

// ── 模型规格 ──
const modelType = ref('linear')
const modelTypeOptions = [
  { label: '线性 (Linear)', value: 'linear', desc: '仅包含主效应，适用于初步筛选' },
  { label: '交互 (Interaction)', value: 'interaction', desc: '主效应 + 两两交互项' },
  { label: '二次 (Quadratic)', value: 'quadratic', desc: '主效应 + 交互 + 平方项，适用于响应面建模' },
  { label: '自定义', value: 'custom', desc: '手动选择效应项' },
]

// 自定义效应复选框状态
const customMainEffects = ref({})
const customInteractions = ref({})
const customQuadratic = ref({})
const customExtraEffects = ref('')

// 从变量列表生成效应项
const variables = ref([])
async function loadVariables() {
  try {
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
    // 初始化复选框
    for (const v of variables.value) {
      if (!(v.name in customMainEffects.value)) customMainEffects.value[v.name] = true
      if (!(v.name in customQuadratic.value)) customQuadratic.value[v.name] = false
    }
    // 初始化交互项
    for (let i = 0; i < variables.value.length; i++) {
      for (let j = i + 1; j < variables.value.length; j++) {
        const key = `${variables.value[i].name}*${variables.value[j].name}`
        if (!(key in customInteractions.value)) customInteractions.value[key] = false
      }
    }
  } catch { /* 静默失败 */ }
}

// 计算当前的 effects 列表
const currentEffects = computed(() => {
  if (modelType.value !== 'custom') return []
  const effects = []
  for (const v of variables.value) {
    if (customMainEffects.value[v.name]) effects.push(v.name)
  }
  for (const key of Object.keys(customInteractions.value)) {
    if (customInteractions.value[key]) effects.push(key)
  }
  for (const v of variables.value) {
    if (customQuadratic.value[v.name]) effects.push(`${v.name}**2`)
  }
  if (customExtraEffects.value.trim()) {
    effects.push(...customExtraEffects.value.split(',').map(s => s.trim()).filter(Boolean))
  }
  return effects
})

function toggleAllMainEffects() {
  const allOn = variables.value.every(v => customMainEffects.value[v.name])
  for (const v of variables.value) customMainEffects.value[v.name] = !allOn
}

function toggleAllInteractions() {
  const keys = Object.keys(customInteractions.value)
  const allOn = keys.length > 0 && keys.every(k => customInteractions.value[k])
  for (const k of keys) customInteractions.value[k] = !allOn
}

function toggleAllQuadratic() {
  const allOn = variables.value.every(v => customQuadratic.value[v.name])
  for (const v of variables.value) customQuadratic.value[v.name] = !allOn
}

// ── 设计参数 ──
const criterion = ref('D')
const criterionOptions = [
  { label: 'D-optimal', value: 'D', desc: '最小化参数置信椭球体积，最常用' },
  { label: 'A-optimal', value: 'A', desc: '最小化参数估计的平均方差' },
  { label: 'I-optimal', value: 'I', desc: '最小化设计空间内的平均预测方差' },
]

const algorithm = ref('fedorov')
const algorithmOptions = [
  { label: 'Fedorov (推荐)', value: 'fedorov' },
  { label: 'Modified Fedorov', value: 'modified_fedorov' },
  { label: 'DetMax (最优)', value: 'detmax' },
  { label: 'Simple Exchange', value: 'simple_exchange' },
  { label: 'Sequential (最快)', value: 'sequential' },
]

const runMode = ref('multiplier')
const pMultiplier = ref(2.0)
const nPoints = ref(12)
const showAdvanced = ref(false)
const gridLevels = ref(5)
const maxIter = ref(200)
const randomSeed = ref(null)

// ── 状态 ──
const loading = ref(false)
const infoLoading = ref(false)
const designResult = ref(null)
const previewInfo = ref(null)

// ── 预览模型项 ──
async function handlePreview() {
  try {
    infoLoading.value = true
    previewInfo.value = null
    const config = {}
    if (modelType.value === 'custom') {
      if (currentEffects.value.length === 0) {
        ElMessage.warning('请至少选择一个效应项')
        return
      }
      config.effects = currentEffects.value
    } else {
      config.model_type = modelType.value
    }
    const data = await getOptimalDesignInfo(props.sessionId, config)
    previewInfo.value = data
  } catch (e) {
    ElMessage.error(`预览模型项失败: ${e.message}`)
  } finally {
    infoLoading.value = false
  }
}

// ── 生成最优设计 ──
async function handleGenerate() {
  if (variables.value.length === 0) {
    ElMessage.warning('请先在"变量定义"中添加变量')
    return
  }
  try {
    loading.value = true
    designResult.value = null
    const config = {
      criterion: criterion.value,
      algorithm: algorithm.value,
    }
    if (modelType.value === 'custom') {
      if (currentEffects.value.length === 0) {
        ElMessage.warning('请至少选择一个效应项')
        return
      }
      config.effects = currentEffects.value
    } else {
      config.model_type = modelType.value
    }
    if (runMode.value === 'multiplier') {
      config.p_multiplier = pMultiplier.value
    } else {
      config.n_points = nPoints.value
    }
    if (showAdvanced.value) {
      config.n_levels = gridLevels.value
      config.max_iter = maxIter.value
      if (randomSeed.value != null) config.random_seed = randomSeed.value
    }
    const data = await generateOptimalDesign(props.sessionId, config)
    designResult.value = data
    ElMessage.success(`生成 ${data.n_points} 组最优实验方案`)
  } catch (e) {
    ElMessage.error(`生成最优设计失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

// ── 暂存设计结果 ──
async function handleStageDesign() {
  if (!designResult.value || !designResult.value.points) return
  try {
    loading.value = true
    const reason = `最优设计 (${criterion.value}-optimal, ${algorithm.value})`
    await stageExperiments(props.sessionId, { experiments: designResult.value.points, reason })
    ElMessage.success('最优设计点已暂存到实验队列')
  } catch (e) {
    ElMessage.error(`暂存失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

// ── CSV 下载 ──
function handleDownloadCSV() {
  if (!designResult.value || !designResult.value.points) return
  const points = designResult.value.points
  const cols = Object.keys(points[0] || {})
  let csv = cols.join(',') + '\n'
  for (const row of points) {
    csv += cols.map(c => row[c]).join(',') + '\n'
  }
  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `optimal_design_${props.sessionId}.csv`
  a.click()
  URL.revokeObjectURL(url)
}

// ── 获取设计矩阵列名 ──
function getColumnNames() {
  if (!designResult.value || !designResult.value.points) return []
  const row = designResult.value.points[0]
  return Object.keys(row)
}

// ── LLM 效应建议 ──
const llmSuggestVisible = ref(false)
const systemContext = ref('')
const llmSuggesting = ref(false)
const llmEvents = ref([])
const llmSuggestedEffects = ref([])
const llmReasoning = ref('')
const llmSources = ref([])
const llmConfidence = ref(null)

function getLlmConfig() {
  try {
    const saved = localStorage.getItem('alchemist_llm_config')
    if (saved) return JSON.parse(saved)
  } catch { /* ignore */ }
  return null
}

async function handleLlmSuggest() {
  if (!systemContext.value.trim()) {
    ElMessage.warning('请输入实验系统描述')
    return
  }
  const llmConfig = getLlmConfig()
  if (!llmConfig || !llmConfig.apiUrl || !llmConfig.model) {
    ElMessage.warning('请先在 LLM 配置中设置 API 地址和模型名称')
    return
  }

  llmSuggesting.value = true
  llmEvents.value = []
  llmSuggestedEffects.value = []
  llmReasoning.value = ''
  llmSources.value = []
  llmConfidence.value = null

  const config = {
    structuring_provider: {
      provider: llmConfig.apiUrl.includes('ollama') || llmConfig.apiUrl.includes('11434') ? 'ollama' : 'openai',
      model: llmConfig.model,
      api_key: llmConfig.apiKey || '',
      base_url: llmConfig.apiUrl || '',
    },
    system_context: systemContext.value,
  }

  llmSuggestEffectsSSE(
    props.sessionId,
    config,
    (event) => {
      llmEvents.value.push(event)
      if (event.type === 'effects') {
        llmSuggestedEffects.value = event.effects || []
        llmConfidence.value = event.confidence
      } else if (event.type === 'reasoning') {
        llmReasoning.value = event.content || ''
      } else if (event.type === 'sources') {
        llmSources.value = event.sources || []
      } else if (event.type === 'error') {
        ElMessage.error(event.message || 'LLM 建议失败')
      }
    },
    (err) => {
      ElMessage.error(`LLM 建议失败: ${err.message}`)
      llmSuggesting.value = false
    },
    () => {
      llmSuggesting.value = false
      if (llmSuggestedEffects.value.length > 0) {
        ElMessage.success(`LLM 建议了 ${llmSuggestedEffects.value.length} 个效应项`)
      }
    }
  )
}

function applyLlmEffects() {
  if (llmSuggestedEffects.value.length === 0) return
  modelType.value = 'custom'
  // 重置所有复选框
  for (const v of variables.value) customMainEffects.value[v.name] = false
  for (const k of Object.keys(customInteractions.value)) customInteractions.value[k] = false
  for (const v of variables.value) customQuadratic.value[v.name] = false
  customExtraEffects.value = ''

  for (const effect of llmSuggestedEffects.value) {
    const name = effect.name || effect
    if (name.includes('*') && !name.includes('**')) {
      if (name in customInteractions.value) customInteractions.value[name] = true
    } else if (name.includes('**2')) {
      const varName = name.replace('**2', '')
      if (varName in customQuadratic.value) customQuadratic.value[varName] = true
    } else {
      if (name in customMainEffects.value) customMainEffects.value[name] = true
      else customExtraEffects.value = customExtraEffects.value
        ? `${customExtraEffects.value}, ${name}`
        : name
    }
  }
  ElMessage.success('已应用 LLM 建议的效应项')
}

// ── 初始化 ──
watch(() => props.sessionId, () => { if (props.sessionId) loadVariables() })
onMounted(() => { if (props.sessionId) loadVariables() })
</script>

<template>
  <div class="oed-panel">
    <!-- 模型规格 -->
    <div style="margin-bottom:16px">
      <div style="font-size:13px;font-weight:600;color:var(--app-ink);margin-bottom:8px">模型规格</div>
      <el-radio-group v-model="modelType" size="small">
        <el-radio-button v-for="m in modelTypeOptions" :key="m.value" :value="m.value">
          <el-tooltip :content="m.desc" placement="top">
            <span>{{ m.label }}</span>
          </el-tooltip>
        </el-radio-button>
      </el-radio-group>
    </div>

    <!-- 自定义效应选择 -->
    <div v-if="modelType === 'custom'" style="border:1px solid var(--app-hairline);border-radius:8px;padding:12px;margin-bottom:16px;background:var(--app-stat-bg)">
      <!-- 主效应 -->
      <div style="margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:13px;font-weight:600;color:var(--app-ink)">主效应 (Main Effects)</span>
          <el-button text size="small" @click="toggleAllMainEffects">全选/取消</el-button>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <el-checkbox v-for="v in variables" :key="'main-'+v.name" v-model="customMainEffects[v.name]" size="small">
            {{ v.name }}
          </el-checkbox>
        </div>
      </div>

      <!-- 交互项 -->
      <div v-if="variables.length >= 2" style="margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:13px;font-weight:600;color:var(--app-ink)">交互项 (Interactions)</span>
          <el-button text size="small" @click="toggleAllInteractions">全选/取消</el-button>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <el-checkbox v-for="(key, idx) in Object.keys(customInteractions)" :key="'inter-'+idx" v-model="customInteractions[key]" size="small">
            {{ key }}
          </el-checkbox>
          <span v-if="Object.keys(customInteractions).length === 0" style="color:var(--app-ink-muted);font-size:12px">需要至少 2 个变量</span>
        </div>
      </div>

      <!-- 二次项 -->
      <div style="margin-bottom:10px">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
          <span style="font-size:13px;font-weight:600;color:var(--app-ink)">二次项 (Quadratic)</span>
          <el-button text size="small" @click="toggleAllQuadratic">全选/取消</el-button>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          <el-checkbox v-for="v in variables" :key="'quad-'+v.name" v-model="customQuadratic[v.name]" size="small">
            {{ v.name }}²
          </el-checkbox>
        </div>
      </div>

      <!-- 额外自定义效应 -->
      <div>
        <span style="font-size:13px;font-weight:600;color:var(--app-ink);display:block;margin-bottom:4px">额外自定义效应</span>
        <el-input v-model="customExtraEffects" placeholder="逗号分隔，如: 温度*压力**2, 1/温度" size="small" />
      </div>

      <div style="margin-top:8px;font-size:12px;color:var(--app-ink-muted)">
        当前已选 {{ currentEffects.length }} 个效应项：{{ currentEffects.join(', ') || '无' }}
      </div>

      <!-- LLM 建议按钮 -->
      <el-button type="warning" plain size="small" style="margin-top:8px" @click="llmSuggestVisible = !llmSuggestVisible">
        <el-icon><MagicStick /></el-icon>
        LLM 辅助建议效应
      </el-button>

      <!-- LLM 建议区域 -->
      <div v-if="llmSuggestVisible" style="margin-top:10px;padding:10px;background:#fff;border-radius:6px;border:1px solid var(--app-hairline)">
        <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:6px">描述你的实验系统，LLM 将建议哪些效应项可能是重要的</div>
        <el-input
          v-model="systemContext"
          type="textarea"
          :rows="2"
          placeholder="例如：费托合成负载金属催化剂，目标最大化C5+选择性，250°C、20bar，变量包括温度、压力、H2/CO比、活性金属负载量"
          size="small"
        />
        <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
          <el-button type="primary" size="small" @click="handleLlmSuggest" :loading="llmSuggesting">
            <el-icon><MagicStick /></el-icon> 获取 LLM 建议
          </el-button>
          <el-button v-if="llmSuggestedEffects.length > 0" type="success" size="small" @click="applyLlmEffects">
            应用建议到复选框
          </el-button>
        </div>

        <!-- LLM 推理过程 -->
        <div v-if="llmReasoning" style="margin-top:8px;padding:8px;background:#f0fdf4;border-radius:4px;font-size:12px;color:#15803d">
          <strong>推理过程：</strong>{{ llmReasoning }}
        </div>

        <!-- LLM 建议效应卡片 -->
        <div v-if="llmSuggestedEffects.length > 0" style="margin-top:8px">
          <div style="font-size:12px;font-weight:600;margin-bottom:4px;color:var(--app-ink)">
            建议效应项
            <el-tag v-if="llmConfidence != null" size="small" type="success" style="margin-left:6px">置信度: {{ (llmConfidence * 100).toFixed(0) }}%</el-tag>
          </div>
          <div style="display:flex;gap:6px;flex-wrap:wrap">
            <el-tag
              v-for="(eff, idx) in llmSuggestedEffects"
              :key="idx"
              size="small"
              :type="currentEffects.includes(eff.name || eff) ? 'success' : 'info'"
              effect="plain"
            >
              {{ eff.name || eff }}
              <el-icon v-if="currentEffects.includes(eff.name || eff)" style="margin-left:2px"><InfoFilled /></el-icon>
            </el-tag>
          </div>
        </div>

        <!-- 文献来源 -->
        <div v-if="llmSources.length > 0" style="margin-top:8px">
          <div style="font-size:12px;font-weight:600;color:var(--app-ink);margin-bottom:2px">文献来源</div>
          <div v-for="(src, idx) in llmSources" :key="idx" style="font-size:11px;color:var(--app-ink-muted);line-height:1.4">
            {{ src }}
          </div>
        </div>
      </div>
    </div>

    <!-- 设计参数 -->
    <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
      <div>
        <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">最优性准则</div>
        <el-select v-model="criterion" style="width:140px">
          <el-option v-for="c in criterionOptions" :key="c.value" :label="c.label" :value="c.value">
            <div>
              <div>{{ c.label }}</div>
              <div style="font-size:11px;color:var(--app-ink-muted)">{{ c.desc }}</div>
            </div>
          </el-option>
        </el-select>
      </div>
      <div>
        <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">交换算法</div>
        <el-select v-model="algorithm" style="width:200px">
          <el-option v-for="a in algorithmOptions" :key="a.value" :label="a.label" :value="a.value" />
        </el-select>
      </div>
      <div>
        <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">实验次数</div>
        <el-radio-group v-model="runMode" size="small" style="margin-bottom:4px">
          <el-radio-button value="multiplier">p × 倍数</el-radio-button>
          <el-radio-button value="fixed">固定数量</el-radio-button>
        </el-radio-group>
        <el-input-number
          v-if="runMode === 'multiplier'"
          v-model="pMultiplier"
          :min="1"
          :max="10"
          :step="0.5"
          style="width:100px"
        />
        <el-input-number
          v-else
          v-model="nPoints"
          :min="1"
          :max="10000"
          style="width:120px"
        />
      </div>
      <div style="display:flex;gap:8px">
        <el-button @click="handlePreview" :loading="infoLoading">
          <el-icon><InfoFilled /></el-icon>
          预览模型项
        </el-button>
        <el-button type="primary" @click="handleGenerate" :loading="loading">生成最优设计</el-button>
      </div>
    </div>

    <!-- 高级选项 -->
    <div style="margin-bottom:12px">
      <el-button text size="small" @click="showAdvanced = !showAdvanced">
        {{ showAdvanced ? '收起' : '展开' }}高级选项
      </el-button>
      <div v-if="showAdvanced" style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap">
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">网格水平数</div>
          <el-input-number v-model="gridLevels" :min="2" :max="20" size="small" style="width:120px" />
        </div>
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">最大迭代次数</div>
          <el-input-number v-model="maxIter" :min="10" :max="10000" :step="50" size="small" style="width:140px" />
        </div>
        <div>
          <div style="font-size:12px;color:var(--app-ink-muted);margin-bottom:2px">随机种子</div>
          <el-input-number v-model="randomSeed" :min="0" placeholder="可选" size="small" style="width:140px" />
        </div>
      </div>
    </div>

    <!-- 预览信息 -->
    <div v-if="previewInfo" style="border:1px solid #bfdbfe;border-radius:8px;padding:12px;margin-bottom:16px;background:#eff6ff">
      <div style="font-size:13px;font-weight:600;color:#1e40af;margin-bottom:8px">模型项预览</div>
      <div style="display:flex;gap:24px;flex-wrap:wrap;margin-bottom:8px">
        <div><span style="font-size:12px;color:var(--app-ink-muted)">模型列数 p：</span><strong>{{ previewInfo.p_columns }}</strong></div>
        <div><span style="font-size:12px;color:var(--app-ink-muted)">最少实验数：</span><strong>{{ previewInfo.n_points_minimum }}</strong></div>
        <div><span style="font-size:12px;color:var(--app-ink-muted)">推荐实验数 (2p)：</span><strong>{{ previewInfo.n_points_recommended }}</strong></div>
      </div>
      <div style="font-size:12px;color:var(--app-ink-muted)">
        模型项：{{ (previewInfo.model_terms || []).join(' + ') || '无' }}
      </div>
    </div>

    <!-- 设计结果 -->
    <div v-if="designResult" style="margin-top:16px">
      <!-- 质量指标 -->
      <div style="display:flex;gap:16px;margin-bottom:12px;flex-wrap:wrap">
        <div style="padding:10px 16px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;text-align:center;min-width:120px">
          <div style="font-size:11px;color:#15803d;margin-bottom:2px">D-效率 (D-eff)</div>
          <strong style="font-size:18px;color:#15803d">
            {{ designResult.design_info?.D_eff != null ? (designResult.design_info.D_eff * 100).toFixed(1) + '%' : '-' }}
          </strong>
        </div>
        <div style="padding:10px 16px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;text-align:center;min-width:120px">
          <div style="font-size:11px;color:#1e40af;margin-bottom:2px">A-效率 (A-eff)</div>
          <strong style="font-size:18px;color:#1e40af">
            {{ designResult.design_info?.A_eff != null ? (designResult.design_info.A_eff * 100).toFixed(1) + '%' : '-' }}
          </strong>
        </div>
        <div style="padding:10px 16px;background:var(--app-stat-bg);border-radius:8px;border:1px solid var(--app-hairline);text-align:center;min-width:100px">
          <div style="font-size:11px;color:var(--app-ink-muted);margin-bottom:2px">得分</div>
          <strong style="font-size:18px;color:var(--app-ink)">
            {{ designResult.design_info?.score != null ? Number(designResult.design_info.score).toFixed(4) : '-' }}
          </strong>
        </div>
        <div style="padding:10px 16px;background:var(--app-stat-bg);border-radius:8px;border:1px solid var(--app-hairline);text-align:center;min-width:100px">
          <div style="font-size:11px;color:var(--app-ink-muted);margin-bottom:2px">实验点数</div>
          <strong style="font-size:18px;color:var(--app-ink)">{{ designResult.n_points }}</strong>
        </div>
      </div>

      <!-- 设计矩阵表格 -->
      <el-table :data="designResult.points" border stripe max-height="360" style="margin-bottom:12px">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
      </el-table>

      <!-- 操作按钮 -->
      <div style="display:flex;gap:8px">
        <el-button type="success" size="small" @click="handleStageDesign" :loading="loading">暂存到实验队列</el-button>
        <el-button size="small" @click="handleDownloadCSV">导出 CSV</el-button>
      </div>
    </div>
  </div>
</template>
