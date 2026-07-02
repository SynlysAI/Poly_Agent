<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Connection, Cpu, MagicStick, Plus, Promotion } from '@element-plus/icons-vue'

import {
  createCampaign,
  createComputation,
  generateSuggestion,
  getApiErrorMessage,
  importCampaignCandidates,
  submitSuggestionComputation,
} from '../api/polyAgentApi'

const router = useRouter()
const formRef = ref(null)
const submitting = ref(false)
const demoSubmitting = ref(false)
const demoResult = ref(null)

const form = reactive({
  name: 'candidate_001',
  smiles: 'CCOC1=CC=CC=C1',
  workflow_type: 'MOCK_XTB_ONLY',
  engine: 'MOCK',
  charge: 0,
  multiplicity: 1,
  method: 'GFN2-xTB',
  solvent: '',
  num_cores: 2,
  memory_mb: 4096,
  max_wallclock_seconds: 1800,
})

const rules = {
  name: [{ required: true, message: '请输入候选名称', trigger: 'blur' }],
  smiles: [{ required: true, message: '请输入 SMILES', trigger: 'blur' }],
  workflow_type: [{ required: true, message: '请选择 workflow', trigger: 'change' }],
  engine: [{ required: true, message: '请选择 engine', trigger: 'change' }],
}

const workflowOptions = [
  { label: 'Mock xTB 单点', value: 'MOCK_XTB_ONLY' },
  { label: 'Mock Laser 指标', value: 'MOCK_LASER' },
  { label: 'Local 结构生成', value: 'LOCAL_STRUCTURE' },
  { label: 'Local xTB', value: 'LOCAL_XTB' },
]

const engineOptionsByWorkflow = {
  MOCK_XTB_ONLY: [{ label: 'MOCK 本地演示引擎', value: 'MOCK' }],
  MOCK_LASER: [{ label: 'MOCK 本地演示引擎', value: 'MOCK' }],
  LOCAL_STRUCTURE: [
    { label: 'LOCAL 自动选择', value: 'LOCAL' },
    { label: 'RDKit', value: 'RDKit' },
    { label: 'OpenBabel', value: 'OPENBABEL' },
  ],
  LOCAL_XTB: [{ label: 'xTB', value: 'XTB' }],
}

const engineOptions = computed(() => engineOptionsByWorkflow[form.workflow_type] || [])

watch(
  () => form.workflow_type,
  (workflowType) => {
    const options = engineOptionsByWorkflow[workflowType] || []
    if (!options.some((item) => item.value === form.engine)) {
      form.engine = options[0]?.value || ''
    }
    if (workflowType === 'LOCAL_XTB') {
      form.method = 'GFN2-xTB'
    }
  },
)

function buildComputationPayload() {
  return {
    workflow_type: form.workflow_type,
    engine: form.engine,
    molecule: {
      name: form.name,
      smiles: form.smiles,
    },
    parameters: {
      charge: Number(form.charge),
      multiplicity: Number(form.multiplicity),
      method: form.method,
      solvent: form.solvent || null,
    },
    resources: {
      num_cores: Number(form.num_cores),
      memory_mb: Number(form.memory_mb),
      max_wallclock_seconds: Number(form.max_wallclock_seconds),
    },
    source: 'task_submit_view',
  }
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const data = await createComputation(buildComputationPayload())
    ElMessage.success(`计算任务已创建：${data.run_id}`)
    await router.push({ path: '/computations/runs', query: { run_id: data.run_id } })
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    submitting.value = false
  }
}

async function handleCreateOptimizationDemo() {
  demoSubmitting.value = true
  demoResult.value = null
  try {
    const campaign = await createCampaign({
      name: `Mock laser screening ${new Date().toISOString().slice(0, 10)}`,
      planner_type: 'fallback',
      objectives: [
        { name: 'gain_factor', direction: 'max', unit: 'cm2_s', required: true },
      ],
      planner_config: { batch_size: 1 },
    })
    await importCampaignCandidates(campaign.campaign_id, {
      candidates: [
        { candidate_key: 'C001', smiles: form.smiles, metadata: { source: 'TaskSubmitView demo' } },
        { candidate_key: 'C002', smiles: 'COC1=CC=CC=C1', metadata: { source: 'TaskSubmitView demo' } },
        { candidate_key: 'C003', smiles: 'CCN(CC)C1=CC=CC=C1', metadata: { source: 'TaskSubmitView demo' } },
      ],
    })
    const suggestions = await generateSuggestion(campaign.campaign_id, { batch_size: 1 })
    const suggestion = suggestions.items[0]
    const submitted = await submitSuggestionComputation(suggestion.suggestion_id)
    demoResult.value = {
      campaign_id: campaign.campaign_id,
      suggestion_id: suggestion.suggestion_id,
      run_id: submitted.run_id,
    }
    ElMessage.success('优化闭环 demo 已创建，并已提交首个计算任务')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    demoSubmitting.value = false
  }
}
</script>

<template>
  <div class="submit-layout">
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">计算任务提交</h3>
          <p class="panel-subtitle">创建可追踪的 computation run，mock worker 会自动推进状态并生成 artifact。</p>
        </div>
      </div>
      <div class="panel-body">
        <el-form ref="formRef" :model="form" :rules="rules" label-width="128px" class="computation-form">
          <div class="form-section-title">分子与 workflow</div>
          <el-form-item label="候选名称" prop="name">
            <el-input v-model="form.name" placeholder="candidate_001" />
          </el-form-item>
          <el-form-item label="SMILES" prop="smiles">
            <el-input v-model="form.smiles" placeholder="CCOC1=CC=CC=C1" />
          </el-form-item>
          <el-form-item label="Workflow" prop="workflow_type">
            <el-select v-model="form.workflow_type" style="width:100%">
              <el-option v-for="item in workflowOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="Engine" prop="engine">
            <el-select v-model="form.engine" style="width:100%">
              <el-option v-for="item in engineOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>

          <div class="form-section-title">参数与资源</div>
          <div class="compact-grid">
            <el-form-item label="Charge">
              <el-input-number v-model="form.charge" :min="-5" :max="5" controls-position="right" style="width:100%" />
            </el-form-item>
            <el-form-item label="Multiplicity">
              <el-input-number v-model="form.multiplicity" :min="1" :max="6" controls-position="right" style="width:100%" />
            </el-form-item>
            <el-form-item label="CPU cores">
              <el-input-number v-model="form.num_cores" :min="1" :max="32" controls-position="right" style="width:100%" />
            </el-form-item>
            <el-form-item label="Memory MB">
              <el-input-number v-model="form.memory_mb" :min="512" :max="131072" :step="512" controls-position="right" style="width:100%" />
            </el-form-item>
          </div>
          <el-form-item label="Method">
            <el-input v-model="form.method" />
          </el-form-item>
          <el-form-item label="Solvent">
            <el-input v-model="form.solvent" placeholder="可选" />
          </el-form-item>
          <el-form-item label="Wallclock">
            <el-input-number v-model="form.max_wallclock_seconds" :min="60" :max="172800" :step="60" controls-position="right" style="width:100%" />
          </el-form-item>
          <el-form-item>
            <el-button type="primary" :icon="Promotion" :loading="submitting" @click="handleSubmit">提交计算任务</el-button>
            <el-button :icon="Cpu" @click="$router.push('/computations/runs')">计算任务中心</el-button>
          </el-form-item>
        </el-form>
      </div>
    </section>

    <aside class="panel demo-panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">优化闭环 Demo</h3>
          <p class="panel-subtitle">创建 campaign、导入候选、生成 suggestion，并将 suggestion 转为计算任务。</p>
        </div>
      </div>
      <div class="panel-body demo-flow">
        <div class="flow-step">
          <el-icon><Plus /></el-icon>
          <span>Campaign</span>
        </div>
        <div class="flow-step">
          <el-icon><MagicStick /></el-icon>
          <span>Suggestion</span>
        </div>
        <div class="flow-step">
          <el-icon><Connection /></el-icon>
          <span>Computation</span>
        </div>
        <el-button type="primary" plain :loading="demoSubmitting" @click="handleCreateOptimizationDemo">生成闭环 demo</el-button>
        <el-descriptions v-if="demoResult" :column="1" border size="small" class="demo-result">
          <el-descriptions-item label="Campaign">{{ demoResult.campaign_id }}</el-descriptions-item>
          <el-descriptions-item label="Suggestion">{{ demoResult.suggestion_id }}</el-descriptions-item>
          <el-descriptions-item label="Run">{{ demoResult.run_id }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.submit-layout {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.8fr);
  gap: 16px;
}

.panel-subtitle {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
}

.computation-form {
  max-width: 780px;
}

.form-section-title {
  margin: 4px 0 14px;
  color: var(--app-sidebar-from);
  font-size: 13px;
  font-weight: 700;
}

.form-section-title:not(:first-child) {
  margin-top: 24px;
}

.compact-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 14px;
}

.demo-panel {
  align-self: start;
}

.demo-flow {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.flow-step {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 42px;
  padding: 0 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  background: #f8fbff;
  color: var(--app-ink-body);
  font-weight: 600;
}

.flow-step .el-icon {
  color: var(--app-primary);
}

.demo-result {
  margin-top: 4px;
}

@media (max-width: 1100px) {
  .submit-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 640px) {
  .compact-grid {
    grid-template-columns: 1fr;
  }
}
</style>
