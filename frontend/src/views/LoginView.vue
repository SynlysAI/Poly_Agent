<script setup>
import { ElMessage, ElForm, ElFormItem, ElInput, ElButton } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { loginWithPassword, getApiErrorMessage } from '../api/polyAgentApi'
import { setAuthSession } from '../auth/authState'

const route = useRoute()
const router = useRouter()

const formRef = ref(null)
const loading = ref(false)
const showPassword = ref(false)

const form = reactive({
  username: '',
  password: '',
})

const rules = {
  username: [{ required: true, message: '请输入用户名', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }],
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
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
      tokenType: data.token_type || 'Bearer',
      accessToken: data.access_token,
      expiresAt: data.expires_at,
    })
    const redirect = route.query.redirect
    if (redirect && typeof redirect === 'string' && redirect.startsWith('/')) {
      await router.replace(redirect)
    } else {
      await router.replace('/dashboard')
    }
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-shell" style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(180deg,#f3f7fd 0%,#ecf2fa 100%)">
    <div class="login-card" style="width:380px;padding:36px 32px;border-radius:var(--app-radius-lg);border:1px solid var(--app-card-border);background:#fff;box-shadow:var(--app-card-shadow)">
      <div style="text-align:center;margin-bottom:28px">
        <div style="width:56px;height:56px;margin:0 auto 12px;border-radius:var(--app-radius-md);background:var(--app-primary);color:#fff;display:flex;align-items:center;justify-content:center;font-size:28px;font-weight:700">P</div>
        <div style="font-size:22px;font-weight:700;color:var(--app-ink);letter-spacing:-0.3px">PolyAgent</div>
        <div style="font-size:13px;color:var(--app-ink-muted);margin-top:4px">高分子智能计算平台</div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="handleSubmit">
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item style="margin-top:8px">
          <el-button type="primary" :loading="loading" native-type="submit" style="width:100%;height:42px;font-size:15px">
            登录
          </el-button>
        </el-form-item>
      </el-form>
      <div style="text-align:center;margin-top:8px">
        <router-link to="/register" style="color:var(--app-primary);font-size:13px;text-decoration:none">没有账号？使用邀请码注册</router-link>
      </div>
    </div>
  </div>
</template>
