<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { trainModel, getModelStatus, getExperimentsSummary } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const kernelOptions = [
  { label: 'Matern 5/2', id: 'matern52', kernel: 'Matern', params: { nu: 2.5 } },
  { label: 'Matern 3/2', id: 'matern32', kernel: 'Matern', params: { nu: 1.5 } },
  { label: 'RBF（径向基函数）', id: 'rbf', kernel: 'RBF', params: {} },
  { label: 'IBNN（贝叶斯神经网络核）', id: 'ibnn', kernel: 'IBNN', params: {} },
]

const backendOptions = [
  { label: 'scikit-learn（基础稳定）', value: 'sklearn' },
  { label: 'BoTorch', value: 'botorch' },
]

const selectedKernel = ref('matern52')
const selectedBackend = ref('sklearn')
const useARD = ref(true)
const loading = ref(false)
const modelResult = ref(null)

/** 判断模型结果是否代表已训练成功。 */
function isModelTrained() {
  if (!modelResult.value) return false
  if (typeof modelResult.value.success === 'boolean') return modelResult.value.success
  return Boolean(modelResult.value.is_trained)
}

/** 核函数显示名称 — 直接返回后端值，未训练或无法获取时回退到前端所选。 */
function getKernelDisplayName(kernel) {
  return kernel || selectedKernel.value
}

async function handleTrainModel() {
  try {
    loading.value = true
    modelResult.value = null
    const summary = await getExperimentsSummary(props.sessionId)
    const nExperiments = summary.n_experiments || 0
    if (nExperiments < 5) {
      ElMessage.warning(`当前只有 ${nExperiments} 条实验数据，GP 建模至少需要 5 条带输出值的实验数据`)
      return
    }
    const kernelOption = kernelOptions.find(item => item.id === selectedKernel.value) || kernelOptions[0]
    if (selectedBackend.value === 'sklearn' && kernelOption.kernel === 'IBNN') {
      ElMessage.warning('scikit-learn 后端不支持 IBNN 核函数，请选择 Matern/RBF 或切换到 BoTorch')
      return
    }
    const config = {
      backend: selectedBackend.value,
      kernel: kernelOption.kernel,
      kernel_params: kernelOption.params,
    }
    const data = await trainModel(props.sessionId, config)
    modelResult.value = data
    ElMessage.success('模型训练完成')
  } catch (e) {
    ElMessage.error(`模型训练失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

async function handleCheckStatus() {
  try {
    const data = await getModelStatus(props.sessionId)
    if (data.is_trained) {
      ElMessage.success(`模型状态: 已训练 (${data.backend})`)
      modelResult.value = data
    } else {
      modelResult.value = null
      ElMessage.info('模型状态: 未训练')
    }
  } catch (e) {
    ElMessage.error(`获取模型状态失败: ${e.message}`)
  }
}
</script>

<template>
  <div class="panel">
    <div class="panel-header"><h3 class="panel-title">高斯过程回归建模</h3></div>
    <div class="panel-body">
      <div style="display:flex;gap:24px;align-items:flex-end;margin-bottom:16px;flex-wrap:wrap">
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">核函数</div>
          <el-select v-model="selectedKernel" style="width:220px">
            <el-option v-for="k in kernelOptions" :key="k.id" :label="k.label" :value="k.id" />
          </el-select>
        </div>
        <div>
          <div style="font-size:13px;color:var(--app-ink-muted);margin-bottom:4px">计算后端</div>
          <el-select v-model="selectedBackend" style="width:200px">
            <el-option v-for="b in backendOptions" :key="b.value" :label="b.label" :value="b.value" />
          </el-select>
        </div>
        <div>
          <el-checkbox v-model="useARD">自动相关性确定 (ARD)</el-checkbox>
        </div>
        <div>
          <el-button type="primary" @click="handleTrainModel" :loading="loading">训练模型</el-button>
          <el-button @click="handleCheckStatus">查看状态</el-button>
        </div>
      </div>

      <div v-if="modelResult" style="margin-top:16px">
        <el-descriptions border :column="2" size="small">
          <el-descriptions-item label="核函数">{{ getKernelDisplayName(modelResult.kernel) }}</el-descriptions-item>
          <el-descriptions-item label="后端">{{ modelResult.backend || selectedBackend }}</el-descriptions-item>
          <el-descriptions-item label="训练状态">{{ isModelTrained() ? '已训练' : '未训练' }}</el-descriptions-item>
          <el-descriptions-item label="R²">{{ modelResult.metrics?.r2 || '-' }}</el-descriptions-item>
          <el-descriptions-item label="RMSE">{{ modelResult.metrics?.rmse || '-' }}</el-descriptions-item>
          <el-descriptions-item label="MAE">{{ modelResult.metrics?.mae || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
  </div>
</template>
