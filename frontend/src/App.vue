<script setup>
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Fold, Expand, SwitchButton,
} from '@element-plus/icons-vue'

import { getAuthStatus, getApiErrorMessage, getCurrentUser } from './api/polyAgentApi'
import { acceptPortalToken, authState, clearAuthSession, setAuthEnabled, setAuthSession } from './auth/authState'

const route = useRoute()
const router = useRouter()
const AUTH_PUBLIC_PATHS = new Set(['/login', '/register'])
const sidebarCollapsed = ref(false)
const currentDate = ref(formatCurrentDate())
const isAuthPage = computed(() => route.path === '/login' || route.path === '/register')
const authBootstrapping = ref(true)
const AUTH_EXPIRED_EVENT_NAME = 'poly-agent-auth-expired'
const APP_VERSION = '0.1.0'

const canAccessAdminFeatures = computed(() => !authState.authEnabled || authState.role === 'admin')

const currentUserDisplayName = computed(() => {
  if (!authState.authEnabled) return '管理员'
  return authState.username || '当前用户'
})

const currentUserRoleLabel = computed(() => {
  if (!authState.authEnabled) return ''
  if (authState.role === 'admin') return '管理员'
  if (authState.role === 'user') return '普通用户'
  return ''
})

const currentUserAvatarText = computed(() => currentUserDisplayName.value.slice(0, 1) || 'U')
const isAuthPublicRoute = computed(() => AUTH_PUBLIC_PATHS.has(route.path))

const HEADER_SECTION_ROUTE_MAP = {
  '任务提交': '/tasks/submit',
  '任务中心': '/tasks/center',
  '工具服务': '/tools',
  '系统管理': '/database',
}

const currentBreadcrumbItems = computed(() => {
  const section = String(route.meta.section || '').trim()
  const title = String(route.meta.title || '').trim()
  if (section && title) {
    return [
      { label: section, path: HEADER_SECTION_ROUTE_MAP[section] || '', isCurrent: false },
      { label: title, path: '', isCurrent: true },
    ]
  }
  const fallbackLabel = title || section || 'PolyAgent'
  return [{ label: fallbackLabel, path: '', isCurrent: true }]
})

const activeMenu = computed(() => {
  const current = route.path
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

function formatCurrentDate() {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
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

onMounted(() => {
  window.addEventListener(AUTH_EXPIRED_EVENT_NAME, handleAuthExpired)
  acceptPortalToken()
  initializeAuthState()
})

onBeforeUnmount(() => {
  window.removeEventListener(AUTH_EXPIRED_EVENT_NAME, handleAuthExpired)
})
</script>

<template>
  <div v-if="authBootstrapping" class="app-loading-shell">
    <div class="app-loading-card">
      <div style="font-size:42px;margin-bottom:8px">🧬</div>
      <div class="app-loading-title">PolyAgent</div>
      <div class="app-loading-text">正在初始化...</div>
    </div>
  </div>
  <router-view v-else-if="isAuthPage" />
  <el-container v-else class="app-shell">
    <el-aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }" :width="sidebarCollapsed ? '66px' : '220px'">
      <div class="brand">
        <div class="brand-logo" style="display:flex;align-items:center;justify-content:center;color:var(--app-sidebar-from);font-weight:700;font-size:20px">P</div>
        <div v-if="!sidebarCollapsed" class="brand-text">
          <div class="brand-title">PolyAgent</div>
          <div class="brand-subtitle">高分子智能计算平台</div>
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
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><rect x="2" y="3" width="20" height="14" rx="2" fill="none" stroke="currentColor" stroke-width="2"/><path d="M8 21h8M12 17v4" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>工作台</span>
          </el-menu-item>
          <el-menu-item index="/tasks/submit">
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M9 3h-4a2 2 0 00-2 2v4a2 2 0 002 2h4a2 2 0 002-2V5a2 2 0 00-2-2zM19 3h-4a2 2 0 00-2 2v4a2 2 0 002 2h4a2 2 0 002-2V5a2 2 0 00-2-2zM9 13h-4a2 2 0 00-2 2v4a2 2 0 002 2h4a2 2 0 002-2v-4a2 2 0 00-2-2zM19 13h-4a2 2 0 00-2 2v4a2 2 0 002 2h4a2 2 0 002-2v-4a2 2 0 00-2-2z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>任务提交</span>
          </el-menu-item>
          <el-menu-item index="/tasks/center">
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><rect x="18" y="3" width="4" height="18" rx="1" fill="none" stroke="currentColor" stroke-width="2"/><rect x="11" y="8" width="4" height="13" rx="1" fill="none" stroke="currentColor" stroke-width="2"/><rect x="4" y="13" width="4" height="8" rx="1" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>任务中心</span>
          </el-menu-item>
          <el-menu-item index="/dialogue">
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>问答对话</span>
          </el-menu-item>
          <el-menu-item index="/tools">
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><circle cx="12" cy="12" r="3" fill="none" stroke="currentColor" stroke-width="2"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>工具服务</span>
          </el-menu-item>
          <el-menu-item v-if="canAccessAdminFeatures" index="/database">
            <svg class="menu-icon" viewBox="0 0 24 24" style="width:18px;height:18px"><path d="M22 19a2 2 0 01-2 2H4a2 2 0 01-2-2V5a2 2 0 012-2h5l2 3h9a2 2 0 012 2z" fill="none" stroke="currentColor" stroke-width="2"/></svg>
            <span>数据库管理</span>
          </el-menu-item>
        </el-menu>
      </div>
      <div class="sidebar-version" :class="{ collapsed: sidebarCollapsed }">
        <template v-if="sidebarCollapsed">
          <span class="sidebar-version-mini">{{ APP_VERSION }}</span>
        </template>
        <template v-else>
          <div class="sidebar-version-top">
            <span class="sidebar-version-label">版本</span>
            <span class="sidebar-version-badge">v{{ APP_VERSION }}</span>
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
          <el-tag v-if="authState.authEnabled" type="success" effect="plain" size="small">已启用登录保护</el-tag>
          <el-tag v-if="currentUserRoleLabel" effect="plain" size="small">{{ currentUserRoleLabel }}</el-tag>
          <el-avatar size="small">{{ currentUserAvatarText }}</el-avatar>
          <span style="font-weight:500">{{ currentUserDisplayName }}</span>
          <el-button v-if="authState.authEnabled" text class="logout-btn" @click="handleLogout">
            <el-icon><SwitchButton /></el-icon>
            退出登录
          </el-button>
        </div>
      </el-header>
      <el-main class="app-main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>
