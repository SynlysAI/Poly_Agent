<script setup>
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Hide, View } from '@element-plus/icons-vue'

import { getApiErrorMessage, loginWithPassword } from '../api/polyAgentApi'
import { setAuthSession } from '../auth/authState'

const route = useRoute()
const router = useRouter()
const BRAND_LOGO_SRC = '/brand/JG-logo.png'
const submitting = ref(false)
const passwordVisible = ref(false)
const formRef = ref(null)
const form = reactive({
  username: '',
  password: '',
})
const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

function resolveRedirectPath() {
  const redirect = String(route.query.redirect || '').trim()
  if (!redirect.startsWith('/')) return '/dashboard'
  return redirect
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  submitting.value = true
  try {
    const data = await loginWithPassword({
      username: form.username.trim(),
      password: form.password,
    })
    setAuthSession({
      userId: data.user_id,
      username: data.username,
      role: data.role,
      status: data.status,
      tokenType: data.token_type,
      accessToken: data.access_token,
      expiresAt: data.expires_at,
    })
    ElMessage.success('登录成功')
    router.replace(resolveRedirectPath())
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-background"></div>
    <section class="login-panel">
      <div class="login-brand">
        <img :src="BRAND_LOGO_SRC" alt="Poly Agent" class="login-brand-mark" />
        <div>
          <div class="login-brand-title">Poly Agent</div>
          <div class="login-brand-subtitle">高分子智能分析平台</div>
        </div>
      </div>

      <div class="login-heading">
        <h1>账号登录</h1>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="login-form">
        <el-form-item label="账号" prop="username">
          <input
            v-model="form.username"
            class="login-native-input"
            placeholder="请输入登录账号"
            autocomplete="username"
          />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <div class="login-password-field">
            <input
              v-model="form.password"
              class="login-native-input login-native-input-password"
              :type="passwordVisible ? 'text' : 'password'"
              placeholder="请输入登录密码"
              autocomplete="current-password"
              @keyup.enter="handleSubmit"
            />
            <button
              type="button"
              class="login-password-toggle"
              :aria-label="passwordVisible ? '隐藏密码' : '显示密码'"
              @click="passwordVisible = !passwordVisible"
            >
              <el-icon>
                <View v-if="passwordVisible" />
                <Hide v-else />
              </el-icon>
            </button>
          </div>
        </el-form-item>
        <el-button type="primary" class="login-submit" :loading="submitting" @click="handleSubmit">
          登录并进入系统
        </el-button>
      </el-form>

      <div class="login-footer">
        <span>没有账号？</span>
        <router-link class="login-link" to="/register">使用邀请码注册</router-link>
      </div>
    </section>
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(59, 130, 246, 0.22), transparent 34%),
    radial-gradient(circle at right 20%, rgba(14, 165, 233, 0.14), transparent 28%),
    linear-gradient(160deg, #071c3a 0%, #0a2a56 48%, #f2f7ff 48%, #eef3fb 100%);
}

.login-background {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(255, 255, 255, 0.06) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, 0.06) 1px, transparent 1px);
  background-size: 32px 32px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, 0.7), transparent 80%);
}

.login-panel {
  position: relative;
  width: min(440px, calc(100vw - 32px));
  padding: 30px 28px 28px;
  border-radius: 24px;
  border: 1px solid rgba(255, 255, 255, 0.42);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(20px);
  box-shadow:
    0 22px 58px rgba(7, 31, 67, 0.24),
    inset 0 1px 0 rgba(255, 255, 255, 0.55);
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 14px;
}

.login-brand-mark {
  width: 48px;
  height: 48px;
  border-radius: 16px;
  object-fit: cover;
  box-shadow: 0 14px 28px rgba(21, 94, 239, 0.18);
}

.login-brand-title {
  color: #0d2449;
  font-size: 22px;
  font-weight: 700;
}

.login-brand-subtitle {
  margin-top: 4px;
  color: #6f82a3;
  font-size: 13px;
}

.login-heading {
  margin-top: 28px;
}

.login-heading h1 {
  margin: 0;
  color: #0f2345;
  font-size: 28px;
}

.login-form {
  margin-top: 24px;
}

.login-native-input {
  width: 100%;
  height: 32px;
  padding: 1px 11px;
  color: var(--app-ink);
  font: inherit;
  font-weight: 500;
  line-height: 30px;
  border: none;
  border-radius: 4px;
  outline: none;
  background: #ffffff;
  box-shadow: 0 0 0 1px var(--app-border) inset;
  transition: box-shadow 0.2s ease;
}

.login-native-input:hover {
  box-shadow: 0 0 0 1px #c0c4cc inset;
}

.login-native-input:focus {
  box-shadow: 0 0 0 1px var(--app-primary) inset;
}

.login-native-input::placeholder {
  color: var(--app-ink-subtle);
  font-weight: 400;
}

.login-password-field {
  position: relative;
  width: 100%;
}

.login-native-input-password {
  padding-right: 40px;
}

.login-password-toggle {
  position: absolute;
  top: 50%;
  right: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  color: #a8abb2;
  border: none;
  background: transparent;
  cursor: pointer;
  transform: translateY(-50%);
}

.login-password-toggle:hover {
  color: #606266;
}

.login-submit {
  width: 100%;
  height: 44px;
  margin-top: 8px;
  border: none;
  border-radius: 14px;
  background: linear-gradient(90deg, #155eef, #0ea5e9);
  box-shadow: 0 14px 24px rgba(21, 94, 239, 0.22);
}

.login-footer {
  margin-top: 18px;
  display: flex;
  justify-content: center;
  gap: 6px;
  color: #627697;
  font-size: 14px;
}

.login-link {
  color: #155eef;
  font-weight: 600;
  text-decoration: none;
}

@media (max-width: 640px) {
  .login-page {
    align-items: start;
    padding-top: 72px;
  }
  .login-panel {
    padding: 24px 20px 22px;
    border-radius: 20px;
  }
  .login-heading h1 {
    font-size: 24px;
  }
}
</style>
