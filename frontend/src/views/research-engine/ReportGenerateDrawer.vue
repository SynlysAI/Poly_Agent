<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'

import { getApiErrorMessage, getReportReadiness } from '../../api/polyAgentApi'

const props = defineProps({
  modelValue: {
    type: Boolean,
    default: false,
  },
  subject: {
    type: Object,
    default: null,
  },
  submitting: {
    type: Boolean,
    default: false,
  },
})

const emit = defineEmits(['update:modelValue', 'submit'])

const visible = computed({
  get: () => props.modelValue,
  set: value => emit('update:modelValue', value),
})

const form = reactive(defaultForm())
const readiness = ref(null)
const readinessLoading = ref(false)

const subjectLabel = computed(() => {
  if (!props.subject) return '-'
  return `${props.subject.subject_type === 'research_run' ? 'ResearchRun' : 'AlgorithmRun'} · ${props.subject.subject_id}`
})

const isIncompleteSubject = computed(() => {
  const status = props.subject?.status
  return Boolean(status && !['completed', 'failed'].includes(status))
})

const readinessWarnings = computed(() => readiness.value?.warnings || [])
const providerBlocked = computed(() =>
  Boolean(readiness.value && (
    !readiness.value.reports_enabled
    || !readiness.value.output_root_ready
    || !readiness.value.provider_ready
    || !readiness.value.skill_pipeline_ready
  )),
)
const pdfBlocked = computed(() =>
  Boolean(form.formats.includes('pdf') && readiness.value && !readiness.value.pdf_ready),
)
const submitDisabled = computed(() =>
  Boolean(!props.subject || !form.formats.length || props.submitting || providerBlocked.value || pdfBlocked.value),
)

watch(
  () => props.modelValue,
  (next) => {
    if (next) {
      Object.assign(form, defaultForm())
      applySubjectDefaults()
      loadReadiness()
    }
  },
)

function defaultForm() {
  return {
    template_id: 'research_run_summary_zh',
    skill_pipeline_id: 'nature_research_report_zh',
    provider: 'auto',
    language: 'zh-CN',
    formats: ['markdown', 'pdf'],
    scope: {
      include_stages: true,
      include_algorithm_runs: true,
      include_computations: true,
      include_observations: true,
      include_audit_events: true,
      include_citations: false,
      include_figures: false,
      include_literature_background: false,
      include_failure_analysis: false,
      appendix_level: 'standard',
    },
    user_instructions: '',
  }
}

function applySubjectDefaults() {
  if (props.subject?.subject_type === 'algorithm_run') {
    form.template_id = 'algorithm_run_summary_zh'
  } else {
    form.template_id = 'research_run_summary_zh'
  }
}

async function loadReadiness() {
  readinessLoading.value = true
  try {
    readiness.value = await getReportReadiness()
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    readinessLoading.value = false
  }
}

function submit() {
  if (submitDisabled.value) return
  emit('submit', {
    subject_type: props.subject.subject_type,
    subject_id: props.subject.subject_id,
    template_id: form.template_id,
    skill_pipeline_id: form.skill_pipeline_id,
    provider: form.provider,
    language: form.language,
    formats: [...form.formats],
    scope: { ...form.scope },
    user_instructions: form.user_instructions?.trim() || null,
  })
}
</script>

<template>
  <el-drawer v-model="visible" title="生成报告" size="520px">
    <div class="report-drawer">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="报告对象">{{ subjectLabel }}</el-descriptions-item>
        <el-descriptions-item label="状态">{{ subject?.status || '-' }}</el-descriptions-item>
      </el-descriptions>
      <el-alert
        v-if="isIncompleteSubject"
        title="当前运行尚未结束，生成的报告可能不完整。"
        type="warning"
        :closable="false"
        show-icon
      />
      <section v-loading="readinessLoading" class="report-readiness-box">
        <div class="readiness-row">
          <span>报告服务</span>
          <el-tag size="small" :type="providerBlocked ? 'danger' : 'success'" effect="plain">
            {{ providerBlocked ? '未就绪' : '可生成' }}
          </el-tag>
        </div>
        <div v-if="readiness" class="readiness-meta">
          <span>{{ readiness.provider }} / {{ readiness.skill_pipeline }}</span>
          <span>PDF：{{ readiness.pdf_ready ? '可用' : '不可用' }}</span>
        </div>
        <p v-if="readinessWarnings.length || pdfBlocked" class="readiness-warning">
          {{ pdfBlocked ? '当前 PDF 输出不可用，请取消 PDF 或检查 Playwright Chromium。' : readinessWarnings[0] }}
        </p>
      </section>

      <el-form label-position="top" class="report-form">
        <el-form-item label="报告模板">
          <el-select v-model="form.template_id" style="width: 100%">
            <el-option label="研发摘要报告（中文）" value="research_run_summary_zh" />
            <el-option label="算法运行报告（中文）" value="algorithm_run_summary_zh" />
            <el-option label="失败分析报告（中文）" value="research_run_failure_analysis_zh" />
          </el-select>
        </el-form-item>

        <div class="form-grid">
          <el-form-item label="语言">
            <el-segmented v-model="form.language" :options="[{ label: '中文', value: 'zh-CN' }, { label: 'English', value: 'en-US' }]" />
          </el-form-item>
          <el-form-item label="附录">
            <el-radio-group v-model="form.scope.appendix_level">
              <el-radio-button value="compact">精简</el-radio-button>
              <el-radio-button value="standard">标准</el-radio-button>
              <el-radio-button value="full">完整</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </div>

        <el-form-item label="输出格式">
          <el-checkbox-group v-model="form.formats">
            <el-checkbox-button value="markdown">Markdown</el-checkbox-button>
            <el-checkbox-button value="pdf">PDF</el-checkbox-button>
          </el-checkbox-group>
        </el-form-item>

        <el-form-item label="内容范围">
          <div class="checkbox-grid">
            <el-checkbox v-model="form.scope.include_stages">阶段</el-checkbox>
            <el-checkbox v-model="form.scope.include_algorithm_runs">算法</el-checkbox>
            <el-checkbox v-model="form.scope.include_computations">计算</el-checkbox>
            <el-checkbox v-model="form.scope.include_observations">观测</el-checkbox>
            <el-checkbox v-model="form.scope.include_audit_events">审计</el-checkbox>
          </div>
        </el-form-item>

        <el-form-item label="增强能力">
          <div class="checkbox-grid">
            <el-checkbox v-model="form.scope.include_citations">引用</el-checkbox>
            <el-checkbox v-model="form.scope.include_figures">图表</el-checkbox>
            <el-checkbox v-model="form.scope.include_literature_background">文献背景</el-checkbox>
            <el-checkbox v-model="form.scope.include_failure_analysis">失败诊断</el-checkbox>
          </div>
        </el-form-item>

        <el-collapse>
          <el-collapse-item title="高级配置" name="advanced">
            <el-form-item label="Skill 流水线">
              <el-select v-model="form.skill_pipeline_id" style="width: 100%">
                <el-option label="Nature 研发报告" value="nature_research_report_zh" />
                <el-option label="带引用报告" value="nature_research_report_with_citations_zh" />
                <el-option label="带图表报告" value="nature_research_report_with_figures_zh" />
                <el-option label="失败分析" value="research_run_failure_analysis_zh" />
              </el-select>
            </el-form-item>
          </el-collapse-item>
        </el-collapse>

        <el-form-item label="备注指令">
          <el-input
            v-model="form.user_instructions"
            type="textarea"
            :rows="4"
            maxlength="4000"
            show-word-limit
          />
        </el-form-item>
      </el-form>
    </div>

    <template #footer>
      <div class="drawer-footer">
        <el-button @click="visible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" :disabled="submitDisabled" @click="submit">
          开始生成
        </el-button>
      </div>
    </template>
  </el-drawer>
</template>

<style scoped>
.report-drawer {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.report-form {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.report-readiness-box {
  padding: 12px;
  border: 1px solid var(--app-border-soft);
  border-radius: var(--app-radius-md);
  background: #fbfdff;
}

.readiness-row,
.readiness-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.readiness-row {
  color: var(--app-ink);
  font-size: 13px;
  font-weight: 600;
}

.readiness-meta {
  flex-wrap: wrap;
  margin-top: 6px;
  color: var(--app-ink-muted);
  font-size: 12px;
}

.readiness-warning {
  margin: 8px 0 0;
  color: #b45309;
  font-size: 12px;
  line-height: 1.5;
}

.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.checkbox-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px 12px;
}

.drawer-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

@media (max-width: 720px) {
  .form-grid,
  .checkbox-grid {
    grid-template-columns: 1fr;
  }
}
</style>
