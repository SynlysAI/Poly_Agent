<script setup>
import { ElMessage } from 'element-plus'
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Fold, Expand, SwitchButton,
  Monitor, DataAnalysis, Histogram, Collection, SetUp, Aim, MagicStick,
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
const BRAND_LOGO_SRC = '/brand/JG-logo.png'
const BRAND_PARTNER_TEXT = '智储大装置｜嘉庚实验室｜厦门大学｜苏州实验室｜浦江实验室'

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
const canAccessAdmin = computed(() => !authState.authEnabled || authState.role === 'admin')

const HEADER_SECTION_ROUTE_MAP = {
  '任务提交': '/tasks/submit',
  '知识库': '/knowledge',
  '任务中心': '/tasks/center',
  '计算智能': '/tasks/submit',
  '数据管理': '/database/data-catalog',
  '湿实验优化': '/tasks/submit',
  '研发引擎': '/research-engine',
  '工具服务': '/tools',
  '系统管理': '/admin',
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
  const fallbackLabel = title || section || 'Poly Agent'
  return [{ label: fallbackLabel, path: '', isCurrent: true }]
})

const activeMenu = computed(() => {
  const current = route.path
  if (current.startsWith('/computations/submit')) return '/tasks/submit'
  if (current.startsWith('/computations/runs')) return '/tasks/center'
  if (current === '/data-catalog' || current.startsWith('/database/data-catalog')) return '/database/data-catalog'
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
      <img :src="BRAND_LOGO_SRC" alt="Poly Agent" class="app-loading-logo" />
      <div class="app-loading-title">Poly Agent</div>
      <div class="app-loading-text">正在初始化...</div>
    </div>
  </div>
  <router-view v-else-if="isAuthPage" />
  <el-container v-else class="app-shell">
    <el-aside class="app-sidebar" :class="{ collapsed: sidebarCollapsed }" :width="sidebarCollapsed ? '66px' : '220px'">
      <div class="brand">
        <img class="brand-logo" :src="BRAND_LOGO_SRC" alt="Poly Agent" />
        <div v-if="!sidebarCollapsed" class="brand-text">
          <div class="brand-title">Poly Agent</div>
          <div class="brand-subtitle">高分子智能分析平台</div>
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
            <span>工作台</span>
          </el-menu-item>
          <el-menu-item index="/research-engine">
            <el-icon><MagicStick /></el-icon>
            <span>研发引擎</span>
          </el-menu-item>
          <el-menu-item index="/tasks/submit">
            <el-icon><Aim /></el-icon>
            <span>任务提交</span>
          </el-menu-item>
          <el-menu-item index="/tasks/center">
            <el-icon><Histogram /></el-icon>
            <span>任务中心</span>
          </el-menu-item>
          <el-menu-item index="/knowledge">
            <el-icon><Collection /></el-icon>
            <span>知识库</span>
          </el-menu-item>
          <el-menu-item index="/tools">
            <el-icon><SetUp /></el-icon>
            <span>工具服务</span>
          </el-menu-item>
          <el-menu-item index="/database/data-catalog">
            <el-icon><DataAnalysis /></el-icon>
            <span>数据管理</span>
          </el-menu-item>
          <el-menu-item v-if="canAccessAdmin" index="/admin">
            <el-icon><SetUp /></el-icon>
            <span>系统管理</span>
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
          <div class="sidebar-meta-inline">
            <span class="sidebar-meta-inline-label">合作单位</span>
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
