<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, CopyDocument, Download, Plus, Upload, VideoPlay } from '@element-plus/icons-vue'

import AttributionBanner from '../components/attribution/AttributionBanner.vue'
import {
  cloneExperimentDispatchProfile,
  createExperimentDispatchProfile,
  evaluateExperimentDispatchProfile,
  getApiErrorMessage,
  listAlgorithms,
  listExperimentDispatchCandidates,
  listExperimentDispatchProfiles,
  listExperimentDispatchTargets,
  publishExperimentDispatchProfile,
  updateExperimentDispatchProfile,
} from '../api/polyAgentApi'
import { autoMatchDispatchMappings, flattenDispatchFields } from '../utils/experimentDispatch.mjs'

const router = useRouter()
const profiles = ref([])
const targets = ref([])
const algorithms = ref([])
const candidates = ref([])
const selectedKey = ref('')
const selectedRunId = ref('')
const trial = ref(null)
const loading = ref(false)
const saving = ref(false)
const trialLoading = ref(false)
const fileInput = ref(null)
const isNew = ref(false)
const draft = reactive(blankProfile())

const selectedProfile = computed(() => profiles.value.find((item) => `${item.profile_id}@${item.version}` === selectedKey.value) || null)
const selectedTarget = computed(() => targets.value.find((item) => item.target_id === draft.target_id && item.version === draft.target_version) || null)
const isGenericTarget = computed(() => draft.target_id === 'generic_json')
const targetFields = computed(() => draft.target_fields?.length ? draft.target_fields : (selectedTarget.value?.fields || []))
const sourceFields = computed(() => draft.source_contract.required_fields || [])
const sampleAlgorithm = computed(() => algorithms.value.find((item) => item.algorithm_id === draft.source_contract.example_algorithm_id) || null)
const sampleOutputFields = computed(() => flattenDispatchFields(sampleAlgorithm.value?.output_schema || sampleAlgorithm.value?.output_contract || {}, '/output'))
const availableSourceFields = computed(() => [...sourceFields.value, ...sampleOutputFields.value.filter((item) => !sourceFields.value.some((field) => field.path === item.path))])
const mappingTargets = computed(() => targetFields.value.filter((field) => field.path))

function blankProfile() {
  return {
    profile_id: '', version: '0.1.0', name: '', description: '', notes: '', visibility: 'private',
    source_contract: { example_algorithm_id: null, allowed_trigger_sources: [], required_fields: [] },
    target_id: 'generic_json', target_version: '1.0.0', target_fields: [], mappings: [], branches: [], display_fields: [], source_info: {},
  }
}
function pathField(path = '') { return { path, label: path.split('/').pop() || path, value_type: 'any', required: true, unit: null } }
function source(kind = 'path') { return kind === 'manual' ? { kind, key: '', path: null, paths: [], value: null } : kind === 'constant' ? { kind, value: '', path: null, paths: [], key: null } : { kind, path: '/output/', paths: [], value: null, key: null } }
function mapping(path = '') { return { target_path: path, label: '', source: source(), transforms: [], default_value: null, required: false, allow_override: false, error_policy: 'block' } }
function branch() { return { rule_id: `rule_${Date.now()}`, name: '新条件', priority: 100, conditions: { mode: 'all', items: [{ path: '/output/', operator: 'exists', value: null }] }, actions: [{ kind: 'warn', target_path: null, source: null, transforms: [], message: '' }], stop_on_match: false } }
function replaceDraft(value) { Object.assign(draft, JSON.parse(JSON.stringify({ ...blankProfile(), ...value, source_contract: { ...blankProfile().source_contract, ...(value.source_contract || {}) } }))); trial.value = null }
function selectProfile(profile) { selectedKey.value = `${profile.profile_id}@${profile.version}`; replaceDraft(profile); isNew.value = false }

async function load() {
  loading.value = true
  try {
    const [profileData, targetData, algorithmData, candidateData] = await Promise.all([
      listExperimentDispatchProfiles({ page: 1, page_size: 100 }), listExperimentDispatchTargets(), listAlgorithms({ page: 1, page_size: 100 }), listExperimentDispatchCandidates({ page: 1, page_size: 50 }),
    ])
    profiles.value = profileData.items || []; targets.value = targetData.items || []; algorithms.value = algorithmData.items || []; candidates.value = candidateData.items || []
    if (selectedKey.value) { const current = profiles.value.find((item) => `${item.profile_id}@${item.version}` === selectedKey.value); if (current) selectProfile(current) }
    if (!selectedKey.value && profiles.value.length) selectProfile(profiles.value[0])
    if (!selectedRunId.value && candidates.value.length) selectedRunId.value = candidates.value[0].run_id
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { loading.value = false }
}
function newProfile() { replaceDraft(blankProfile()); selectedKey.value = ''; isNew.value = true }
function addSourceField() { draft.source_contract.required_fields.push(pathField('/output/')) }
function removeSourceField(index) { draft.source_contract.required_fields.splice(index, 1) }
function addTargetField() { draft.target_fields.push({ path: '/payload/', label: '', value_type: 'string', required: false, unit: null, default_value: null, allow_override: false, order: draft.target_fields.length }) }
function removeTargetField(index) { draft.target_fields.splice(index, 1) }
function addMapping() { draft.mappings.push(mapping(mappingTargets.value[0]?.path || '/payload/')) }
function removeMapping(index) { draft.mappings.splice(index, 1) }
function addBranch() { draft.branches.push(branch()) }
function removeBranch(index) { draft.branches.splice(index, 1) }
function addTransform(item) { item.transforms.push({ operation: 'cast', value_type: 'string', scale: 1, offset: 0, lookup: {}, default_value: null, prefix: '', suffix: '', index: 0 }) }
function removeTransform(item, index) { item.transforms.splice(index, 1) }
function autoMatch() {
  const matches = autoMatchDispatchMappings(mappingTargets.value, availableSourceFields.value)
  matches.forEach((match) => { if (!draft.mappings.some((item) => item.target_path === match.target_path)) { draft.mappings.push({ ...mapping(match.target_path), source: { ...source('path'), path: match.source_path } }) } })
  ElMessage.success(`已自动匹配 ${matches.length} 个高置信度字段`)
}
function parseConstant(item) {
  if (item.source.kind !== 'constant' || typeof item.source.value !== 'string') return
  try { item.source.value = JSON.parse(item.source.value) } catch { /* keep plain text */ }
}
function profilePayload() {
  const payload = {
    name: draft.name,
    description: draft.description || null,
    notes: draft.notes || null,
    source_contract: draft.source_contract,
    target_id: draft.target_id,
    target_version: draft.target_version,
    target_fields: draft.target_fields || [],
    mappings: draft.mappings || [],
    branches: draft.branches || [],
    display_fields: draft.display_fields || [],
    source_info: draft.source_info || {},
  }
  if (isNew.value) payload.visibility = draft.visibility
  payload.mappings = payload.mappings.map((item) => ({ ...item, source: normalizeSource(item.source) }))
  payload.branches = payload.branches.map((rule) => ({
    ...rule,
    conditions: { ...rule.conditions, items: rule.conditions.items.map((condition) => ({ ...condition, value: parseLooseJson(condition.value) })) },
    actions: rule.actions.map((action) => ({ ...action, source: action.kind === 'set' ? normalizeSource(action.source || { kind: 'constant', value: action.message }) : undefined })),
  }))
  if (isNew.value) payload.profile_id = draft.profile_id || undefined
  return payload
}
function parseLooseJson(value) {
  if (typeof value !== 'string') return value
  const trimmed = value.trim()
  if (!trimmed) return null
  try { return JSON.parse(trimmed) } catch { return value }
}
function normalizeSource(value) {
  const item = { ...(value || {}) }
  if (item.kind === 'coalesce' && typeof item.paths === 'string') item.paths = item.paths.split(',').map((path) => path.trim()).filter(Boolean)
  if (item.kind === 'constant') item.value = parseLooseJson(item.value)
  return item
}
function exportProfile() {
  const blob = new Blob([JSON.stringify(draft, null, 2)], { type: 'application/json' }); const url = URL.createObjectURL(blob); const link = document.createElement('a'); link.href = url; link.download = `${draft.profile_id || 'experiment-dispatch-profile'}.${draft.version}.json`; link.click(); URL.revokeObjectURL(url)
}
function importProfile(event) { const file = event.target.files?.[0]; if (!file) return; const reader = new FileReader(); reader.onload = () => { try { replaceDraft(JSON.parse(reader.result)); isNew.value = true; selectedKey.value = ''; ElMessage.success('已导入草稿，请保存后再试运行') } catch (error) { ElMessage.error(`导入失败：${error.message}`) } }; reader.readAsText(file); event.target.value = '' }
async function saveDraft() {
  saving.value = true
  try {
    const payload = profilePayload()
    const saved = isNew.value ? await createExperimentDispatchProfile(payload) : await updateExperimentDispatchProfile(draft.profile_id, draft.version, payload)
    profiles.value = profiles.value.filter((item) => !(item.profile_id === saved.profile_id && item.version === saved.version)).concat(saved); selectProfile(saved); ElMessage.success('下发配置草稿已保存')
  } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { saving.value = false }
}
async function cloneVersion() {
  const nextVersion = `${draft.version.split('.').map((part, index) => index === 2 ? Number(part || 0) + 1 : Number(part || 0)).join('.')}`
  try { const cloned = await cloneExperimentDispatchProfile(draft.profile_id, draft.version, nextVersion); profiles.value.push(cloned); selectProfile(cloned); ElMessage.success(`已创建 v${nextVersion} 草稿`) } catch (error) { ElMessage.error(getApiErrorMessage(error)) }
}
async function publish() {
  if (!trial.value?.result?.is_valid) return ElMessage.warning('请先用已完成 Run 试运行并通过校验')
  try { const published = await publishExperimentDispatchProfile(draft.profile_id, draft.version); profiles.value = profiles.value.map((item) => item.profile_id === published.profile_id && item.version === published.version ? published : item); selectProfile(published); ElMessage.success('配置已发布') } catch (error) { ElMessage.error(getApiErrorMessage(error)) }
}
async function runTrial() {
  if (!selectedRunId.value || !draft.profile_id) return ElMessage.warning('请先保存草稿并选择样例 Run')
  trialLoading.value = true
  try { trial.value = await evaluateExperimentDispatchProfile({ run_id: selectedRunId.value, profile_id: draft.profile_id, profile_version: draft.version, manual_values: {} }); if (trial.value.result?.is_valid) ElMessage.success('样例试运行通过'); else ElMessage.warning('试运行存在校验问题') } catch (error) { ElMessage.error(getApiErrorMessage(error)) } finally { trialLoading.value = false }
}
watch(() => draft.target_id, (value) => { const target = targets.value.find((item) => item.target_id === value); if (target) { draft.target_version = target.version; if (value !== 'generic_json') draft.target_fields = [] } })
onMounted(load)
</script>

<template>
  <div class="profiles-page">
    <AttributionBanner module-id="experiment_dispatch" label="工具支持" compact />
    <section class="panel page-heading"><div><el-button text :icon="ArrowLeft" @click="router.push('/optimization/experiment-dispatch')">返回转发台</el-button><h3 class="panel-title">管理下发配置</h3><p class="panel-subtitle">以版本化、可审计的声明式映射连接算法输出与实验接口。</p></div><div class="heading-actions"><el-button :icon="Plus" @click="newProfile">新建</el-button><el-button :icon="Upload" @click="fileInput?.click()">导入</el-button><input ref="fileInput" type="file" accept="application/json" hidden @change="importProfile" /><el-button :icon="Download" @click="exportProfile">导出 JSON</el-button></div></section>
    <div class="editor-layout">
      <aside class="panel profile-list"><div class="panel-header"><h3 class="panel-title">配置列表</h3></div><div class="panel-body profile-list-body"><el-button type="primary" plain class="full-width" @click="newProfile"><el-icon><Plus /></el-icon>新建下发配置</el-button><button v-for="profile in profiles" :key="`${profile.profile_id}@${profile.version}`" type="button" class="profile-list-item" :class="{ active: selectedKey === `${profile.profile_id}@${profile.version}` }" @click="selectProfile(profile)"><strong>{{ profile.name }}</strong><span>{{ profile.profile_id }} · v{{ profile.version }}</span><el-tag size="small" :type="profile.status === 'published' ? 'success' : 'info'">{{ profile.status === 'published' ? '已发布' : '草稿' }}</el-tag></button><div v-if="!profiles.length && !loading" class="empty-inline">暂无配置</div></div></aside>
      <main class="panel editor-panel"><div class="panel-header editor-header"><div><h3 class="panel-title">{{ draft.name || '新下发配置' }}</h3><p class="panel-caption">{{ isNew ? '未保存草稿' : `${draft.profile_id} · v${draft.version}` }}</p></div><div class="heading-actions"><el-button v-if="!isNew && draft.status === 'published'" :icon="CopyDocument" @click="cloneVersion">复制新版本</el-button><el-button v-if="!isNew && draft.status === 'draft'" :loading="saving" type="primary" @click="saveDraft">保存草稿</el-button><el-button v-if="!isNew && draft.status === 'draft'" :loading="trialLoading" :icon="VideoPlay" @click="runTrial">试运行</el-button><el-button v-if="!isNew && draft.status === 'draft'" type="success" :disabled="!trial?.result?.is_valid" @click="publish">发布</el-button></div></div>
        <el-tabs type="border-card" class="editor-tabs">
          <el-tab-pane label="基本信息"><el-form label-position="top" class="editor-form"><div class="form-grid"><el-form-item label="配置 ID" required><el-input v-model="draft.profile_id" :disabled="!isNew" placeholder="例如 formulation_dispatch" /></el-form-item><el-form-item label="版本" required><el-input v-model="draft.version" :disabled="!isNew" placeholder="0.1.0" /></el-form-item></div><el-form-item label="名称" required><el-input v-model="draft.name" /></el-form-item><div class="form-grid"><el-form-item label="可见性"><el-radio-group v-model="draft.visibility"><el-radio-button value="private">私有</el-radio-button><el-radio-button value="public">公开</el-radio-button></el-radio-group></el-form-item><el-form-item label="目标接口"><el-select v-model="draft.target_id" class="full-width"><el-option v-for="target in targets" :key="`${target.target_id}@${target.version}`" :label="`${target.name} · v${target.version}`" :value="target.target_id" /></el-select></el-form-item></div><el-form-item label="说明"><el-input v-model="draft.description" type="textarea" :rows="2" /></el-form-item><el-form-item label="配置备注"><el-input v-model="draft.notes" type="textarea" :rows="2" /></el-form-item><el-form-item label="示例算法"><el-select v-model="draft.source_contract.example_algorithm_id" clearable filterable class="full-width"><el-option v-for="algorithm in algorithms" :key="algorithm.algorithm_id" :label="algorithm.name || algorithm.algorithm_id" :value="algorithm.algorithm_id" /></el-select></el-form-item><div class="subsection-title">输入字段契约 <el-button text :icon="Plus" @click="addSourceField">添加字段</el-button></div><div v-for="(field,index) in draft.source_contract.required_fields" :key="index" class="inline-row"><el-input v-model="field.path" placeholder="/output/value" /><el-input v-model="field.label" placeholder="显示名称" /><el-select v-model="field.value_type" placeholder="类型"><el-option v-for="type in ['any','string','number','integer','boolean','object','array']" :key="type" :label="type" :value="type" /></el-select><el-checkbox v-model="field.required">必填</el-checkbox><el-button text type="danger" @click="removeSourceField(index)">删除</el-button></div></el-form></el-tab-pane>
          <el-tab-pane label="参数映射"><div class="toolbar"><span class="panel-caption">目标参数 · 数据来源 · 安全转换 · 状态</span><el-button text @click="autoMatch">一键按同名匹配</el-button><el-button text :icon="Plus" @click="addMapping">添加映射</el-button></div><el-table :data="draft.mappings" border size="small"><el-table-column label="目标参数" min-width="190"><template #default="{ row }"><el-select v-model="row.target_path" filterable class="full-width"><el-option v-for="field in mappingTargets" :key="field.path" :label="field.label || field.path" :value="field.path" /></el-select></template></el-table-column><el-table-column label="数据来源" min-width="260"><template #default="{ row }"><div class="source-editor"><el-select v-model="row.source.kind"><el-option label="字段" value="path" /><el-option label="常量" value="constant" /><el-option label="人工输入" value="manual" /><el-option label="回退字段" value="coalesce" /></el-select><el-input v-if="row.source.kind === 'path'" v-model="row.source.path" placeholder="/output/..." /><el-input v-else-if="row.source.kind === 'constant'" v-model="row.source.value" placeholder="值" @blur="parseConstant(row)" /><el-input v-else-if="row.source.kind === 'manual'" v-model="row.source.key" placeholder="manual key" /><el-input v-else v-model="row.source.paths" placeholder="/output/a, /output/b" /></div></template></el-table-column><el-table-column label="转换" min-width="180"><template #default="{ row }"><div v-for="(transform,index) in row.transforms" :key="index" class="transform-line"><el-select v-model="transform.operation"><el-option v-for="op in ['cast','scale','lookup','concat','array_item','default']" :key="op" :label="op" :value="op" /></el-select><el-input v-if="transform.operation === 'cast'" v-model="transform.value_type" placeholder="类型" /><el-input v-else-if="transform.operation === 'scale'" v-model.number="transform.scale" placeholder="scale" /><el-button text type="danger" @click="removeTransform(row,index)">×</el-button></div><el-button text @click="addTransform(row)">+ 转换</el-button></template></el-table-column><el-table-column label="选项" width="150"><template #default="{ row }"><el-checkbox v-model="row.allow_override">允许人工覆盖</el-checkbox><el-button text type="danger" @click="removeMapping(draft.mappings.indexOf(row))">删除</el-button></template></el-table-column></el-table><div v-if="isGenericTarget" class="target-fields"><div class="subsection-title">自定义目标字段 <el-button text :icon="Plus" @click="addTargetField">添加字段</el-button></div><div v-for="(field,index) in draft.target_fields" :key="index" class="inline-row"><el-input v-model="field.path" placeholder="/payload/value" /><el-input v-model="field.label" placeholder="标签" /><el-select v-model="field.value_type"><el-option v-for="type in ['string','number','integer','boolean','object','array','any']" :key="type" :label="type" :value="type" /></el-select><el-checkbox v-model="field.required">必填</el-checkbox><el-checkbox v-model="field.allow_override">允许覆盖</el-checkbox><el-button text type="danger" @click="removeTargetField(index)">删除</el-button></div></div></el-tab-pane>
          <el-tab-pane label="条件分支与试运行"><div class="toolbar"><span class="panel-caption">按优先级确定性执行，不支持脚本或任意表达式</span><el-button text :icon="Plus" @click="addBranch">添加条件分支</el-button></div><div v-for="(rule,index) in draft.branches" :key="rule.rule_id" class="rule-card"><div class="rule-head"><el-input v-model="rule.name" placeholder="分支名称" /><el-input v-model.number="rule.priority" type="number" placeholder="优先级" /><el-checkbox v-model="rule.stop_on_match">命中后停止</el-checkbox><el-button text type="danger" @click="removeBranch(index)">删除</el-button></div><div v-for="condition in rule.conditions.items" :key="condition.path" class="inline-row"><span class="when-label">当</span><el-input v-model="condition.path" placeholder="/output/value" /><el-select v-model="condition.operator"><el-option v-for="op in ['exists','equals','notEquals','in','between','gt','gte','lt','lte']" :key="op" :label="op" :value="op" /></el-select><el-input :model-value="condition.value == null ? '' : String(condition.value)" placeholder="比较值" @update:model-value="condition.value = $event" /></div><div v-for="action in rule.actions" :key="action.kind" class="inline-row"><span class="when-label">设置</span><el-select v-model="action.kind"><el-option label="设置字段" value="set" /><el-option label="追加警告" value="warn" /><el-option label="阻止生成" value="block" /></el-select><el-input v-if="action.kind === 'set'" v-model="action.target_path" placeholder="目标路径" /><el-input v-model="action.message" placeholder="动作值或提示语" /></div></div><el-divider /><div class="trial-row"><el-select v-model="selectedRunId" filterable placeholder="选择已完成样例 Run" class="trial-select"><el-option v-for="run in candidates" :key="run.run_id" :label="`${run.algorithm_name || run.algorithm_id} · ${run.run_id.slice(0, 12)}`" :value="run.run_id" /></el-select><el-button :loading="trialLoading" :icon="VideoPlay" type="primary" @click="runTrial">试运行</el-button></div><div v-if="trial" class="trial-result"><el-tag :type="trial.result?.is_valid ? 'success' : 'danger'">{{ trial.result?.is_valid ? '通过' : '未通过' }}</el-tag><pre class="json-view">{{ JSON.stringify(trial.result || {}, null, 2) }}</pre></div></el-tab-pane>
        </el-tabs>
      </main>
    </div>
  </div>
</template>

<style scoped>
.profiles-page { display:flex; flex-direction:column; gap:24px; max-width:1440px; margin:0 auto; }.page-heading,.editor-header,.heading-actions,.toolbar,.trial-row { display:flex; align-items:center; justify-content:space-between; gap:10px; flex-wrap:wrap; }.panel-subtitle,.panel-caption { color:var(--app-ink-muted); font-size:13px; }.panel-subtitle { margin:6px 0 0; }.editor-layout { display:grid; grid-template-columns:260px minmax(0,1fr); gap:24px; align-items:start; }.profile-list { position:sticky; top:16px; }.profile-list-body { padding:12px; }.full-width { width:100%; }.profile-list-item { box-sizing:border-box; width:100%; max-width:100%; display:flex; flex-direction:column; align-items:flex-start; gap:4px; padding:11px 10px; border:0; border-top:1px solid var(--app-border-soft); background:transparent; color:inherit; text-align:left; cursor:pointer; }.profile-list-body > .el-button { box-sizing:border-box; max-width:100%; }.profile-list-item.active { background:var(--app-primary-light); }.profile-list-item span { color:var(--app-ink-muted); font-size:11px; }.editor-panel { min-width:0; overflow:hidden; }.editor-tabs { min-width:0; border:0; box-shadow:none; }.editor-tabs :deep(.el-tabs__nav-wrap) { overflow-x:auto; }.editor-tabs :deep(.el-tabs__content) { padding:18px 20px 20px; }.editor-form { padding:4px 2px; }.form-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:12px; }.subsection-title { display:flex; align-items:center; justify-content:space-between; margin:14px 0 8px; color:var(--app-ink); font-size:13px; font-weight:700; }.inline-row { display:grid; grid-template-columns:minmax(120px,1fr) minmax(120px,1fr) 130px auto auto; gap:8px; align-items:center; margin:8px 0; }.toolbar { margin-bottom:10px; }.source-editor,.transform-line { display:flex; gap:6px; }.source-editor .el-input { min-width:0; }.transform-line { margin-bottom:5px; }.rule-card { padding:12px; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); margin-bottom:10px; }.rule-head { display:grid; grid-template-columns:minmax(120px,1fr) 100px auto auto; gap:8px; align-items:center; }.when-label { color:var(--app-ink-muted); font-size:12px; }.trial-select { min-width:280px; }.trial-result { margin-top:12px; }.json-view { margin:8px 0 0; padding:10px; max-height:320px; overflow:auto; background:#f8fafc; border:1px solid var(--app-border-soft); border-radius:var(--app-radius-sm); font:12px/1.6 var(--app-mono-font); white-space:pre-wrap; word-break:break-word; }.empty-inline { padding:20px 8px; color:var(--app-ink-muted); text-align:center; }
@media (max-width:900px) { .editor-layout { grid-template-columns:1fr; }.profile-list { position:static; }.inline-row,.rule-head { grid-template-columns:1fr; }.source-editor,.transform-line { flex-wrap:wrap; }.source-editor .el-select,.source-editor .el-input { width:100%; }.form-grid { grid-template-columns:1fr; } }
</style>
