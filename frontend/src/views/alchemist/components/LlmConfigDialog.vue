<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

const props = defineProps({
  visible: { type: Boolean, default: false }
})

const emit = defineEmits(['update:visible'])

const STORAGE_KEY = 'alchemist_llm_config'

const formData = ref({
  apiUrl: '',
  apiKey: '',
  model: 'gpt-4o',
})

function loadConfig() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    if (saved) {
      const config = JSON.parse(saved)
      formData.value = { ...formData.value, ...config }
    }
  } catch {
    /* 忽略解析错误 */
  }
}

function handleSave() {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(formData.value))
    emit('update:visible', false)
    ElMessage.success('LLM 配置已保存')
  } catch (e) {
    ElMessage.error('保存配置失败')
  }
}

function handleClose() {
  emit('update:visible', false)
}

watch(() => props.visible, (val) => {
  if (val) loadConfig()
})
</script>

<template>
  <el-dialog :model-value="visible" title="LLM 配置" width="480px" @close="handleClose">
    <el-form label-width="100px">
      <el-form-item label="API 地址">
        <el-input v-model="formData.apiUrl" placeholder="例如: https://api.openai.com/v1" />
        <div style="font-size:11px;color:var(--app-ink-muted);margin-top:4px">Ollama 用户请填写 http://localhost:11434/v1</div>
      </el-form-item>
      <el-form-item label="API Key">
        <el-input v-model="formData.apiKey" type="password" show-password placeholder="请输入 API Key" />
      </el-form-item>
      <el-form-item label="模型名称">
        <el-input v-model="formData.model" placeholder="例如: gpt-4o, gpt-4, llama3" />
      </el-form-item>
    </el-form>
    <template #footer>
      <el-button @click="handleClose">取消</el-button>
      <el-button type="primary" @click="handleSave">保存配置</el-button>
    </template>
  </el-dialog>
</template>
