<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { authState, getAuthorizationHeader } from '../auth/authState'

const AI4MS_API_BASE = String(import.meta.env.VITE_AI4MS_API_URL || 'https://ai4ms.xmuzc.com').replace(/\/+$/, '')
const AI4MS_FEEDBACK_URL = `${AI4MS_API_BASE}/api/v1/feedback`

/* 平台标识（与 AI4MS 后端 FEEDBACK_PLATFORMS 对应）。 */
const FEEDBACK_PLATFORM = 'poly_agent'

const FEEDBACK_TYPES = [
  { value: 'bug', label: '功能异常' },
  { value: 'ux', label: '体验问题' },
  { value: 'idea', label: '功能建议' },
  { value: 'other', label: '其他' },
]
const MAX_CONTENT_LENGTH = 500

const dialogVisible = ref(false)
const feedbackType = ref('bug')
const content = ref('')
const submitting = ref(false)

const contentLength = computed(() => content.value.length)
const canSubmit = computed(() => content.value.trim().length > 0 && !submitting.value)

/* SSO 登录时前端拿不到真实用户名（占位符 __portal__），展示为"当前登录用户"，实际提交人由后端从 Token 解析。 */
const submitterName = computed(() => {
  const name = authState.username
  if (!name || name === '__portal__') {
    return '当前登录用户'
  }
  return name
})

/** 打开反馈弹窗并重置表单。 */
function openDialog() {
  feedbackType.value = 'bug'
  content.value = ''
  dialogVisible.value = true
}

/** 提交反馈至 AI4MS 统一门户后端。 */
async function submitFeedback() {
  const text = content.value.trim()
  if (!text) {
    ElMessage.warning('请填写反馈内容')
    return
  }
  submitting.value = true
  try {
    const headers = { 'Content-Type': 'application/json' }
    const auth = getAuthorizationHeader()
    if (auth) {
      headers.Authorization = auth
    }
    const resp = await fetch(AI4MS_FEEDBACK_URL, {
      method: 'POST',
      headers,
      body: JSON.stringify({
        platform: FEEDBACK_PLATFORM,
        feedback_type: feedbackType.value,
        content: text,
      }),
    })
    if (resp.status === 401) {
      ElMessage.error('登录状态已失效，请重新从 AI4MS 门户进入后再提交')
      return
    }
    if (!resp.ok) {
      ElMessage.error('提交失败，请稍后重试')
      return
    }
    dialogVisible.value = false
    ElMessage.success('提交成功，感谢您的反馈')
  } catch {
    ElMessage.error('网络异常，提交失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <el-tooltip content="意见反馈" placement="bottom" :show-after="300">
    <el-button circle text class="feedback-entry-btn" aria-label="意见反馈" @click="openDialog">
      <el-icon>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
          <line x1="12" y1="7" x2="12" y2="12" />
          <line x1="12" y1="15" x2="12.01" y2="15" />
        </svg>
      </el-icon>
    </el-button>
  </el-tooltip>

  <el-dialog v-model="dialogVisible" title="意见反馈" width="480px"
             :close-on-click-modal="false" append-to-body class="feedback-dialog">
    <div class="fb-subtitle">您的反馈将提交至 AI4MS 平台管理员，感谢帮助我们一起改进</div>

    <div class="fb-label"><span class="fb-required">*</span>反馈类型</div>
    <div class="fb-chips">
      <button v-for="t in FEEDBACK_TYPES" :key="t.value" type="button"
              class="fb-chip" :class="{ 'is-active': feedbackType === t.value }"
              @click="feedbackType = t.value">
        {{ t.label }}
      </button>
    </div>

    <div class="fb-label"><span class="fb-required">*</span>反馈内容</div>
    <el-input v-model="content" type="textarea" :rows="5" :maxlength="MAX_CONTENT_LENGTH"
              resize="none" data-testid="feedback-content"
              placeholder="请详细描述您遇到的问题或建议，如操作路径、预期效果、实际现象…" />
    <div class="fb-word-count">{{ contentLength }} / {{ MAX_CONTENT_LENGTH }}</div>

    <div class="fb-submitter">
      提交人：<b>{{ submitterName }}</b>
    </div>

    <template #footer>
      <el-button @click="dialogVisible = false">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!canSubmit" @click="submitFeedback">
        提交反馈
      </el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.feedback-entry-btn {
  color: #2b4f82;
}

.fb-subtitle {
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin: -6px 0 16px;
}

.fb-label {
  font-size: 13px;
  color: var(--el-text-color-regular);
  margin-bottom: 8px;
}

.fb-required {
  color: var(--el-color-danger);
  margin-right: 3px;
}

.fb-chips {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}

.fb-chip {
  font-size: 12px;
  padding: 5px 14px;
  border-radius: 999px;
  cursor: pointer;
  background: var(--el-fill-color-light);
  color: var(--el-text-color-regular);
  border: 1px solid var(--el-border-color-light);
  transition: all 0.15s;
}

.fb-chip:hover {
  border-color: var(--el-color-primary-light-5);
}

.fb-chip.is-active {
  background: var(--el-color-primary-light-9);
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
  font-weight: 500;
}

.fb-word-count {
  font-size: 11px;
  color: var(--el-text-color-placeholder);
  text-align: right;
  margin-top: 5px;
}

.fb-submitter {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color-lighter);
  border-radius: 8px;
  padding: 8px 12px;
}

.fb-submitter b {
  color: var(--el-text-color-regular);
  font-weight: 500;
}
</style>
