<template>
  <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:60vh;gap:16px">
    <div style="font-size:72px;font-weight:700;color:var(--app-ink-subtle)">404</div>
    <div style="font-size:18px;color:var(--app-ink-muted)">页面不存在</div>
    <el-button type="primary" @click="$router.push('/dashboard')">返回工作台</el-button>
  </div>
</template>
