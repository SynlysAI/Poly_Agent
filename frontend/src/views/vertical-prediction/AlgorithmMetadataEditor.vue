<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Delete, Plus } from '@element-plus/icons-vue'

import { getApiErrorMessage, updateAlgorithmMetadata } from '../../api/polyAgentApi'

const props = defineProps({
  visible: { type: Boolean, default: false },
  algorithm: { type: Object, default: null },
  activeVersion: { type: Object, default: null },
})

const emit = defineEmits(['update:visible', 'saved'])

const formRef = ref(null)
const saving = ref(false)
const apiError = ref('')
const fieldErrors = ref({})
const contributorRows = ref([])

const form = reactive({
  name: '',
  description: '',
  visibility: 'private',
  developer: '',
  developer_organization: '',
  mentor_team: '',
  source_url: '',
  citation: '',
  reason: '',
})

const drawerVisible = computed({
  get: () => props.visible,
  set: (value) => emit('update:visible', value),
})

const rules = {
  name: [
    { required: true, message: '请输入算法名称', trigger: 'blur' },
    { max: 120, message: '算法名称不能超过 120 个字符', trigger: 'blur' },
  ],
}

function resetForm() {
  const algorithm = props.algorithm || {}
  const attribution = algorithm.developer_attribution || {}
  Object.assign(form, {
    name: algorithm.name || '',
    description: algorithm.description || '',
    visibility: algorithm.visibility || 'private',
    developer: attribution.name || '',
    developer_organization: attribution.organization || '',
    mentor_team: algorithm.mentor_team || '',
    source_url: attribution.url || '',
    citation: attribution.citation_text || '',
    reason: '',
  })
  contributorRows.value = (algorithm.contributors || []).map((item) => ({ ...item }))
  apiError.value = ''
  fieldErrors.value = {}
  formRef.value?.clearValidate()
}

function addContributor() {
  contributorRows.value.push({
    user_id: null,
    name: '',
    role: 'developer',
    organization: form.developer_organization || '',
    mentor_relation: '',
    description: '',
  })
}

function removeContributor(index) {
  contributorRows.value.splice(index, 1)
}

function optionalText(value) {
  const normalized = String(value || '').trim()
  return normalized || null
}

function contributorPayload(row) {
  return {
    user_id: optionalText(row.user_id),
    name: String(row.name || '').trim(),
    role: String(row.role || '').trim(),
    organization: optionalText(row.organization),
    mentor_relation: optionalText(row.mentor_relation),
    description: optionalText(row.description),
  }
}

function parseValidationErrors(errors) {
  const parsed = {}
  for (const error of errors || []) {
    const location = (error.loc || []).filter((item) => item !== 'body')
    const key = location.join('.')
    if (key && !parsed[key]) parsed[key] = error.msg
  }
  return parsed
}

function contributorError(index, field) {
  return fieldErrors.value[`contributors.${index}.${field}`] || ''
}

function validateContributors() {
  let valid = true
  contributorRows.value.forEach((row, index) => {
    if (!String(row.name || '').trim()) {
      fieldErrors.value[`contributors.${index}.name`] = '请输入姓名'
      valid = false
    }
    if (!String(row.role || '').trim()) {
      fieldErrors.value[`contributors.${index}.role`] = '请选择角色'
      valid = false
    }
  })
  return valid
}

async function save() {
  apiError.value = ''
  fieldErrors.value = {}
  const formValid = await formRef.value?.validate().catch(() => false)
  if (!formValid || !validateContributors()) return

  saving.value = true
  try {
    const updated = await updateAlgorithmMetadata(props.algorithm.algorithm_id, {
      name: form.name.trim(),
      description: optionalText(form.description),
      visibility: form.visibility,
      developer: optionalText(form.developer),
      developer_organization: optionalText(form.developer_organization),
      mentor_team: optionalText(form.mentor_team),
      source_url: optionalText(form.source_url),
      citation: optionalText(form.citation),
      contributors: contributorRows.value.map(contributorPayload),
      reason: optionalText(form.reason),
    })
    ElMessage.success('算法信息已更新')
    emit('saved', updated)
    drawerVisible.value = false
  } catch (error) {
    if (error.status === 422 && Array.isArray(error.errors)) {
      fieldErrors.value = parseValidationErrors(error.errors)
    }
    apiError.value = getApiErrorMessage(error)
  } finally {
    saving.value = false
  }
}

watch(() => [props.visible, props.algorithm?.algorithm_id], ([visible]) => {
  if (visible) resetForm()
})
</script>

<template>
  <el-drawer v-model="drawerVisible" title="编辑算法信息" size="min(780px, 96vw)" :close-on-click-modal="!saving">
    <div class="metadata-editor">
      <el-descriptions v-if="algorithm" :column="2" border size="small" class="contract-summary">
        <el-descriptions-item label="算法 ID">{{ algorithm.algorithm_id }}</el-descriptions-item>
        <el-descriptions-item label="当前版本">{{ activeVersion?.version || algorithm.version || '-' }}</el-descriptions-item>
        <el-descriptions-item label="算法类型">{{ algorithm.type || '-' }}</el-descriptions-item>
        <el-descriptions-item label="来源类型">{{ algorithm.source || '-' }}</el-descriptions-item>
      </el-descriptions>

      <el-alert v-if="apiError" type="error" :title="apiError" :closable="false" show-icon />

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" :disabled="saving">
        <div class="form-grid">
          <el-form-item label="算法名称" prop="name" :error="fieldErrors.name">
            <el-input v-model="form.name" maxlength="120" show-word-limit @input="delete fieldErrors.name" />
          </el-form-item>
          <el-form-item label="公开状态" prop="visibility" :error="fieldErrors.visibility">
            <el-segmented v-model="form.visibility" :options="[{ label: '仅自己与管理员', value: 'private' }, { label: '平台公开', value: 'public' }]" />
          </el-form-item>
        </div>

        <el-form-item label="算法介绍" prop="description" :error="fieldErrors.description">
          <el-input v-model="form.description" type="textarea" :rows="4" maxlength="1000" show-word-limit />
        </el-form-item>

        <div class="form-grid">
          <el-form-item label="开发者" prop="developer" :error="fieldErrors.developer">
            <el-input v-model="form.developer" maxlength="160" />
          </el-form-item>
          <el-form-item label="开发机构" prop="developer_organization" :error="fieldErrors.developer_organization">
            <el-input v-model="form.developer_organization" maxlength="160" />
          </el-form-item>
          <el-form-item label="导师课题组" prop="mentor_team" :error="fieldErrors.mentor_team">
            <el-input v-model="form.mentor_team" maxlength="160" />
          </el-form-item>
          <el-form-item label="来源链接" prop="source_url" :error="fieldErrors.source_url">
            <el-input v-model="form.source_url" maxlength="600" placeholder="https://..." />
          </el-form-item>
        </div>

        <el-form-item label="推荐引用" prop="citation" :error="fieldErrors.citation">
          <el-input v-model="form.citation" type="textarea" :rows="3" maxlength="1000" show-word-limit />
        </el-form-item>

        <section class="contributors-section">
          <div class="section-heading">
            <h3>结构化贡献者</h3>
            <el-button :icon="Plus" @click="addContributor">添加贡献者</el-button>
          </div>
          <el-table :data="contributorRows" border size="small" empty-text="暂无贡献者">
            <el-table-column label="姓名" min-width="150">
              <template #default="{ row, $index }">
                <el-input v-model="row.name" :class="{ 'has-error': contributorError($index, 'name') }" @input="delete fieldErrors[`contributors.${$index}.name`]" />
                <small v-if="contributorError($index, 'name')" class="field-error">{{ contributorError($index, 'name') }}</small>
              </template>
            </el-table-column>
            <el-table-column label="角色" min-width="130">
              <template #default="{ row, $index }">
                <el-select v-model="row.role" filterable allow-create :class="{ 'has-error': contributorError($index, 'role') }">
                  <el-option label="开发" value="developer" /><el-option label="审核" value="reviewer" />
                  <el-option label="指导" value="mentor" /><el-option label="维护" value="maintainer" />
                  <el-option label="数据" value="data" /><el-option label="方法" value="method" />
                </el-select>
                <small v-if="contributorError($index, 'role')" class="field-error">{{ contributorError($index, 'role') }}</small>
              </template>
            </el-table-column>
            <el-table-column label="机构" min-width="150"><template #default="{ row }"><el-input v-model="row.organization" /></template></el-table-column>
            <el-table-column label="导师关系" min-width="150"><template #default="{ row }"><el-input v-model="row.mentor_relation" /></template></el-table-column>
            <el-table-column label="贡献说明" min-width="180"><template #default="{ row }"><el-input v-model="row.description" /></template></el-table-column>
            <el-table-column width="54" fixed="right">
              <template #default="{ $index }"><el-button text :icon="Delete" aria-label="删除贡献者" @click="removeContributor($index)" /></template>
            </el-table-column>
          </el-table>
        </section>

        <el-form-item label="修改说明（可选）" prop="reason" :error="fieldErrors.reason">
          <el-input v-model="form.reason" type="textarea" :rows="2" maxlength="1000" show-word-limit />
        </el-form-item>
      </el-form>

      <el-collapse class="contract-collapse">
        <el-collapse-item title="输入输出契约（只读）" name="contracts">
          <div class="contract-grid">
            <div><strong>输入契约</strong><pre>{{ JSON.stringify(algorithm?.input_schema || {}, null, 2) }}</pre></div>
            <div><strong>输出契约</strong><pre>{{ JSON.stringify(algorithm?.output_schema || {}, null, 2) }}</pre></div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </div>

    <template #footer>
      <el-button :disabled="saving" @click="drawerVisible = false">取消</el-button>
      <el-button type="primary" :loading="saving" @click="save">保存</el-button>
    </template>
  </el-drawer>
</template>

<style scoped>
.metadata-editor { display: grid; gap: 16px; min-width: 0; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.contract-summary :deep(.el-descriptions__content) { overflow-wrap: anywhere; }
.contributors-section { display: grid; gap: 10px; margin-bottom: 18px; min-width: 0; }
.section-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.section-heading h3 { margin: 0; color: var(--app-ink); font-size: 15px; letter-spacing: 0; }
.field-error { display: block; margin-top: 3px; color: var(--el-color-danger); font-size: 12px; }
.has-error :deep(.el-input__wrapper), .has-error :deep(.el-select__wrapper) { box-shadow: 0 0 0 1px var(--el-color-danger) inset; }
.contract-collapse { border-top: 1px solid var(--app-border-soft); }
.contract-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.contract-grid > div { min-width: 0; }
.contract-grid strong { display: block; margin-bottom: 6px; color: var(--app-ink); font-size: 13px; }
.contract-grid pre { max-height: 260px; overflow: auto; margin: 0; padding: 10px; border: 1px solid var(--app-border-soft); border-radius: var(--app-radius-sm); background: #f8fafc; color: var(--app-ink-body); font: 12px/1.5 var(--app-mono-font); white-space: pre-wrap; overflow-wrap: anywhere; }
@media (max-width: 680px) {
  .form-grid, .contract-grid { grid-template-columns: 1fr; }
  .contract-summary :deep(.el-descriptions__body table) { table-layout: fixed; }
  .section-heading { align-items: stretch; flex-direction: column; }
}
</style>
