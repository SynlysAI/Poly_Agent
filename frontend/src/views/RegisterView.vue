<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { User, Lock, Ticket, OfficeBuilding, Hide, View } from '@element-plus/icons-vue'

import { registerWithInviteCode, getApiErrorMessage } from '../api/polyAgentApi'

const router = useRouter()
const BRAND_LOGO_SRC = '/brand/JG-logo.png'
const formRef = ref(null)
const loading = ref(false)
const passwordVisible = ref(false)
const confirmVisible = ref(false)

const form = reactive({
  invite_code: '',
  organization: '',
  username: '',
  password: '',
  confirm_password: '',
})

const validateConfirmPassword = (_rule, value, callback) => {
  if (value && value !== form.password) {
    callback(new Error('两次输入的密码不一致'))
  } else {
    callback()
  }
}

const rules = {
  invite_code: [{ required: true, message: '请输入邀请码', trigger: 'blur' }],
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { min: 3, max: 32, message: '用户名长度在 3 到 32 个字符', trigger: 'blur' },
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { min: 6, message: '密码长度不能少于 6 位', trigger: 'blur' },
  ],
  confirm_password: [
    { required: true, message: '请确认密码', trigger: 'blur' },
    { validator: validateConfirmPassword, trigger: 'blur' },
  ],
}

async function handleSubmit() {
  const valid = await formRef.value?.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    await registerWithInviteCode({
      invite_code: form.invite_code.trim(),
      username: form.username.trim(),
      organization: form.organization.trim() || undefined,
      password: form.password,
    })
    ElMessage.success('注册成功，请登录')
    await router.replace('/login')
  } catch (error) {
    ElMessage.error(getApiErrorMessage(error))
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="login-page">
    <div class="login-background"></div>
    <section class="login-panel" style="width: min(460px, calc(100vw - 32px))">
      <div class="login-brand">
        <img :src="BRAND_LOGO_SRC" alt="Poly Agent" class="login-brand-mark" />
        <div>
          <div class="login-brand-title">Poly Agent</div>
          <div class="login-brand-subtitle">高分子智能分析平台</div>
        </div>
      </div>

      <div class="login-heading">
        <h1>邀请码注册</h1>
        <p style="margin:10px 0 0;color:#627697;font-size:14px;line-height:1.7">使用管理员提供的邀请码创建账号</p>
      </div>

      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" class="login-form">
        <el-form-item label="邀请码" prop="invite_code">
          <input v-model="form.invite_code" class="login-native-input" placeholder="请输入管理员提供的邀请码" autocomplete="off" />
        </el-form-item>
        <el-form-item label="单位" prop="organization">
          <input v-model="form.organization" class="login-native-input" placeholder="请输入所在单位名称" autocomplete="off" />
        </el-form-item>
        <el-form-item label="用户名" prop="username">
          <input v-model="form.username" class="login-native-input" placeholder="3-32 个字符" autocomplete="off" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <div class="login-password-field">
            <input
              v-model="form.password"
              class="login-native-input login-native-input-password"
              :type="passwordVisible ? 'text' : 'password'"
              placeholder="至少 6 位密码"
              autocomplete="new-password"
            />
            <button
              type="button" class="login-password-toggle"
              :aria-label="passwordVisible ? '隐藏密码' : '显示密码'"
              @click="passwordVisible = !passwordVisible"
            >
              <el-icon><View v-if="passwordVisible" /><Hide v-else /></el-icon>
            </button>
          </div>
        </el-form-item>
        <el-form-item label="确认密码" prop="confirm_password">
          <div class="login-password-field">
            <input
              v-model="form.confirm_password"
              class="login-native-input login-native-input-password"
              :type="confirmVisible ? 'text' : 'password'"
              placeholder="再次输入密码"
              autocomplete="new-password"
            />
            <button
              type="button" class="login-password-toggle"
              :aria-label="confirmVisible ? '隐藏密码' : '显示密码'"
              @click="confirmVisible = !confirmVisible"
            >
              <el-icon><View v-if="confirmVisible" /><Hide v-else /></el-icon>
            </button>
          </div>
        </el-form-item>
        <el-button type="primary" class="login-submit" :loading="loading" @click="handleSubmit">
          注册
        </el-button>
      </el-form>

      <div class="login-footer">
        <span>已有账号？</span>
        <router-link class="login-link" to="/login">返回登录</router-link>
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
