<script setup>
import { ref } from 'vue'

const messages = ref([
  { role: 'assistant', content: '你好！我是 PolyAgent 智能助手，可以帮你解答高分子材料相关的问题。' },
])

const inputText = ref('')
const sending = ref(false)

function sendMessage() {
  const text = inputText.value.trim()
  if (!text) return
  messages.value.push({ role: 'user', content: text })
  inputText.value = ''
  sending.value = true
  setTimeout(() => {
    messages.value.push({ role: 'assistant', content: '问答功能开发中，后续将接入大语言模型提供专业的高分子材料知识问答。敬请期待。' })
    sending.value = false
  }, 800)
}
</script>

<template>
  <div style="display:flex;gap:16px;height:calc(100vh - 100px)">
    <div class="panel" style="width:260px;flex-shrink:0;display:flex;flex-direction:column">
      <div class="panel-header">
        <h3 class="panel-title">对话列表</h3>
      </div>
      <div class="panel-body" style="flex:1;overflow-y:auto">
        <div style="padding:10px;border-radius:var(--app-radius-sm);background:var(--app-stat-bg);border:1px solid var(--app-stat-border);font-size:13px;color:var(--app-ink);cursor:pointer">
          新高分子材料问答
        </div>
      </div>
    </div>
    <div class="panel" style="flex:1;display:flex;flex-direction:column">
      <div class="panel-header">
        <h3 class="panel-title">问答对话</h3>
      </div>
      <div class="panel-body" style="flex:1;overflow-y:auto;display:flex;flex-direction:column;gap:12px">
        <div v-for="(msg, i) in messages" :key="i" :style="{ alignSelf: msg.role === 'user' ? 'flex-end' : 'flex-start', maxWidth: '70%', padding: '10px 14px', borderRadius: 'var(--app-radius-md)', background: msg.role === 'user' ? 'var(--app-primary)' : '#f1f5f9', color: msg.role === 'user' ? '#fff' : 'var(--app-ink)', fontSize: '14px', lineHeight: '1.6' }">
          {{ msg.content }}
        </div>
      </div>
      <div style="padding:12px 16px;border-top:1px solid var(--app-border-soft);display:flex;gap:10px">
        <el-input v-model="inputText" placeholder="输入问题..." @keyup.enter="sendMessage" style="flex:1" />
        <el-button type="primary" :loading="sending" @click="sendMessage">发送</el-button>
      </div>
    </div>
  </div>
</template>
