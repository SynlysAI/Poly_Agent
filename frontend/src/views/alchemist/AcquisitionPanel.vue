<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { dispatchExperimentTask, getModelStatus, suggestNext, findOptimum } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const acquisitionOptions = [
  { label: '期望改进 (EI)', value: 'EI', needXi: true },
  { label: '改进概率 (PI)', value: 'PI', needXi: true },
  { label: '上置信界 (UCB)', value: 'UCB', needKappa: true },
  { label: 'q-期望改进 (qEI)', value: 'qEI' },
  { label: 'q-上置信界 (qUCB)', value: 'qUCB', needKappa: true },
  { label: 'q-负积分后验方差 (qNIPV)', value: 'qNIPV' },
]

const selectedAcquisition = ref('EI')
const nSuggestions = ref(1)
const loading = ref(false)
const suggestions = ref([])
const goal = ref('maximize')
const xi = ref(0.01)
const kappa = ref(1.96)

/** 最优结果 */
const optimumResult = ref(null)
const optimumLoading = ref(false)

/** SpecLabOS 实验任务下发状态 */
const dispatchDialogVisible = ref(false)
const dispatchLoading = ref(false)
const dispatchResult = ref(null)
const dispatchForm = ref({
  experimentName: '',
  objectName: '',
  objectType: '',
  objectDescription: '',
  experimentContent: '',
})

const batchStrategies = ['qEI', 'qUCB', 'qNIPV']
const isBatchStrategy = computed(() => batchStrategies.includes(selectedAcquisition.value))

const currentAcqOption = computed(() =>
  acquisitionOptions.find(a => a.value === selectedAcquisition.value) || acquisitionOptions[0]
)

async function handleSuggest() {
  try {
    loading.value = true
    suggestions.value = []
    const status = await getModelStatus(props.sessionId)
    if (isBatchStrategy.value && status.backend !== 'botorch') {
      ElMessage.warning('批量采集函数通常需要 BoTorch 后端；当前模型后端不支持')
      return
    }

    const effectiveSuggestions = isBatchStrategy.value ? nSuggestions.value : 1
    const config = {
      strategy: selectedAcquisition.value,
      goal: goal.value,
      n_suggestions: effectiveSuggestions,
    }
    if (currentAcqOption.value.needXi) config.xi = xi.value
    if (currentAcqOption.value.needKappa) config.kappa = kappa.value

    const data = await suggestNext(props.sessionId, config)
    suggestions.value = data.suggestions || data.candidates || []
    ElMessage.success(`获得 ${suggestions.value.length} 组建议实验点`)
  } catch (e) {
    ElMessage.error(`获取建议失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleFindOptimum() {
  try {
    optimumLoading.value = true
    optimumResult.value = null
    const data = await findOptimum(props.sessionId, { goal: goal.value })
    optimumResult.value = data
    ElMessage.success(`找到模型最优点: ${data.predicted_value?.toFixed(4)}`)
  } catch (e) {
    ElMessage.error(`搜索最优值失败: ${e.message}`)
  } finally {
    optimumLoading.value = false
  }
}

/** 打开实验任务下发对话框。 */
function openDispatchDialog() {
  if (suggestions.value.length === 0) {
    ElMessage.warning('请先生成实验建议后再下发任务')
    return
  }
  dispatchResult.value = null
  dispatchDialogVisible.value = true
}

/** 构建当前建议对应的实验任务下发请求。 */
function buildDispatchPayload() {
  const acquisitionParameters = {}
  if (currentAcqOption.value.needXi) acquisitionParameters.xi = xi.value
  if (currentAcqOption.value.needKappa) acquisitionParameters.kappa = kappa.value

  return {
    experiment_name: dispatchForm.value.experimentName.trim(),
    experiment_object: {
      name: dispatchForm.value.objectName.trim(),
      type: dispatchForm.value.objectType.trim() || null,
      description: dispatchForm.value.objectDescription.trim() || null,
    },
    experiment_content: dispatchForm.value.experimentContent.trim() || null,
    conditions: suggestions.value.map((parameters) => ({
      parameters,
      metadata: {},
    })),
    strategy: selectedAcquisition.value,
    goal: goal.value,
    acquisition_parameters: acquisitionParameters,
  }
}

/** 将当前实验建议下发至 SpecLabOS。 */
async function handleDispatch() {
  if (!dispatchForm.value.experimentName.trim() || !dispatchForm.value.objectName.trim()) {
    ElMessage.warning('请填写实验任务名称和实验对象名称')
    return
  }

  try {
    dispatchLoading.value = true
    dispatchResult.value = await dispatchExperimentTask(
      props.sessionId,
      buildDispatchPayload()
    )
    ElMessage.success(`实验任务已被 SpecLabOS 接收：${dispatchResult.value.dispatch_id}`)
  } catch (e) {
    ElMessage.error(`下发实验任务失败: ${e.message}`)
  } finally {
    dispatchLoading.value = false
  }
}

function getColumnNames() {
  if (suggestions.value.length === 0) return []
  const row = suggestions.value[0]
  if (typeof row === 'object' && !Array.isArray(row)) return Object.keys(row)
  return []
}

watch(selectedAcquisition, () => {
  if (!isBatchStrategy.value) nSuggestions.value = 1
  else if (nSuggestions.value < 2) nSuggestions.value = 2
})
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">采集优化</h3></div>
    <div class="panel-body">
      <!-- 参数区 -->
      <div style="display:flex;gap:16px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">采集函数</div>
          <el-select v-model="selectedAcquisition" style="width:260px">
            <el-option v-for="a in acquisitionOptions" :key="a.value" :label="a.label" :value="a.value" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">优化目标</div>
          <el-radio-group v-model="goal" size="small">
            <el-radio-button value="maximize">最大化</el-radio-button>
            <el-radio-button value="minimize">最小化</el-radio-button>
          </el-radio-group>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">建议点数量</div>
          <el-input-number
            v-model="nSuggestions"
            :min="isBatchStrategy ? 2 : 1"
            :max="10"
            :disabled="!isBatchStrategy"
            style="width:100px"
          />
        </div>
        <div v-if="currentAcqOption.needXi">
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">xi（探索权重）</div>
          <el-input-number v-model="xi" :min="0.0001" :max="0.1" :step="0.001" :precision="4" style="width:130px" />
        </div>
        <div v-if="currentAcqOption.needKappa">
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">kappa / beta</div>
          <el-input-number v-model="kappa" :min="0.1" :max="5.0" :step="0.1" :precision="2" style="width:130px" />
        </div>
        <div style="display:flex;gap:8px">
          <el-button type="primary" @click="handleSuggest" :loading="loading">生成建议</el-button>
          <el-button @click="handleFindOptimum" :loading="optimumLoading">寻找最优点</el-button>
          <el-button @click="openDispatchDialog" :disabled="suggestions.length === 0">下发至 SpecLabOS</el-button>
        </div>
      </div>

      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px">
        <template #title>
          EI / PI / UCB 每次推荐 1 个点；需要并行建议请选择 qEI、qUCB 或 qNIPV。xi 控制探索程度，kappa/beta 控制置信界宽度。
        </template>
      </el-alert>

      <!-- 建议点表格 -->
      <el-table :data="suggestions" border stripe empty-text="请选好参数后点击【生成建议】" max-height="360" style="margin-bottom:16px">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
      </el-table>

      <!-- Find Optimum 结果 -->
      <div v-if="optimumResult" style="border:1px solid var(--app-hairline);border-radius:8px;padding:16px;background:var(--app-stat-bg)">
        <h4 style="font-size:14px;font-weight:600;margin:0 0 10px;color:var(--app-ink)">
          模型最优点 ({{ optimumResult.goal === 'maximize' ? '最大化' : '最小化' }})
        </h4>
        <div style="display:flex;gap:24px;flex-wrap:wrap;align-items:center">
          <div v-for="(val, key) in optimumResult.optimum" :key="key" style="text-align:center">
            <div style="font-size:11px;color:var(--app-ink-muted);margin-bottom:2px">{{ key }}</div>
            <strong style="font-size:16px;color:var(--app-ink)">{{ typeof val === 'number' ? val.toFixed(4) : val }}</strong>
          </div>
          <div style="text-align:center;padding:8px 16px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0">
            <div style="font-size:11px;color:#15803d;margin-bottom:2px">预测值</div>
            <strong style="font-size:18px;color:#15803d">{{ optimumResult.predicted_value?.toFixed(4) }}</strong>
            <span v-if="optimumResult.predicted_std != null" style="font-size:12px;color:#4ade80;margin-left:4px">±{{ optimumResult.predicted_std?.toFixed(4) }}</span>
          </div>
        </div>
        <el-alert type="warning" :closable="false" show-icon style="margin-top:10px">
          <template #title>
            此结果完全依赖模型预测，未使用采集函数平衡探索与利用。建议在对模型精度有信心时使用。
          </template>
        </el-alert>
      </div>
    </div>

    <el-dialog v-model="dispatchDialogVisible" title="下发实验任务至 SpecLabOS" width="680px">
      <div v-if="dispatchResult" style="margin-bottom:16px">
        <el-alert type="success" :closable="false" show-icon>
          <template #title>
            SpecLabOS 已接收任务 {{ dispatchResult.dispatch_id }}（{{ dispatchResult.received_at }}）
          </template>
        </el-alert>
      </div>
      <el-form label-width="120px">
        <el-form-item label="实验任务名称" required>
          <el-input v-model="dispatchForm.experimentName" placeholder="例如：催化条件优化第 3 轮" :disabled="dispatchLoading" />
        </el-form-item>
        <el-form-item label="实验对象名称" required>
          <el-input v-model="dispatchForm.objectName" placeholder="例如：目标反应或样品名称" :disabled="dispatchLoading" />
        </el-form-item>
        <el-form-item label="对象类型">
          <el-input v-model="dispatchForm.objectType" placeholder="例如：reaction、sample" :disabled="dispatchLoading" />
        </el-form-item>
        <el-form-item label="对象说明">
          <el-input v-model="dispatchForm.objectDescription" type="textarea" :rows="2" :disabled="dispatchLoading" />
        </el-form-item>
        <el-form-item label="实验说明">
          <el-input v-model="dispatchForm.experimentContent" type="textarea" :rows="3" placeholder="可选，填写操作备注或验收要求" :disabled="dispatchLoading" />
        </el-form-item>
      </el-form>
      <el-alert type="info" :closable="false" show-icon style="margin-bottom:12px">
        <template #title>
          将下发 {{ suggestions.length }} 组推荐实验条件。当前版本仅在 SpecLabOS 登记任务，不会直接启动湿实验设备。
        </template>
      </el-alert>
      <el-table :data="suggestions" border stripe max-height="220">
        <el-table-column type="index" label="序号" width="60" />
        <el-table-column v-for="col in getColumnNames()" :key="col" :prop="col" :label="col" min-width="100" />
      </el-table>
      <template #footer>
        <el-button @click="dispatchDialogVisible = false" :disabled="dispatchLoading">关闭</el-button>
        <el-button type="primary" @click="handleDispatch" :loading="dispatchLoading">确认下发</el-button>
      </template>
    </el-dialog>
  </div>
</template>
