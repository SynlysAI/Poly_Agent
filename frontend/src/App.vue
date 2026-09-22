<script setup>
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Fold, Expand, SwitchButton,
  Monitor, DataAnalysis, Histogram, Collection, SetUp, Aim, MagicStick,
} from '@element-plus/icons-vue'

import { getAuthStatus, getApiErrorMessage, getCurrentUser } from './api/polyAgentApi'
import { acceptPortalToken, authState, clearAuthSession, setAuthEnabled, setAuthSession } from './auth/authState'
import FeedbackButton from './components/FeedbackButton.vue'
import GuideButton from './components/GuideButton.vue'
import { formatAppDate } from './utils/datetime'
import { useI18n } from './i18n/index.js'
import { getElementLocale } from './i18n/elementLocale.js'
import {
  APP_VERSION_FALLBACK,
  buildAppReleaseUrl,
  fetchLatestAppVersion,
  normalizeAppVersion,
} from './utils/appVersion.mjs'

const route = useRoute()
const router = useRouter()
const { locale, t, setLocale } = useI18n()
const AUTH_PUBLIC_PATHS = new Set(['/login', '/register'])
const sidebarCollapsed = ref(false)
const currentDate = ref(formatCurrentDate())
const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')
const authBootstrapping = ref(true)
const AUTH_EXPIRED_EVENT_NAME = 'poly-agent-auth-expired'
const appVersion = ref(normalizeAppVersion(__APP_VERSION__, APP_VERSION_FALLBACK))
const appReleaseUrl = computed(() => buildAppReleaseUrl(appVersion.value))
const BRAND_LOGO_SRC = '/brand/JG-logo.png'
const BRAND_PARTNER_TEXT = '智储大装置｜嘉庚实验室｜厦门大学｜苏州实验室｜浦江实验室'
let currentDateTimer = null

const currentUserDisplayName = computed(() => {
  if (!authState.authEnabled) return t('app.admin')
  return authState.username || t('app.currentUser')
})

const currentUserRoleLabel = computed(() => {
  if (!authState.authEnabled) return ''
  if (authState.role === 'admin') return t('app.admin')
  if (authState.role === 'user') return t('app.user')
  return ''
})

const currentUserAvatarText = computed(() => currentUserDisplayName.value.slice(0, 1) || 'U')
const isAuthPublicRoute = computed(() => AUTH_PUBLIC_PATHS.has(route.path))
const canAccessAdmin = computed(() => !authState.authEnabled || authState.role === 'admin')

const HEADER_SECTION_ROUTE_MAP = {
  'nav.taskSubmit': '/tasks/submit',
  'nav.knowledge': '/knowledge',
  'nav.taskCenter': '/tasks/center',
  'nav.data': '/database/data-catalog',
  'nav.researchEngine': '/research-engine',
  'nav.tools': '/tools',
  'nav.admin': '/admin',
}

const currentBreadcrumbItems = computed(() => {
  const section = String(route.meta.sectionKey || '').trim()
  const title = String(route.meta.titleKey || '').trim()
  if (section && title) {
    return [
      { label: t(section), path: HEADER_SECTION_ROUTE_MAP[section] || '', isCurrent: false },
      { label: t(title), path: '', isCurrent: true },
    ]
  }
  const fallbackLabel = title ? t(title) : section ? t(section) : 'Poly Agent'
  return [{ label: fallbackLabel, path: '', isCurrent: true }]
})

const activeMenu = computed(() => {
  const current = route.path
  if (current.startsWith('/computations/submit')) return '/tasks/submit'
  if (current.startsWith('/computations/runs')) return '/tasks/center'
  if (current === '/data-catalog' || current.startsWith('/database/data-catalog') || current.startsWith('/database/data-analysis')) return '/database/data-catalog'
  // 湿实验优化路径不再有独立菜单，归入任务提交
  if (current.startsWith('/optimization')) return '/tasks/submit'
  // 问答对话归入工作台
  if (current.startsWith('/dialogue')) return '/dashboard'
  if (current.startsWith('/admin')) return '/admin'
  return current
})

function handleMenuSelect(index) {
  if (index === '/docs') {
    window.open(`${window.location.origin}/docs`, '_blank')
    return
  }
  router.push(index)
}

function handleBreadcrumbNavigate(path) {
  if (!path || path === route.path) return
  router.push(path)
}

function toggleSidebar() {
  sidebarCollapsed.value = !sidebarCollapsed.value
}

function handleLogout() {
  clearAuthSession()
  router.replace('/login')
}

/** 切换界面语言，并保留当前路由和用户输入状态。 */
function handleLocaleChange(nextLocale) {
  setLocale(nextLocale)
}

function formatCurrentDate() {
  return formatAppDate(undefined, locale.value)
}

const elementLocale = computed(() => getElementLocale(locale.value))
watch(locale, () => {
  currentDate.value = formatCurrentDate()
})

/** 拉取 GitHub 最新 Release 并同步侧边栏版本号，失败时保留构建版本。 */
async function refreshLatestAppVersion() {
  const latestVersion = await fetchLatestAppVersion()
  if (latestVersion) appVersion.value = latestVersion
}

async function redirectToLogin() {
  if (isAuthPublicRoute.value) return
  await router.replace({ path: '/login', query: { redirect: route.fullPath } })
}

function syncCurrentUserSession(currentUser) {
  setAuthSession({
    userId: currentUser.user_id,
    username: currentUser.username || authState.username,
    role: currentUser.role || authState.role,
    status: currentUser.status || authState.status,
    tokenType: authState.tokenType,
    accessToken: authState.accessToken,
    expiresAt: authState.expiresAt,
  })
}

async function recoverAuthBootstrap(error) {
  try {
    const statusData = await getAuthStatus()
    setAuthEnabled(statusData.auth_enabled)
    if (!statusData.auth_enabled) {
      if (isAuthPublicRoute.value) await router.replace('/dashboard')
      return
    }
    if (statusData.authenticated && authState.authenticated) return
    clearAuthSession()
    await redirectToLogin()
    if (error && error.status !== 401 && error.status !== 403) {
      ElMessage.error(`鉴权状态初始化失败：${getApiErrorMessage(error)}`)
    }
  } catch (statusError) {
    clearAuthSession()
    setAuthEnabled(true)
    ElMessage.error(`鉴权状态初始化失败：${getApiErrorMessage(statusError)}`)
    await redirectToLogin()
  }
}

async function initializeAuthState() {
  try {
    const data = await getCurrentUser()
    setAuthEnabled(data.auth_enabled)
    if (!data.auth_enabled) {
      if (isAuthPublicRoute.value) await router.replace('/dashboard')
      return
    }
    if (data.authenticated) {
      syncCurrentUserSession(data)
      return
    }
    clearAuthSession()
    await redirectToLogin()
  } catch (error) {
    await recoverAuthBootstrap(error)
  } finally {
    authBootstrapping.value = false
  }
}

function handleAuthExpired() {
  clearAuthSession()
  if (!authState.authEnabled || isAuthPublicRoute.value) return
  router.replace({ path: '/login', query: { redirect: route.fullPath } })
}

/**
 * 在异步认证初始化完成后补执行路由角色守卫。
 *
 * 首次整页加载时路由可能先于 /auth/me 返回而放行受保护路由；
 * 初始化完成后需要按真实角色回退，避免普通用户停留在配置页。
 */
function enforceRouteRoleAfterAuthInit() {
  if (
    authState.authEnabled &&
    authState.initialized &&
    route.meta.requiresRole &&
    authState.role !== route.meta.requiresRole
  ) {
    router.replace('/dashboard')
  }
}

onMounted(() => {
  window.addEventListener(AUTH_EXPIRED_EVENT_NAME, handleAuthExpired)
  currentDate.value = formatCurrentDate()
  currentDateTimer = window.setInterval(() => {
    currentDate.value = formatCurrentDate()
  }, 60000)
  acceptPortalToken()
  initializeAuthState()
  refreshLatestAppVersion()

  watch(
    () => authState.initialized,
    enforceRouteRoleAfterAuthInit,
    { immediate: true },
  )
})

onBeforeUnmount(() => {
  window.removeEventListener(AUTH_EXPIRED_EVENT_NAME, handleAuthExpired)
  if (currentDateTimer) {
    window.clearInterval(currentDateTimer)
    currentDateTimer = null
  }
})
</script>

<template>
  <el-config-provider :locale="elementLocale">
  <div v-if="authBootstrapping" class="app-loading-shell">
    <div class="app-loading-card">
      <img :src="BRAND_LOGO_SRC" alt="Poly Agent" class="app-loading-logo" />
      <div class="app-loading-title">Poly Agent</div>
      <div class="app-loading-text">{{ t('app.initializing') }}</div>
    </div>
  </div>
  <router-view v-else-if="isAuthPage" />
  <el-container v-else class="app-shell">
    <el-aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }" :width="sidebarCollapsed ? '66px' : '220px'">
      <div class="brand">
        <img class="brand-logo" :src="BRAND_LOGO_SRC" alt="Poly Agent" />
        <div v-if="!sidebarCollapsed" class="brand-text">
          <div class="brand-title">Poly Agent</div>
          <div class="brand-subtitle">{{ t('app.subtitle') }}</div>
        </div>
      </div>
      <div class="sidebar-nav">
        <el-menu
          :default-active="activeMenu"
          class="sidebar-menu"
          :collapse="sidebarCollapsed"
          :collapse-transition="false"
          background-color="transparent"
          text-color="#c5d4f0"
          active-text-color="#ffffff"
          @select="handleMenuSelect"
        >
          <el-menu-item index="/dashboard">
            <el-icon><Monitor /></el-icon>
            <span>{{ t('nav.dashboard') }}</span>
          </el-menu-item>
          <el-menu-item index="/research-engine">
            <el-icon><MagicStick /></el-icon>
            <span>{{ t('nav.researchEngine') }}</span>
          </el-menu-item>
          <el-menu-item index="/tasks/submit">
            <el-icon><Aim /></el-icon>
            <span>{{ t('nav.taskSubmit') }}</span>
          </el-menu-item>
          <el-menu-item index="/tasks/center">
            <el-icon><Histogram /></el-icon>
            <span>{{ t('nav.taskCenter') }}</span>
          </el-menu-item>
          <el-menu-item index="/knowledge">
            <el-icon><Collection /></el-icon>
            <span>{{ t('nav.knowledge') }}</span>
          </el-menu-item>
          <el-menu-item index="/tools">
            <el-icon><SetUp /></el-icon>
            <span>{{ t('nav.tools') }}</span>
          </el-menu-item>
          <el-menu-item index="/database/data-catalog">
            <el-icon><DataAnalysis /></el-icon>
            <span>{{ t('nav.data') }}</span>
          </el-menu-item>
          <el-menu-item v-if="canAccessAdmin" index="/admin">
            <el-icon><SetUp /></el-icon>
            <span>{{ t('nav.admin') }}</span>
          </el-menu-item>
          <el-menu-item v-if="canAccessAdmin" index="/admin/lui-evaluation">
            <el-icon><DataAnalysis /></el-icon>
            <span>{{ t('nav.evaluation') }}</span>
          </el-menu-item>
        </el-menu>
      </div>
      <div class="sidebar-version" :class="{ collapsed: sidebarCollapsed }">
        <template v-if="sidebarCollapsed">
          <a
            :href="appReleaseUrl"
            class="sidebar-version-link sidebar-version-mini"
            target="_blank"
            rel="noopener noreferrer"
            :aria-label="t('app.releaseNotes', { version: appVersion })"
            :title="t('app.releaseNotes', { version: appVersion })"
          >v{{ appVersion }}</a>
        </template>
        <template v-else>
          <div class="sidebar-version-top">
            <span class="sidebar-version-label">{{ t('app.version') }}</span>
            <a
              :href="appReleaseUrl"
              class="sidebar-version-link sidebar-version-badge"
              target="_blank"
              rel="noopener noreferrer"
              :aria-label="t('app.releaseNotes', { version: appVersion })"
              :title="t('app.releaseNotes', { version: appVersion })"
            >v{{ appVersion }}</a>
          </div>
          <div class="sidebar-meta-inline">
            <span class="sidebar-meta-inline-label">{{ t('app.partners') }}</span>
            <span class="sidebar-meta-partners">{{ BRAND_PARTNER_TEXT }}</span>
          </div>
        </template>
      </div>
    </el-aside>
    <el-container>
      <el-header class="app-header">
        <div class="header-left">
          <el-button circle text class="collapse-btn" @click="toggleSidebar">
            <el-icon v-if="sidebarCollapsed"><Expand /></el-icon>
            <el-icon v-else><Fold /></el-icon>
          </el-button>
          <el-breadcrumb separator=">" class="header-breadcrumb">
            <el-breadcrumb-item v-for="item in currentBreadcrumbItems" :key="`${item.label}-${item.path || 'current'}`">
              <button v-if="item.path && !item.isCurrent" type="button" class="header-breadcrumb-link" @click="handleBreadcrumbNavigate(item.path)">{{ item.label }}</button>
              <span v-else class="header-breadcrumb-current">{{ item.label }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
        </div>
        <div class="header-right">
          <span class="header-date">{{ currentDate }}</span>
          <el-tag v-if="authState.authEnabled" type="success" effect="plain" size="small">{{ t('app.loginProtection') }}</el-tag>
          <el-tag v-if="currentUserRoleLabel" effect="plain" size="small">{{ currentUserRoleLabel }}</el-tag>
          <GuideButton />
          <FeedbackButton v-if="authState.authEnabled" />
          <div class="locale-switcher" role="group" :aria-label="t('locale.switchTo', { language: locale === 'zh-CN' ? t('locale.english') : t('locale.chinese') })">
            <button type="button" :class="{ active: locale === 'zh-CN' }" :aria-pressed="locale === 'zh-CN'" @click="handleLocaleChange('zh-CN')">中</button>
            <span aria-hidden="true">/</span>
            <button type="button" :class="{ active: locale === 'en-US' }" :aria-pressed="locale === 'en-US'" @click="handleLocaleChange('en-US')">EN</button>
          </div>
          <el-avatar size="small">{{ currentUserAvatarText }}</el-avatar>
          <span style="font-weight:500">{{ currentUserDisplayName }}</span>
          <el-button v-if="authState.authEnabled" text class="logout-btn" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            {{ t('app.logout') }}
          </el-button>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
  </el-config-provider>
</template>
