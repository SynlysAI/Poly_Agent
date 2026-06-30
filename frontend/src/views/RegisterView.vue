<script setup>
import { ElMessage, ElForm, ElFormItem, ElInput, ElButton } from 'element-plus'
import { User, Lock, Ticket } from '@element-plus/icons-vue'
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'

import { registerWithInviteCode, getApiErrorMessage } from '../api/polyAgentApi'

const router = useRouter()
const formRef = ref(null)
const loading = ref(false)

const form = reactive({
  invite_code: '',
  username: '',
  real_name: '',
  organization: '',
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
      real_name: form.real_name.trim() || undefined,
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
  <div style="min-height:100vh;display:grid;place-items:center;background:linear-gradient(180deg,#f3f7fd 0%,#ecf2fa 100%)">
    <div style="width:420px;padding:36px 32px;border-radius:var(--app-radius-lg);border:1px solid var(--app-card-border);background:#fff;box-shadow:var(--app-card-shadow)">
      <div style="text-align:center;margin-bottom:24px">
        <div style="font-size:20px;font-weight:700;color:var(--app-ink);letter-spacing:-0.3px">邀请码注册</div>
        <div style="font-size:13px;color:var(--app-ink-muted);margin-top:4px">使用管理员提供的邀请码创建账号</div>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" size="large" @submit.prevent="handleSubmit">
        <el-form-item prop="invite_code">
          <el-input v-model="form.invite_code" placeholder="邀请码" :prefix-icon="Ticket" />
        </el-form-item>
        <el-form-item prop="username">
          <el-input v-model="form.username" placeholder="用户名" :prefix-icon="User" />
        </el-form-item>
        <el-form-item prop="real_name">
          <el-input v-model="form.real_name" placeholder="姓名（选填）" />
        </el-form-item>
        <el-form-item prop="organization">
          <el-input v-model="form.organization" placeholder="单位（选填）" />
        </el-form-item>
        <el-form-item prop="password">
          <el-input v-model="form.password" type="password" placeholder="密码" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item prop="confirm_password">
          <el-input v-model="form.confirm_password" type="password" placeholder="确认密码" :prefix-icon="Lock" show-password />
        </el-form-item>
        <el-form-item style="margin-top:8px">
          <el-button type="primary" :loading="loading" native-type="submit" style="width:100%;height:42px;font-size:15px">
            注册
          </el-button>
        </el-form-item>
      </el-form>
      <div style="text-align:center;margin-top:8px">
        <router-link to="/login" style="color:var(--app-primary);font-size:13px;text-decoration:none">已有账号？返回登录</router-link>
      </div>
    </div>
  </div>
</template>
