<script setup>
import { ref, onMounted } from 'vue'

const stats = ref([
  { title: '总任务数', value: '--', color: '#3b82f6' },
  { title: '预测准确率', value: '--', color: '#16a34a' },
  { title: '运行中任务', value: '--', color: '#d97706' },
  { title: '模型服务', value: '--', color: '#7c3aed' },
])

const recentTasks = ref([
  { id: '--', type: '--', status: '--', time: '--' },
])

onMounted(() => {
  stats.value = [
    { title: '总任务数', value: '128', color: '#3b82f6' },
    { title: '预测准确率', value: '95%', color: '#16a34a' },
    { title: '运行中任务', value: '12', color: '#d97706' },
    { title: '模型服务', value: '3', color: '#7c3aed' },
  ]
  recentTasks.value = [
    { id: 'T-20260630-001', type: 'GPC 分子量', status: 'completed', time: '2026-06-30 14:30' },
    { id: 'T-20260630-002', type: '热稳定性', status: 'running', time: '2026-06-30 13:15' },
    { id: 'T-20260630-003', type: '力学性能', status: 'pending', time: '2026-06-30 11:00' },
  ]
})
</script>

<template>
  <div>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-header">
        <h3 class="panel-title">工作台概览</h3>
      </div>
      <div class="panel-body">
        <div class="stat-grid">
          <div v-for="stat in stats" :key="stat.title" class="stat-card">
            <div class="stat-title">{{ stat.title }}</div>
            <div class="stat-value" :style="{ color: stat.color }">{{ stat.value }}</div>
          </div>
        </div>
      </div>
    </div>

    <div class="page-grid">
      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title">最近任务</h3>
        </div>
        <div class="panel-body">
          <el-table :data="recentTasks" stripe style="width:100%">
            <el-table-column prop="id" label="任务编号" min-width="160" />
            <el-table-column prop="type" label="预测类型" min-width="120" />
            <el-table-column prop="status" label="状态" min-width="100">
              <template #default="{ row }">
                <el-tag :type="row.status === 'completed' ? 'success' : row.status === 'running' ? 'warning' : 'info'" size="small">
                  {{ row.status === 'completed' ? '已完成' : row.status === 'running' ? '运行中' : '等待中' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="time" label="提交时间" min-width="150" />
          </el-table>
        </div>
      </div>

      <div class="panel">
        <div class="panel-header">
          <h3 class="panel-title">快捷操作</h3>
        </div>
        <div class="panel-body" style="display:flex;flex-direction:column;gap:10px">
          <el-button type="primary" @click="$router.push('/tasks/submit')" style="width:100%">新建预测任务</el-button>
          <el-button @click="$router.push('/tasks/center')" style="width:100%">查看任务列表</el-button>
          <el-button @click="$router.push('/dialogue')" style="width:100%">问答对话</el-button>
          <el-button @click="$router.push('/tools')" style="width:100%">工具服务</el-button>
        </div>
      </div>
    </div>
  </div>
</template>
