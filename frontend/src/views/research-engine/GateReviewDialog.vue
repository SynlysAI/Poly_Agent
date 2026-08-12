<script setup>
import { ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { approveStage, getApiErrorMessage, rejectStage } from '../../api/polyAgentApi'

const emit = defineEmits(['decided'])

const props = defineProps({
  visible: { type: Boolean, default: false },
  researchRunId: { type: String, default: '' },
  stageRun: { type: Object, default: null },
})

const loading = ref(false)
const reason = ref('')
const decision = ref('approved')

watch(() => props.visible, (val) => {
  if (val) {
    reason.value = ''
    decision.value = 'approved'
  }
})

function stageLabel(key) {
  const map = {
    PROBLEM_SPEC: '问题定义',
    KNOWLEDGE_RETRIEVAL: '文献检索',
    STRUCTURE_FEATURE: '结构表示',
    COMPUTE_PREDICT: '计算预测',
    RECOMMENDATION_ASK: '候选推荐',
    HUMAN_REVIEW: '人工审核',
    EXPERIMENT_EXECUTION: '实验执行',
    RESULT_TELL: '结果回填',
    MODEL_UPDATE: '模型更新',
    ARCHIVE_LEARNING: '经验归档',
  }
  return map[key] || key
}

function statusLabel(status) {
  const map = {
    pending: '待执行',
    running: '执行中',
    blocked_approval: '等待审批',
    completed: '已完成',
    failed: '已失败',
  }
  return map[status] || status
}

async function handleSubmit() {
  if (!reason.value.trim()) {
    ElMessage.warning('请填写审批原因')
    return
  }
  loading.value = true
  try {
    const payload = {
      stage_key: props.stageRun.stage_key,
      decision: decision.value,
      reason: reason.value.trim(),
    }
    let result
    if (decision.value === 'approved') {
      result = await approveStage(props.researchRunId, props.stageRun.stage_run_id, payload)
      ElMessage.success('已批准该阶段')
    } else {
      result = await rejectStage(props.researchRunId, props.stageRun.stage_run_id, payload)
      ElMessage.success('已拒绝该阶段')
    }
    emit('decided', result)
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}

function handleCancel() {
  emit('decided', null)
}
</script>

<template>
  <el-dialog
    :model-value="visible"
    :title="`阶段审批: ${stageRun ? stageLabel(stageRun.stage_key) : ''}`"
    width="560px"
    :close-on-click-modal="false"
    @close="handleCancel"
  >
    <template v-if="stageRun">
      <el-descriptions :column="2" border size="small" style="margin-bottom:16px">
        <el-descriptions-item label="阶段">{{ stageLabel(stageRun.stage_key) }}</el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag size="small" type="warning">{{ statusLabel(stageRun.status) }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="StageRun ID" :span="2">{{ stageRun.stage_run_id }}</el-descriptions-item>
      </el-descriptions>

      <!-- 阶段输出预览 -->
      <details v-if="stageRun.output_summary && Object.keys(stageRun.output_summary).length" style="margin-bottom:14px">
        <summary>阶段输出摘要</summary>
        <pre class="json-block">{{ JSON.stringify(stageRun.output_summary, null, 2) }}</pre>
      </details>

      <el-form label-position="top">
        <el-form-item label="审批决策">
          <el-radio-group v-model="decision">
            <el-radio value="approved">批准 - 继续推进后续阶段</el-radio>
            <el-radio value="rejected">拒绝 - 标记阶段失败</el-radio>
          </el-radio-group>
        </el-form-item>

        <el-form-item label="审批原因" required>
          <el-input
            v-model="reason"
            type="textarea"
            :rows="3"
            placeholder="请填写审批原因（必填），例如：候选材料符合实验约束条件，批准提交计算验证"
          />
        </el-form-item>
      </el-form>
    </template>

    <template #footer>
      <el-button @click="handleCancel">取消</el-button>
      <el-button
        :type="decision === 'approved' ? 'success' : 'danger'"
        :loading="loading"
        @click="handleSubmit"
      >
        {{ decision === 'approved' ? '批准' : '拒绝' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.json-block {
  margin: 6px 0 0;
  padding: 10px;
  background: #f8fbff;
  color: var(--app-ink-body);
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-sm);
  font-family: var(--app-mono-font);
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 200px;
  overflow: auto;
}

summary {
  cursor: pointer;
  font-size: 13px;
  color: var(--app-primary-active);
  font-weight: 500;
}
</style>
