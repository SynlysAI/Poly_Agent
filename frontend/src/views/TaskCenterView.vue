<script setup>
import { ref, onMounted } from 'vue'

const tasks = ref([])
const loading = ref(false)
const statusFilter = ref('')
const typeFilter = ref('')

const statusOptions = [
  { label: '全部', value: '' },
  { label: '等待中', value: 'pending' },
  { label: '运行中', value: 'running' },
  { label: '已完成', value: 'completed' },
  { label: '失败', value: 'failed' },
]

const typeOptions = [
  { label: '全部', value: '' },
  { label: '分子量分布', value: 'molecular_weight' },
  { label: '热稳定性', value: 'thermal' },
  { label: '力学性能', value: 'mechanical' },
  { label: '流变性能', value: 'rheological' },
]

onMounted(() => {
  tasks.value = [
    { task_id: 'T-20260630-001', type: '分子量分布', sample: 'PE-2026-001', status: 'completed', created_at: '2026-06-30 14:30' },
    { task_id: 'T-20260630-002', type: '热稳定性', sample: 'PP-2026-015', status: 'running', created_at: '2026-06-30 13:15' },
    { task_id: 'T-20260630-003', type: '力学性能', sample: 'PS-2026-008', status: 'pending', created_at: '2026-06-30 11:00' },
  ]
})

function getStatusTag(status) {
  const map = { pending: 'info', running: 'warning', completed: 'success', failed: 'danger' }
  return map[status] || 'info'
}

function getStatusText(status) {
  const map = { pending: '等待中', running: '运行中', completed: '已完成', failed: '失败' }
  return map[status] || status
}

function viewTask(taskId) {
  // Placeholder: navigate to task detail
}
</script>

<template>
  <div class="panel">
    <div class="panel-header">
      <h3 class="panel-title">任务中心</h3>
      <div style="display:flex;gap:12px">
        <el-select v-model="statusFilter" placeholder="状态筛选" size="small" style="width:120px" clearable>
          <el-option v-for="item in statusOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
        <el-select v-model="typeFilter" placeholder="类型筛选" size="small" style="width:140px" clearable>
          <el-option v-for="item in typeOptions" :key="item.value" :label="item.label" :value="item.value" />
        </el-select>
      </div>
    </div>
    <div class="panel-body">
      <el-table :data="tasks" v-loading="loading" stripe style="width:100%">
        <el-table-column prop="task_id" label="任务编号" min-width="160" />
        <el-table-column prop="sample" label="样品编号" min-width="130" />
        <el-table-column prop="type" label="预测类型" min-width="110" />
        <el-table-column prop="status" label="状态" min-width="90">
          <template #default="{ row }">
            <el-tag :type="getStatusTag(row.status)" size="small">{{ getStatusText(row.status) }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="created_at" label="提交时间" min-width="150" />
        <el-table-column label="操作" min-width="80" fixed="right">
          <template #default="{ row }">
            <el-button text type="primary" size="small" @click="viewTask(row.task_id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>
  </div>
</template>
