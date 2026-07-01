<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { trainModel, getModelStatus } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

const kernelOptions = [
  { label: 'Matern 5/2', value: 'matern52' },
  { label: 'Matern 3/2', value: 'matern32' },
  { label: 'RBF（径向基函数）', value: 'rbf' },
  { label: 'IBNN（贝叶斯神经网络核）', value: 'ibnn' },
]

const backendOptions = [
  { label: 'BoTorch (推荐)', value: 'botorch' },
  { label: 'scikit-learn', value: 'sklearn' },
]

const selectedKernel = ref('matern52')
const selectedBackend = ref('botorch')
const useARD = ref(true)
const loading = ref(false)
const modelResult = ref(null)

async function handleTrainModel() {
  try {
    loading.value = true
    modelResult.value = null
    const config = {
      backend: selectedBackend.value,
      kernel: selectedKernel.value,
      kernel_params: useARD.value ? { ard: true } : {},
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
            <el-option v-for="k in kernelOptions" :key="k.value" :label="k.label" :value="k.value" />
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
          <el-descriptions-item label="核函数">{{ modelResult.kernel || selectedKernel }}</el-descriptions-item>
          <el-descriptions-item label="后端">{{ modelResult.backend || selectedBackend }}</el-descriptions-item>
          <el-descriptions-item label="训练状态">{{ modelResult.success ? '成功' : '失败' }}</el-descriptions-item>
          <el-descriptions-item label="R²">{{ modelResult.metrics?.r2 || '-' }}</el-descriptions-item>
          <el-descriptions-item label="RMSE">{{ modelResult.metrics?.rmse || '-' }}</el-descriptions-item>
          <el-descriptions-item label="MAE">{{ modelResult.metrics?.mae || '-' }}</el-descriptions-item>
        </el-descriptions>
      </div>
    </div>
  </div>
</template>
