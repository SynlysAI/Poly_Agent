<script setup>
import { ref, onMounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete, Edit } from '@element-plus/icons-vue'
import { getVariables, addVariable, deleteVariable, updateVariable } from '../../api/alchemistApi'

const props = defineProps({
  sessionId: { type: String, required: true }
})

/** 变量列表 */
const variables = ref([])
const loading = ref(false)

/** 变量类型选项 */
const variableTypes = [
  { label: '连续实值', value: 'real' },
  { label: '整数', value: 'integer' },
  { label: '分类', value: 'categorical' },
  { label: '离散值', value: 'discrete' },
]

/** 新增/编辑对话框 */
const dialogVisible = ref(false)
const editingVariable = ref(null)
const formData = ref({
  name: '',
  type: 'real',
  low: 0,
  high: 1,
  values: '',
})

async function loadVariables() {
  try {
    loading.value = true
    const data = await getVariables(props.sessionId)
    variables.value = data.variables || []
  } catch (e) {
    ElMessage.error(`加载变量列表失败: ${e.message}`)
  } finally {
    loading.value = false
  }
}

function openAddDialog() {
  editingVariable.value = null
  formData.value = { name: '', type: 'real', low: 0, high: 1, values: '' }
  dialogVisible.value = true
}

function openEditDialog(variable) {
  editingVariable.value = variable
  formData.value = {
    name: variable.name,
    type: variable.type,
    low: variable.low || 0,
    high: variable.high || 1,
    values: Array.isArray(variable.values) ? variable.values.join(', ') : (variable.values || ''),
  }
  dialogVisible.value = true
}

async function handleSave() {
  const payload = { name: formData.value.name, type: formData.value.type }
  if (formData.value.type === 'real' || formData.value.type === 'integer') {
    payload.low = Number(formData.value.low)
    payload.high = Number(formData.value.high)
  }
  if (formData.value.type === 'categorical' || formData.value.type === 'discrete') {
    payload.values = formData.value.values.split(',').map(s => s.trim()).filter(Boolean)
  }

  try {
    if (editingVariable.value) {
      await updateVariable(props.sessionId, editingVariable.value.id, payload)
      ElMessage.success('变量更新成功')
    } else {
      await addVariable(props.sessionId, payload)
      ElMessage.success('变量添加成功')
    }
    dialogVisible.value = false
    await loadVariables()
  } catch (e) {
    ElMessage.error(`保存变量失败: ${e.message}`)
  }
}

async function handleDelete(variable) {
  try {
    await ElMessageBox.confirm(`确定要删除变量"${variable.name}"吗？`, '删除确认', { type: 'warning' })
    await deleteVariable(props.sessionId, variable.id)
    ElMessage.success('变量已删除')
    await loadVariables()
  } catch (e) {
    if (e !== 'cancel') {
      ElMessage.error(`删除变量失败: ${e.message}`)
    }
  }
}

function getTypeLabel(type) {
  const found = variableTypes.find(t => t.value === type)
  return found ? found.label : type
}

watch(() => props.sessionId, () => { if (props.sessionId) loadVariables() })
onMounted(() => { if (props.sessionId) loadVariables() })
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">变量定义</h3>
      <el-button type="primary" size="small" @click="openAddDialog">
        <el-icon><Plus /></el-icon>
        添加变量
      </el-button>
    </div>
    <div class="panel-body">
      <el-table :data="variables" v-loading="loading" empty-text="暂无变量，请点击"添加变量"开始定义搜索空间">
        <el-table-column prop="name" label="变量名称" min-width="120" />
        <el-table-column label="类型" width="120">
          <template #default="{ row }">
            <el-tag size="small">{{ getTypeLabel(row.type) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="范围/值" min-width="200">
          <template #default="{ row }">
            <template v-if="row.type === 'real' || row.type === 'integer'">[{{ row.low }}, {{ row.high }}]</template>
            <template v-else>{{ Array.isArray(row.values) ? row.values.join(', ') : row.values }}</template>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="140" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="openEditDialog(row)"><el-icon><Edit /></el-icon></el-button>
            <el-button text type="danger" size="small" @click="handleDelete(row)"><el-icon><Delete /></el-icon></el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="dialogVisible" :title="editingVariable ? '编辑变量' : '添加变量'" width="480px">
      <el-form label-width="80px">
        <el-form-item label="变量名称">
          <el-input v-model="formData.name" placeholder="请输入变量名称" />
        </el-form-item>
        <el-form-item label="变量类型">
          <el-select v-model="formData.type" style="width:100%">
            <el-option v-for="t in variableTypes" :key="t.value" :label="t.label" :value="t.value" />
          </el-select>
        </el-form-item>
        <template v-if="formData.type === 'real' || formData.type === 'integer'">
          <el-form-item label="下限"><el-input-number v-model="formData.low" style="width:100%" /></el-form-item>
          <el-form-item label="上限"><el-input-number v-model="formData.high" style="width:100%" /></el-form-item>
        </template>
        <template v-else>
          <el-form-item label="可选值"><el-input v-model="formData.values" placeholder="用逗号分隔，如: A, B, C" /></el-form-item>
        </template>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="handleSave">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>
