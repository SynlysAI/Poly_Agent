<script setup>
const tools = [
  { name: '分子量预测', desc: '基于分子结构预测聚合物的数均/重均分子量及多分散性指数', status: 'coming' },
  { name: '热稳定性预测', desc: '预测聚合物的玻璃化转变温度、熔融温度和热分解温度', status: 'coming' },
  { name: '力学性能预测', desc: '预测拉伸强度、弹性模量、断裂伸长率等力学指标', status: 'coming' },
  { name: '流变性能预测', desc: '预测聚合物熔体的流变行为与加工性能', status: 'coming' },
  { name: '共混相容性评估', desc: '评估不同聚合物共混体系的相容性和相行为', status: 'coming' },
  { name: '降解性能评估', desc: '预测聚合物在特定环境条件下的降解速率', status: 'coming' },
]
</script>

<template>
  <div>
    <div class="panel" style="margin-bottom:16px">
      <div class="panel-header">
        <h3 class="panel-title">工具服务</h3>
      </div>
      <div class="panel-body">
        <p style="color:var(--app-ink-muted);font-size:14px">提供多种高分子材料性能预测模型服务，选择需要的工具开始使用。</p>
      </div>
    </div>
    <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:16px">
      <div v-for="tool in tools" :key="tool.name" class="panel" style="padding:20px;cursor:pointer;transition:box-shadow 0.2s">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px">
          <span style="font-weight:600;font-size:15px;color:var(--app-ink)">{{ tool.name }}</span>
          <el-tag size="small" type="info">即将上线</el-tag>
        </div>
        <p style="color:var(--app-ink-muted);font-size:13px;line-height:1.6">{{ tool.desc }}</p>
      </div>
    </div>
  </div>
</template>
