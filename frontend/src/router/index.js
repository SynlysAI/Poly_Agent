import { createRouter, createWebHistory } from 'vue-router'

import { authState } from '../auth/authState'
import DashboardView from '../views/DashboardView.vue'
import CampaignDetailView from '../views/CampaignDetailView.vue'
import CampaignsView from '../views/CampaignsView.vue'
import ComputationRunsView from '../views/ComputationRunsView.vue'
import ComputationSubmitView from '../views/ComputationSubmitView.vue'
import DatabaseManagementView from '../views/DatabaseManagementView.vue'
import DialogueView from '../views/DialogueView.vue'
import LoginView from '../views/LoginView.vue'
import NotFoundView from '../views/NotFoundView.vue'
import OptimizationHomeView from '../views/OptimizationHomeView.vue'
import RegisterView from '../views/RegisterView.vue'
import TaskCenterView from '../views/TaskCenterView.vue'
import TaskSubmitView from '../views/TaskSubmitView.vue'
import ToolServicesView from '../views/ToolServicesView.vue'
import AlchemistToolView from '../views/AlchemistToolView.vue'
import ResearchEngineView from '../views/ResearchEngineView.vue'

const AUTH_PUBLIC_PATHS = new Set(['/login', '/register'])

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: LoginView, meta: { public: true, title: '账号登录' } },
  { path: '/register', component: RegisterView, meta: { public: true, title: '邀请码注册' } },
  { path: '/dashboard', component: DashboardView, meta: { title: '工作台' } },
  { path: '/tasks/submit', component: TaskSubmitView, meta: { section: '任务提交', title: '任务目录' } },
  { path: '/tasks/center', component: TaskCenterView, meta: { section: '任务中心', title: '全局任务' } },
  { path: '/computations/submit', component: ComputationSubmitView, meta: { section: '计算智能', title: '提交计算任务' } },
  { path: '/computations/runs', component: ComputationRunsView, meta: { section: '计算智能', title: '计算任务中心' } },
  { path: '/optimization', component: OptimizationHomeView, meta: { section: '湿实验优化', title: '业务入口' } },
  { path: '/optimization/campaigns', component: CampaignsView, meta: { section: '湿实验优化', title: 'Campaign 闭环管理' } },
  { path: '/optimization/campaigns/:campaignId', component: CampaignDetailView, meta: { section: '湿实验优化', title: 'Campaign Detail' } },
  { path: '/optimization/alchemist', component: AlchemistToolView, meta: { section: '湿实验优化', title: 'Alchemist 实验设计' } },
  { path: '/dialogue', component: DialogueView, meta: { title: '问答对话' } },
  { path: '/tools', component: ToolServicesView, meta: { section: '工具服务', title: '工具列表' } },
  { path: '/tools/alchemist', component: AlchemistToolView, meta: { section: '工具服务', title: '实验设计与优化' } },
  { path: '/research-engine', component: ResearchEngineView, meta: { section: '研发引擎', title: 'ResearchEngine' } },
  { path: '/database', component: DatabaseManagementView, meta: { requiresRole: 'admin', section: '系统管理', title: '数据库管理' } },
  { path: '/:pathMatch(.*)*', component: NotFoundView, meta: { public: true, title: '页面不存在' } },
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
