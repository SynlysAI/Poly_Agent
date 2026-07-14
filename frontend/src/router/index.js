import { createRouter, createWebHistory } from 'vue-router'

import { authState } from '../auth/authState'

const AUTH_PUBLIC_PATHS = new Set(['/login', '/register'])
const view = (name) => () => import(`../views/${name}.vue`)

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: view('LoginView'), meta: { public: true, title: '账号登录' } },
  { path: '/register', component: view('RegisterView'), meta: { public: true, title: '邀请码注册' } },
  { path: '/dashboard', component: view('DashboardView'), meta: { title: '工作台' } },
  { path: '/tasks/submit', component: view('TaskSubmitView'), meta: { section: '任务提交', title: '任务目录' } },
  { path: '/tasks/center', component: view('TaskCenterView'), meta: { section: '任务中心', title: '全局任务' } },
  { path: '/knowledge', component: view('KnowledgeBaseView'), meta: { section: '知识库', title: '知识库工作台' } },
  { path: '/computations/submit', component: view('ComputationSubmitView'), meta: { section: '任务提交', title: '提交计算任务' } },
  { path: '/computations/runs', component: view('ComputationRunsView'), meta: { section: '任务中心', title: '计算任务中心' } },
  { path: '/data-catalog', redirect: '/database/data-catalog' },
  { path: '/optimization', component: view('OptimizationHomeView'), meta: { section: '任务提交', title: '湿实验优化入口' } },
  { path: '/optimization/campaigns', component: view('CampaignsView'), meta: { section: '任务中心', title: 'Campaign 闭环管理' } },
  { path: '/optimization/campaigns/:campaignId', component: view('CampaignDetailView'), meta: { section: '任务中心', title: 'Campaign 详情' } },
  { path: '/optimization/alchemist', component: view('AlchemistToolView'), meta: { section: '任务提交', title: 'Alchemist 实验设计' } },
  { path: '/vertical-prediction', component: view('VerticalPredictionView'), meta: { section: '任务提交', title: '垂类预测模型' } },
  { path: '/dialogue', component: view('DialogueView'), meta: { section: '工作台', title: '问答对话' } },
  { path: '/tools', component: view('ToolServicesView'), meta: { section: '工具服务', title: '工具列表' } },
  { path: '/tools/alchemist', component: view('AlchemistToolView'), meta: { section: '工具服务', title: '实验设计与优化' } },
  { path: '/research-engine', component: view('ResearchEngineView'), meta: { section: '研发引擎', title: 'ResearchEngine' } },
  { path: '/admin', component: view('DatabaseManagementView'), meta: { section: '系统管理', title: '系统管理', requiresRole: 'admin' } },
  { path: '/database', redirect: '/database/data-catalog' },
  { path: '/database/data-catalog', component: view('DataCatalogView'), meta: { section: '数据管理', title: '数据管理' } },
  { path: '/:pathMatch(.*)*', component: view('NotFoundView'), meta: { public: true, title: '页面不存在' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

router.beforeEach((to) => {
  const isAuthPublicRoute = AUTH_PUBLIC_PATHS.has(to.path)

  if (!authState.authEnabled) {
    if (isAuthPublicRoute) {
      return '/dashboard'
    }
    return true
  }

  if (!authState.initialized) {
    return true
  }

  if (isAuthPublicRoute) {
    if (authState.authenticated) {
      return '/dashboard'
    }
    return true
  }

  if (!authState.authenticated) {
    return {
      path: '/login',
      query: { redirect: to.fullPath },
    }
  }

  if (to.meta.requiresRole && authState.role !== to.meta.requiresRole) {
    return '/dashboard'
  }

  return true
})

export default router
