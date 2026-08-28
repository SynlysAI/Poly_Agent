<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh } from '@element-plus/icons-vue'

import AttributionBadges from '../components/attribution/AttributionBadges.vue'
import {
  createAgentExecRun,
  getApiErrorMessage,
  getCapabilityCatalog,
  getModuleAttribution,
} from '../api/polyAgentApi'
import {
  CAPABILITY_GROUP_ORDER,
  buildCapabilityConnectorPayload,
  capabilityAction,
  capabilityStatusLabel,
  normalizeCapabilityCatalog,
  visibleCapabilityItems,
} from '../utils/capabilityCenter.mjs'

const router = useRouter()
const rawCatalog = ref(null)
const moduleAttribution = ref(null)
const loading = ref(false)
const loadError = ref('')
const connectorDialogVisible = ref(false)
const connectorSubmitting = ref(false)
const connectorTarget = ref(null)
const lastRun = ref(null)
const connectorForm = reactive({
  prompt: '',
  timeoutSeconds: 60,
  confirmed: false,
})

const catalog = computed(() => normalizeCapabilityCatalog(rawCatalog.value || {}))

const groupMeta = {
  dialogue_tools: { title: '对话工具', description: '从研发引擎派生并可在问答中调用的算法工具。' },
  agent_connectors: { title: '外部 Agent 连接器', description: '由服务端策略治理的受控结构化文件任务。' },
  report_skills: { title: '报告 Skill', description: '仅来自服务端 pipeline allowlist，不读取本地 Skill。' },
  llm_capabilities: { title: 'LLM 能力', description: '脱敏 provider 与模型能力，可进入对话选择调用。' },
}

const groups = computed(() => CAPABILITY_GROUP_ORDER.map((key) => {
  const group = catalog.value[key]
  return {
    ...group,
    ...groupMeta[key],
    items: visibleCapabilityItems(group, catalog.value.is_admin),
  }
}))

const permissionSummary = computed(() => ({
  roleLabel: catalog.value.is_admin ? '管理员' : '普通用户',
  total: groups.value.reduce((sum, group) => sum + group.items.length, 0),
  invocable: groups.value.reduce((sum, group) => sum + group.items.filter((item) => item.policy.viewer_can_invoke).length, 0),
  connectors: groups.value.find((group) => group.group_id === 'agent_connectors')?.items.length || 0,
}))

/**
 * 加载服务端实时能力目录。
 *
 * @returns {Promise<void>} 加载完成或提示错误。
 */
async function loadCatalog() {
  loading.value = true
  loadError.value = ''
  try {
    const [catalogResult, attributionResult] = await Promise.allSettled([
      getCapabilityCatalog(),
      getModuleAttribution('capability_center'),
    ])
    if (catalogResult.status === 'fulfilled') {
      rawCatalog.value = catalogResult.value
    } else {
      loadError.value = getApiErrorMessage(catalogResult.reason)
      rawCatalog.value = null
    }
    moduleAttribution.value = (
      attributionResult.status === 'fulfilled' ? attributionResult.value : null
    )
  } catch (error) {
    loadError.value = getApiErrorMessage(error)
    rawCatalog.value = null
  } finally {
    loading.value = false
  }
}

/**
 * 返回能力状态的标签样式。
 *
 * @param {string} status 能力状态。
 * @returns {string} Element Plus tag type。
 */
function capabilityStatusTag(status) {
  const map = { available: 'success', degraded: 'warning', disabled: 'warning', unavailable: 'danger' }
  return map[status] || 'info'
}

/**
 * 返回分组状态的中文与样式。
 *
 * @param {object} group 能力分组。
 * @returns {{label: string, tag: string}} 分组状态展示。
 */
function groupStatus(group) {
  const map = {
    available: { label: '全部可用', tag: 'success' },
    partial: { label: '部分可用', tag: 'warning' },
    unavailable: { label: '暂不可用', tag: 'danger' },
  }
  return map[group.status] || map.unavailable
}

/**
 * 触发能力卡片的主调用动作。
 *
 * @param {object} item 能力卡片。
 * @returns {void} 无返回值。
 */
function invokeCapability(item) {
  const action = capabilityAction(item)
  if (action.disabled) return
  if (action.kind === 'api') {
    openConnectorDialog(item)
    return
  }
  router.push(item.invocation.target)
}

/**
 * 打开外部连接器显式确认对话框。
 *
 * @param {object} item 外部连接器卡片。
 * @returns {void} 无返回值。
 */
function openConnectorDialog(item) {
  connectorTarget.value = item
  connectorForm.prompt = ''
  connectorForm.timeoutSeconds = 60
  connectorForm.confirmed = false
  connectorDialogVisible.value = true
}

/**
 * 提交已显式确认的外部连接器任务。
 *
 * @returns {Promise<void>} 提交完成或保持对话框并提示错误。
 */
async function submitConnectorRun() {
  if (!connectorTarget.value) return
  connectorSubmitting.value = true
  try {
    const payload = buildCapabilityConnectorPayload({
      providerId: connectorTarget.value.id,
      prompt: connectorForm.prompt,
      timeoutSeconds: connectorForm.timeoutSeconds,
      confirmed: connectorForm.confirmed,
    })
    const run = await createAgentExecRun(payload)
    lastRun.value = run
    connectorDialogVisible.value = false
    ElMessage.success(`外部任务已提交：${run.run_id}`)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    connectorSubmitting.value = false
  }
}

/**
 * 格式化角色标签。
 *
 * @param {string} role 角色值。
 * @returns {string} 中文角色。
 */
function roleLabel(role) {
  const map = { admin: '管理员', user: '普通用户' }
  return map[role] || role
}

/**
 * 格式化调用方式标签。
 *
 * @param {object} item 能力卡片。
 * @returns {string} 调用方式。
 */
function invocationLabel(item) {
  const map = {
    dialogue_tool: '对话工具',
    agent_connector: '结构化文件任务',
    report_skill: '报告 pipeline',
    llm_model: '模型路由',
  }
  return map[item.invocation.kind] || item.invocation.kind
}

onMounted(loadCatalog)
</script>

<template>
  <div class="capability-view">
    <header class="capability-header">
      <div>
        <h1>能力中心</h1>
        <p>实时查看 agent 当前可调用的工具、外部连接器、报告 Skill 与模型能力；这里只读展示，不修改配置。</p>
      </div>
      <el-button type="primary" :icon="Refresh" :loading="loading" @click="loadCatalog">刷新目录</el-button>
    </header>

    <section
      v-if="moduleAttribution?.attributions?.length"
      class="module-source"
      aria-label="能力来源"
    >
      <span>能力来源</span>
      <AttributionBadges
        :attributions="moduleAttribution.attributions"
        :limit="moduleAttribution.attributions.length"
      />
    </section>

    <el-alert
      v-if="loadError"
      type="error"
      show-icon
      :closable="false"
      title="能力目录加载失败"
      :description="loadError"
    />

    <section class="permission-panel" aria-label="权限摘要">
      <article>
        <span>当前视角</span>
        <strong>{{ permissionSummary.roleLabel }}</strong>
        <small>{{ catalog.is_admin ? '可查看不可用原因并跳转工具配置中心' : '仅显示策略允许且可调用的能力' }}</small>
      </article>
      <article>
        <span>可见能力</span>
        <strong>{{ permissionSummary.total }}</strong>
        <small>实时来自四个模块事实源</small>
      </article>
      <article>
        <span>可调用</span>
        <strong>{{ permissionSummary.invocable }}</strong>
        <small>调用前按卡片展示确认要求</small>
      </article>
      <article>
        <span>开放连接器</span>
        <strong>{{ permissionSummary.connectors }}</strong>
        <small>普通用户每次调用必须确认</small>
      </article>
    </section>

    <section
      v-for="group in groups"
      :key="group.group_id"
      class="capability-group"
      :aria-label="group.title"
    >
      <div class="group-heading">
        <div>
          <h2>{{ group.title }}</h2>
          <p>{{ group.description }}</p>
        </div>
        <el-tag :type="groupStatus(group).tag" effect="plain">
          {{ groupStatus(group).label }} · {{ group.invocable_count }}/{{ group.total_count }} 可调用
        </el-tag>
      </div>

      <el-alert
        v-if="group.unavailable_reason && !group.items.length"
        type="info"
        :closable="false"
        :title="catalog.is_admin ? group.unavailable_reason : '当前没有对你开放的能力'"
      />

      <div v-else class="capability-grid">
        <article v-for="item in group.items" :key="item.id" class="capability-card">
          <header>
            <div>
              <h3>{{ item.name }}</h3>
              <p>{{ item.description || item.id }}</p>
            </div>
            <el-tag size="small" :type="capabilityStatusTag(item.status)">
              {{ capabilityStatusLabel(item.status) }}
            </el-tag>
          </header>

          <p v-if="item.reason && catalog.is_admin" class="reason">{{ item.reason }}</p>

          <dl class="policy-list">
            <div>
              <dt>允许角色</dt>
              <dd>{{ item.policy.allowed_roles.map(roleLabel).join(' / ') || '-' }}</dd>
            </div>
            <div>
              <dt>调用方式</dt>
              <dd>{{ invocationLabel(item) }}</dd>
            </div>
            <div>
              <dt>确认要求</dt>
              <dd>{{ item.policy.requires_confirmation ? '调用前确认' : '无需确认' }}</dd>
            </div>
          </dl>

          <p class="scope-note">{{ item.policy.scope_note }}</p>
          <AttributionBadges class="source-badges" :attributions="item.attributions" :limit="3" />

          <footer>
            <el-button
              size="small"
              type="primary"
              :disabled="capabilityAction(item).disabled"
              @click="invokeCapability(item)"
            >
              {{ capabilityAction(item).label }}
            </el-button>
            <el-button
              v-if="catalog.is_admin && item.config_path"
              size="small"
              @click="router.push(item.config_path)"
            >
              前往配置
            </el-button>
          </footer>
        </article>
      </div>
    </section>

    <el-dialog
      v-model="connectorDialogVisible"
      :title="`发起外部任务：${connectorTarget?.name || ''}`"
      width="min(560px, calc(100vw - 32px))"
    >
      <el-form label-position="top">
        <el-form-item label="任务说明" required>
          <el-input
            v-model="connectorForm.prompt"
            type="textarea"
            :rows="4"
            maxlength="2000"
            show-word-limit
            placeholder="说明需要外部 Agent 处理的显式文件任务"
          />
        </el-form-item>
        <el-form-item label="超时（秒）" required>
          <el-input-number v-model="connectorForm.timeoutSeconds" :min="1" :max="600" />
        </el-form-item>
        <el-checkbox v-model="connectorForm.confirmed">
          我确认发起该外部 Agent 任务，并了解输入、输出、超时与沙箱边界由服务端策略控制。
        </el-checkbox>
      </el-form>
      <template #footer>
        <el-button @click="connectorDialogVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="connectorSubmitting"
          :disabled="!connectorForm.confirmed"
          @click="submitConnectorRun"
        >
          确认执行
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
/* —— 简洁高级风格：与其他页面边距保持一致 —— */
.capability-view {
  display: grid;
  gap: 28px;
}

/* 页头 */
.capability-header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 24px;
  padding-bottom: 24px;
  border-bottom: 1px solid var(--app-border-soft);
}

.capability-header h1 {
  margin: 0;
  color: var(--app-ink);
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.3px;
}

.capability-header p {
  margin: 8px 0 0;
  color: var(--app-ink-muted);
  font-size: 14px;
  line-height: 1.6;
  max-width: 640px;
}

/* 能力来源 */
.module-source {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  padding: 14px 18px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-lg);
  background: rgba(255, 255, 255, 0.7);
}

.module-source > span {
  color: var(--app-ink-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.3px;
}

/* 权限摘要 + 能力网格 */
.permission-panel,
.capability-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.permission-panel article,
.capability-card {
  padding: 20px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-lg);
  background: #fff;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: box-shadow 0.22s ease, transform 0.22s ease;
}

.permission-panel article {
  display: grid;
  gap: 6px;
}

.permission-panel span,
.permission-panel small {
  color: var(--app-ink-muted);
  font-size: 12px;
}

.permission-panel small {
  font-size: 11px;
  line-height: 1.5;
}

.permission-panel strong {
  color: var(--app-ink);
  font-size: 28px;
  font-weight: 700;
  letter-spacing: -0.5px;
}

/* 分组 */
.capability-group {
  display: grid;
  gap: 16px;
}

.group-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.group-heading h2 {
  margin: 0;
  color: var(--app-ink);
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.2px;
}

.group-heading p {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

/* 能力卡片网格 */
.capability-grid {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.capability-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.capability-card:hover {
  box-shadow: 0 8px 24px rgba(15, 23, 42, 0.08);
  transform: translateY(-2px);
}

.capability-card header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.capability-card h3 {
  margin: 0;
  color: var(--app-ink);
  font-size: 15px;
  font-weight: 600;
  overflow-wrap: anywhere;
}

.capability-card header p,
.reason,
.scope-note {
  margin: 6px 0 0;
  color: var(--app-ink-muted);
  font-size: 13px;
  line-height: 1.6;
}

.reason {
  color: var(--app-danger, #c53030);
}

/* 策略清单 */
.policy-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 14px 16px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #f8fafc;
}

.policy-list div {
  display: grid;
  grid-template-columns: 68px 1fr;
  gap: 10px;
  align-items: baseline;
}

.policy-list dt,
.policy-list dd {
  margin: 0;
  font-size: 12px;
}

.policy-list dt {
  color: var(--app-ink-subtle);
  font-weight: 500;
}

.policy-list dd {
  color: var(--app-ink-body);
}

.source-badges {
  min-height: 24px;
}

.capability-card footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: auto;
  padding-top: 4px;
}

@media (max-width: 1100px) {
  .permission-panel,
  .capability-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 700px) {
  .capability-view {
    gap: 22px;
  }

  .capability-header,
  .group-heading {
    align-items: stretch;
    flex-direction: column;
  }

  .permission-panel,
  .capability-grid {
    grid-template-columns: 1fr;
  }
}
</style>
