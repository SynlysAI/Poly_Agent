<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'

const formRef = ref(null)
const submitting = ref(false)

const form = reactive({
  sample_name: '',
  material_type: '',
  prediction_type: '',
  description: '',
})

const rules = {
  sample_name: [{ required: true, message: '请输入样品名称', trigger: 'blur' }],
  material_type: [{ required: true, message: '请选择材料类型', trigger: 'change' }],
  prediction_type: [{ required: true, message: '请选择预测指标', trigger: 'change' }],
}

const materialOptions = [
  { label: '聚乙烯 (PE)', value: 'PE' },
  { label: '聚丙烯 (PP)', value: 'PP' },
  { label: '聚苯乙烯 (PS)', value: 'PS' },
  { label: '聚氯乙烯 (PVC)', value: 'PVC' },
  { label: '聚对苯二甲酸乙二醇酯 (PET)', value: 'PET' },
  { label: '其他', value: 'other' },
]

const predictionOptions = [
  { label: '分子量分布 (Mn, Mw, PDI)', value: 'molecular_weight' },
  { label: '热稳定性 (Tg, Tm, Td)', value: 'thermal' },
  { label: '力学性能 (拉伸强度, 模量)', value: 'mechanical' },
  { label: '流变性能', value: 'rheological' },
]

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    ElMessage.success('任务提交功能开发中，敬请期待')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">高分子性能指标预测</h3>
    </div>
    <div class="panel-body">
      <el-form ref="formRef" :model="form" :rules="rules" label-width="100px" style="max-width:640px">
        <el-form-item label="样品名称" prop="sample_name">
          <el-input v-model="form.sample_name" placeholder="请输入样品编号或名称" />
        </el-form-item>
        <el-form-item label="材料类型" prop="material_type">
          <el-select v-model="form.material_type" placeholder="请选择高分子材料类型" style="width:100%">
            <el-option v-for="item in materialOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="预测指标" prop="prediction_type">
          <el-select v-model="form.prediction_type" placeholder="请选择需要预测的性能指标" style="width:100%">
            <el-option v-for="item in predictionOptions" :key="item.value" :label="item.label" :value="item.value" />
          </el-select>
        </el-form-item>
        <el-form-item label="补充描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="可补充样品制备条件、测试环境等额外信息" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="submitting" @click="handleSubmit">提交预测任务</el-button>
          <el-button @click="$router.push('/tasks/center')">查看历史任务</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>
