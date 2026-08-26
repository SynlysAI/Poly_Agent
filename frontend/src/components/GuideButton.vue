<script setup>
/* PolyAgent 操作指导文档（飞书知识库） */
const GUIDE_DOC_URL = 'https://gcnpf55d0gns.feishu.cn/wiki/OdYgwuFCaijJ1wk2e8icmgTVnbO'

/** 新窗口打开平台操作指导文档。 */
function openGuide() {
  window.open(GUIDE_DOC_URL, '_blank', 'noopener,noreferrer')
}
</script>

<template>
  <el-tooltip content="操作指导" placement="bottom" :show-after="300">
    <el-button circle text class="guide-entry-btn" aria-label="操作指导" @click="openGuide">
      <el-icon>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
             stroke-linecap="round" stroke-linejoin="round">
          <path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z" />
          <path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z" />
        </svg>
      </el-icon>
    </el-button>
  </el-tooltip>
</template>

<style scoped>
.guide-entry-btn {
  color: #2b4f82;
}
</style>
