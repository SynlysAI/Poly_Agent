import { createRouter, createWebHistory } from 'vue-router'

import { authState } from '../auth/authState'

const AUTH_PUBLIC_PATHS = new Set(['/login', '/register'])
const view = (name) => () => import(`../views/${name}.vue`)

const routes = [
  { path: '/', redirect: '/dashboard' },
  { path: '/login', component: view('LoginView'), meta: { public: true, titleKey: 'auth.login' } },
  { path: '/register', component: view('RegisterView'), meta: { public: true, titleKey: 'auth.register' } },
  { path: '/dashboard', component: view('DashboardView'), meta: { titleKey: 'nav.dashboard' } },
  { path: '/tasks/submit', component: view('TaskSubmitView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'tasks.catalog' } },
  { path: '/tasks/center', component: view('TaskCenterView'), meta: { sectionKey: 'nav.taskCenter', titleKey: 'tasks.global' } },
  { path: '/knowledge', component: view('KnowledgeBaseView'), meta: { sectionKey: 'nav.knowledge', titleKey: 'knowledge.workspace' } },
  { path: '/computations/submit', component: view('ComputationSubmitView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'computations.submit' } },
  { path: '/computations/runs', component: view('ComputationRunsView'), meta: { sectionKey: 'nav.taskCenter', titleKey: 'computations.center' } },
  { path: '/data-catalog', redirect: '/database/data-catalog' },
  { path: '/optimization', component: view('OptimizationHomeView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'optimization.home' } },
  { path: '/optimization/campaigns', component: view('CampaignsView'), meta: { sectionKey: 'nav.taskCenter', titleKey: 'optimization.campaigns' } },
  { path: '/optimization/campaigns/:campaignId', component: view('CampaignDetailView'), meta: { sectionKey: 'nav.taskCenter', titleKey: 'optimization.detail' } },
  { path: '/optimization/alchemist', component: view('AlchemistToolView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'optimization.alchemist' } },
  { path: '/optimization/experiment-dispatch', component: view('ExperimentDispatchView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'optimization.dispatch' } },
  { path: '/optimization/experiment-dispatch/profiles', component: view('ExperimentDispatchProfilesView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'optimization.profiles' } },
  { path: '/vertical-prediction', component: view('VerticalPredictionView'), meta: { sectionKey: 'nav.taskSubmit', titleKey: 'prediction.vertical' } },
  { path: '/dialogue/:chatId?', component: view('DialogueView'), meta: { sectionKey: 'nav.dashboard', titleKey: 'dialogue.title' } },
  {
    path: '/capabilities',
    redirect: { path: '/tools', query: { tab: 'ai-ready' } },
  },
  { path: '/tools', component: view('ToolServicesView'), meta: { sectionKey: 'nav.tools', titleKey: 'nav.tools' } },
  { path: '/tools/alchemist', component: view('AlchemistToolView'), meta: { sectionKey: 'nav.tools', titleKey: 'tools.alchemist' } },
  { path: '/research-engine', component: view('ResearchEngineView'), meta: { sectionKey: 'nav.researchEngine', titleKey: 'research.title' } },
  { path: '/admin', component: view('DatabaseManagementView'), meta: { sectionKey: 'nav.admin', titleKey: 'nav.admin', requiresRole: 'admin' } },
  { path: '/admin/lui-evaluation', component: view('LuiEvaluationReportView'), meta: { sectionKey: 'nav.admin', titleKey: 'admin.evaluation', requiresRole: 'admin' } },
  { path: '/database', redirect: '/database/data-catalog' },
  { path: '/database/data-catalog', component: view('DataCatalogView'), meta: { sectionKey: 'nav.data', titleKey: 'data.management' } },
  { path: '/database/data-api', component: view('DataApiView'), meta: { sectionKey: 'nav.data', titleKey: 'data.api' } },
  { path: '/database/data-analysis', component: view('DataAnalysisView'), meta: { sectionKey: 'nav.data', titleKey: 'data.analysis' } },
  { path: '/:pathMatch(.*)*', component: view('NotFoundView'), meta: { public: true, titleKey: 'notFound.title' } },
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
