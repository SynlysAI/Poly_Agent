import {
  Cpu,
  DataAnalysis,
  MagicStick,
  SetUp,
  TrendCharts,
} from '@element-plus/icons-vue'

export const TASK_MODULES = [
  {
    id: 'computation',
    name: '计算智能',
    category: '计算与优化',
    status: 'online',
    statusText: '在线',
    icon: Cpu,
    description: '提交 mock/local 计算任务，追踪 workflow timeline、artifact 和结构化结果。',
    primaryActionText: '提交计算任务',
    centerActionText: '计算任务中心',
    routes: {
      submit: '/computations/submit',
      center: '/computations/runs',
    },
  },
  {
    id: 'wetlab-bayes',
    name: '湿实验贝叶斯优化',
    category: '实验闭环',
    status: 'coming',
    statusText: '即将上线',
    icon: SetUp,
    description: '面向湿实验 campaign 的候选推荐、实验观察值回写和下一轮策略生成。',
    primaryActionText: '查看规划',
    centerActionText: '任务管理',
    routes: {},
  },
  {
    id: 'vertical-prediction',
    name: '垂类预测模型',
    category: '预测模型',
    status: 'coming',
    statusText: '即将上线',
    icon: DataAnalysis,
    description: '聚合物热、力学、流变等垂类模型入口，后续接入模型服务。',
    primaryActionText: '查看模型',
    centerActionText: '任务管理',
    routes: {},
  },
  {
    id: 'campaign-planner',
    name: '分子库推荐',
    category: '计算与优化',
    status: 'preview',
    statusText: '预览',
    icon: MagicStick,
    description: '基于候选库和历史 observation 生成 fallback suggestion，用于计算或实验验证。',
    primaryActionText: '生成推荐',
    centerActionText: '推荐记录',
    routes: {
      submit: '/computations/submit',
      center: '/computations/runs',
    },
  },
  {
    id: 'property-screening',
    name: '性质筛选批任务',
    category: '预测模型',
    status: 'coming',
    statusText: '即将上线',
    icon: TrendCharts,
    description: '批量导入候选材料，执行多指标筛选并汇总排序结果。',
    primaryActionText: '查看说明',
    centerActionText: '任务管理',
    routes: {},
  },
]

export const TASK_CATEGORIES = ['全部', ...Array.from(new Set(TASK_MODULES.map((item) => item.category)))]

export function getTaskModule(moduleId) {
  return TASK_MODULES.find((item) => item.id === moduleId) || null
}

export function getTaskStatusTagType(status) {
  const map = {
    online: 'success',
    preview: 'warning',
    coming: 'info',
  }
  return map[status] || 'info'
}

export function mapComputationRunToGlobalTask(run) {
  return {
    task_id: run.run_id,
    task_type: '计算智能',
    module_id: 'computation',
    module_name: '计算智能',
    title: run.molecule?.name || run.run_id,
    summary: run.molecule?.smiles || '-',
    status: run.status,
    status_text: run.status,
    created_at: run.created_at,
    updated_at: run.updated_at,
    route: {
      path: '/computations/runs',
      query: { run_id: run.run_id },
    },
    raw: run,
  }
}
