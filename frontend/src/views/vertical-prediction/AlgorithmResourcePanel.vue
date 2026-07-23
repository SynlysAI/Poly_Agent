<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus, Refresh, VideoPlay } from '@element-plus/icons-vue'

import {
  checkAlgorithmResource,
  createAlgorithmResource,
  getApiErrorMessage,
  listAlgorithmResources,
} from '../../api/polyAgentApi'

const emit = defineEmits(['changed'])

const loading = ref(false)
const resources = ref([])
const filters = reactive({
  algorithm_id: '',
  asset_key: '',
  status: '',
})
const form = reactive({
  algorithm_id: 'raman_structure_analyzer',
  asset_key: 'raman_runtime_resources',
  name: 'Raman runtime resources',
  path: '/home/fangyikai/github_project/Spec_Agent/backend/resources/raman',
  resource_type: 'raman_runtime',
  required_files: 'checkpoints/baseline_removal.pth\ncheckpoints/raman_fg.pth',
  description: 'Raman resource parent directory containing function-group analysis checkpoints.',
})

function parseRequiredFiles(value) {
  return String(value || '')
    .split(/\r?\n|,/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function statusType(status) {
  const map = { active: 'success', missing: 'warning', invalid: 'danger', disabled: 'info' }
  return map[status] || 'info'
}

function storageModeLabel(value) {
  const map = { mounted_path: '挂载路径' }
  return map[value] || value || '-'
}

async function loadResources() {
  loading.value = true
  try {
    const params = {}
    for (const key of ['algorithm_id', 'asset_key', 'status']) {
      if (filters[key]) params[key] = filters[key]
    }
    const data = await listAlgorithmResources({ ...params, page: 1, page_size: 100 })
    resources.value = data.items || []
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function submitResource() {
  if (!form.algorithm_id.trim() || !form.asset_key.trim() || !form.name.trim() || !form.path.trim()) {
    ElMessage.warning('请填写算法 ID、资源 Key、名称和路径')
    return
  }
  loading.value = true
  try {
    await createAlgorithmResource({
      algorithm_id: form.algorithm_id.trim(),
      asset_key: form.asset_key.trim(),
      name: form.name.trim(),
      storage_mode: 'mounted_path',
      path: form.path.trim(),
      resource_type: form.resource_type.trim() || null,
      required_files: parseRequiredFiles(form.required_files),
      description: form.description.trim() || null,
    })
    ElMessage.success('资源已登记')
    filters.algorithm_id = form.algorithm_id.trim()
    await loadResources()
    emit('changed')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

async function checkResource(row) {
  loading.value = true
  try {
    const updated = await checkAlgorithmResource(row.resource_id)
    ElMessage[updated.status === 'active' ? 'success' : 'warning'](updated.status_message || '检查完成')
    await loadResources()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

onMounted(loadResources)
</script>

<template>
  <div class="resource-panel" v-loading="loading">
    <section class="resource-editor">
      <div class="panel-heading">
        <div>
          <h2>资源管理</h2>
          <p>登记服务器或挂载盘上的模型权重、数据库和 tokenizer。</p>
        </div>
        <el-button :icon="Refresh" @click="loadResources">刷新</el-button>
      </div>

      <el-form label-position="top" class="resource-form">
        <div class="form-grid">
          <el-form-item label="算法 ID"><el-input v-model="form.algorithm_id" /></el-form-item>
          <el-form-item label="资源 Key"><el-input v-model="form.asset_key" /></el-form-item>
          <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
          <el-form-item label="资源类型"><el-input v-model="form.resource_type" /></el-form-item>
        </div>
        <el-form-item label="服务器路径"><el-input v-model="form.path" /></el-form-item>
        <el-form-item label="必需文件"><el-input v-model="form.required_files" type="textarea" :rows="3" class="code-input" /></el-form-item>
        <el-form-item label="备注"><el-input v-model="form.description" type="textarea" :rows="2" /></el-form-item>
        <div class="action-row">
          <el-button type="primary" :icon="Plus" @click="submitResource">登记资源</el-button>
        </div>
      </el-form>
    </section>

    <section class="resource-table">
      <div class="table-head">
        <div>
          <h3>已登记资源</h3>
          <p>{{ resources.length }} 条</p>
        </div>
        <div class="filter-row">
          <el-input v-model="filters.algorithm_id" placeholder="算法 ID" clearable @change="loadResources" />
          <el-input v-model="filters.asset_key" placeholder="资源 Key" clearable @change="loadResources" />
          <el-select v-model="filters.status" placeholder="状态" clearable @change="loadResources">
            <el-option label="active" value="active" />
            <el-option label="missing" value="missing" />
            <el-option label="invalid" value="invalid" />
            <el-option label="disabled" value="disabled" />
          </el-select>
        </div>
      </div>

      <el-table :data="resources" border empty-text="暂无资源">
        <el-table-column prop="algorithm_id" label="算法 ID" min-width="190" />
        <el-table-column prop="asset_key" label="资源 Key" min-width="150" />
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="name" label="名称" min-width="170" />
        <el-table-column label="类型" width="110">
          <template #default="{ row }">{{ row.resource_type || storageModeLabel(row.storage_mode) }}</template>
        </el-table-column>
        <el-table-column prop="path" label="路径" min-width="280" show-overflow-tooltip />
        <el-table-column label="必需文件" min-width="180" show-overflow-tooltip>
          <template #default="{ row }">{{ (row.required_files || []).join(', ') || '-' }}</template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button text :icon="VideoPlay" @click="checkResource(row)">检查</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<style scoped>
.resource-panel { display: grid; gap: 16px; }
.resource-editor, .resource-table {
  min-width: 0;
  border: 1px solid var(--app-border);
  border-radius: var(--app-radius-md);
  background: #fff;
  padding: 18px;
}
.panel-heading, .table-head, .action-row, .filter-row { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.panel-heading, .table-head { justify-content: space-between; }
.panel-heading h2, .table-head h3 { margin: 0; color: var(--app-ink); letter-spacing: 0; }
.panel-heading h2 { font-size: 20px; line-height: 1.3; }
.table-head h3 { font-size: 15px; }
.panel-heading p, .table-head p { margin: 4px 0 0; color: var(--app-ink-muted); font-size: 13px; line-height: 1.5; }
.resource-form { display: grid; gap: 12px; margin-top: 14px; }
.form-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.code-input :deep(textarea) { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 12px; }
.filter-row { justify-content: flex-end; }
.filter-row .el-input, .filter-row .el-select { width: 180px; }
@media (max-width: 980px) {
  .form-grid { grid-template-columns: 1fr 1fr; }
  .filter-row { width: 100%; justify-content: stretch; }
  .filter-row .el-input, .filter-row .el-select { width: 100%; flex: 1 1 180px; }
}
@media (max-width: 640px) {
  .resource-editor, .resource-table { padding: 12px; }
  .form-grid { grid-template-columns: 1fr; }
}
</style>
