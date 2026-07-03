import {
  Cpu,
  DataAnalysis,
  SetUp,
} from '@element-plus/icons-vue'

export const TASK_MODULES = [
  {
    id: 'computation',
    name: '计算智能',
    category: '计算与优化',
    status: 'online',
    statusText: '在线',
    icon: Cpu,
    description: '提交真实结构生成、xTB/CREST 和 ORCA 计算任务，追踪 workflow timeline、artifact 和结构化结果。',
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
    status: 'online',
    statusText: '在线',
    icon: SetUp,
    description: '统一进入湿实验优化、贝叶斯 campaign 和 Alchemist 实验设计链路。',
    primaryActionText: '进入优化',
    centerActionText: '任务管理',
    routes: {
      submit: '/optimization',
      center: '/optimization/campaigns',
    },
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

export function mapCampaignToGlobalTask(campaign) {
  return {
    task_id: campaign.campaign_id,
    task_type: '湿实验优化',
    module_id: 'wetlab-bayes',
    module_name: '湿实验贝叶斯优化',
    title: campaign.name || campaign.campaign_id,
    summary: campaign.objectives?.map((item) => item.name).join(', ') || '-',
    status: campaign.status,
    status_text: campaign.status,
    created_at: campaign.created_at,
    updated_at: campaign.updated_at,
    route: {
      path: `/optimization/campaigns/${campaign.campaign_id}`,
    },
    raw: campaign,
  }
}
