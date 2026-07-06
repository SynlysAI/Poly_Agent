<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Cpu, Promotion } from '@element-plus/icons-vue'

import { createComputation, getApiErrorMessage } from '../api/polyAgentApi'

const router = useRouter()
const formRef = ref(null)
const submitting = ref(false)

const form = reactive({
  name: 'candidate_001',
  smiles: 'CCOC1=CC=CC=C1',
  workflow_type: 'LOCAL_XTB',
  engine: 'XTB',
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
  { label: 'Local 结构生成', value: 'LOCAL_STRUCTURE' },
  { label: 'xTB / CREST 粗优化', value: 'LOCAL_XTB' },
  { label: 'ORCA 精加工', value: 'ORCA_COMPUTE_ENGINE_LASER' },
]

const engineOptionsByWorkflow = {
  LOCAL_STRUCTURE: [
    { label: 'LOCAL 自动选择', value: 'LOCAL' },
    { label: 'RDKit', value: 'RDKit' },
    { label: 'OpenBabel', value: 'OPENBABEL' },
  ],
  LOCAL_XTB: [{ label: 'xTB', value: 'XTB' }],
  ORCA_COMPUTE_ENGINE_LASER: [{ label: 'ORCA', value: 'ORCA' }],
}

const methodOptionsByWorkflow = {
  LOCAL_STRUCTURE: [
    { label: 'GFN2-xTB', value: 'GFN2-xTB' },
    { label: 'GFN1-xTB', value: 'GFN1-xTB' },
  ],
  LOCAL_XTB: [
    { label: 'GFN2-xTB', value: 'GFN2-xTB' },
    { label: 'GFN1-xTB', value: 'GFN1-xTB' },
    { label: 'GFN0-xTB', value: 'GFN0-xTB' },
  ],
  ORCA_COMPUTE_ENGINE_LASER: [
    { label: 'B3LYP / def2-SVP', value: 'ORCA_B3LYP_DEF2_SVP' },
    { label: 'PBE0 / def2-SVP', value: 'ORCA_PBE0_DEF2_SVP' },
  ],
}

const solventOptions = [
  { label: '不使用', value: '' },
  { label: 'Water', value: 'WATER' },
  { label: 'Acetonitrile', value: 'ACETONITRILE' },
  { label: 'Toluene', value: 'TOLUENE' },
  { label: 'Ethanol', value: 'ETHANOL' },
  { label: 'Methanol', value: 'METHANOL' },
  { label: 'DCM', value: 'DCM' },
  { label: 'THF', value: 'THF' },
]

const engineOptions = computed(() => engineOptionsByWorkflow[form.workflow_type] || [])
const methodOptions = computed(() => methodOptionsByWorkflow[form.workflow_type] || methodOptionsByWorkflow.LOCAL_XTB)

watch(
  () => form.workflow_type,
  (workflowType) => {
    const engines = engineOptionsByWorkflow[workflowType] || []
    if (!engines.some((item) => item.value === form.engine)) {
      form.engine = engines[0]?.value || ''
    }
    const methods = methodOptionsByWorkflow[workflowType] || []
    if (!methods.some((item) => item.value === form.method)) {
      form.method = methods[0]?.value || 'GFN2-xTB'
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
</script>

<template>
  <div class="submit-layout">
    <section class="panel">
      <div class="panel-header">
        <div>
          <h3 class="panel-title">计算任务提交</h3>
          <p class="panel-subtitle">创建可追踪的真实 computation run，worker 会调用已配置的 RDKit/OpenBabel、xTB、CREST 或 ORCA。</p>
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
            <el-select v-model="form.method" style="width:100%">
              <el-option v-for="item in methodOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
          </el-form-item>
          <el-form-item label="Solvent">
            <el-select v-model="form.solvent" clearable style="width:100%">
              <el-option v-for="item in solventOptions" :key="item.value" :label="item.label" :value="item.value" />
            </el-select>
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
  </div>
</template>

<style scoped>
.submit-layout {
  display: block;
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

@media (max-width: 640px) {
  .compact-grid {
    grid-template-columns: 1fr;
  }
}
</style>
