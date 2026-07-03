<script setup>
import { ref } from 'vue'

const activeCollection = ref('polymer_samples')

const collections = [
  { key: 'polymer_samples', name: '聚合物样品', count: 1286 },
  { key: 'prediction_results', name: '预测结果', count: 956 },
  { key: 'experiment_data', name: '实验数据', count: 420 },
  { key: 'literature_data', name: '文献数据', count: 318 },
]

const sampleColumns = [
  { prop: 'sample_id', label: '样品编号', minWidth: 140 },
  { prop: 'name', label: '名称', minWidth: 120 },
  { prop: 'material_type', label: '材料类型', minWidth: 100 },
  { prop: 'mw', label: '分子量 (Mw)', minWidth: 120 },
  { prop: 'pdi', label: 'PDI', minWidth: 80 },
  { prop: 'source', label: '数据来源', minWidth: 100 },
  { prop: 'created_at', label: '录入时间', minWidth: 140 },
]

const sampleData = [
  { sample_id: 'PE-2026-001', name: 'HDPE-Grade-A', material_type: 'PE', mw: '124,500', pdi: '2.1', source: '实验', created_at: '2026-06-15' },
  { sample_id: 'PP-2026-015', name: 'PP-Copolymer-B', material_type: 'PP', mw: '89,200', pdi: '3.2', source: '实验', created_at: '2026-06-20' },
  { sample_id: 'PS-2026-008', name: 'PS-Standard', material_type: 'PS', mw: '210,000', pdi: '1.05', source: '文献', created_at: '2026-05-28' },
]
</script>

<template>
  <div style="display:flex;gap:16px;height:calc(100vh - 100px)">
    <div class="panel" style="width:220px;flex-shrink:0;display:flex;flex-direction:column">
      <div class="panel-header">
        <h3 class="panel-title">数据集</h3>
      </div>
      <div class="panel-body" style="flex:1;overflow-y:auto;padding:8px">
        <div
          v-for="col in collections"
          :key="col.key"
          @click="activeCollection = col.key"
          :style="{
            padding: '10px 12px',
            borderRadius: 'var(--app-radius-sm)',
            cursor: 'pointer',
            marginBottom: '4px',
            background: activeCollection === col.key ? 'var(--app-primary-light)' : 'transparent',
            color: activeCollection === col.key ? 'var(--app-primary)' : 'var(--app-ink-body)',
            fontWeight: activeCollection === col.key ? '600' : '400',
            fontSize: '13px',
          }"
        >
          <div>{{ col.name }}</div>
          <div style="font-size:11px;margin-top:2px;opacity:0.7">{{ col.count.toLocaleString() }} 条记录</div>
        </div>
      </div>
    </div>
    <div class="panel" style="flex:1;display:flex;flex-direction:column">
      <div class="panel-header">
        <h3 class="panel-title">数据浏览</h3>
        <div style="display:flex;gap:8px">
          <el-input size="small" placeholder="搜索..." style="width:200px" />
          <el-button size="small" type="primary">查询</el-button>
        </div>
      </div>
      <div class="panel-body" style="flex:1;overflow:auto">
        <el-table :data="sampleData" :columns="sampleColumns" stripe style="width:100%">
          <el-table-column v-for="col in sampleColumns" :key="col.prop" :prop="col.prop" :label="col.label" :min-width="col.minWidth" />
        </el-table>
      </div>
    </div>
  </div>
</template>
