/**
 * LUI 工具菜单分类的纯函数定义。
 * 当前 /agent-tools 只返回垂类算法，计算工具与其他分类作为占位结构保留。
 */

export const TOOL_MENU_CATEGORIES = [
  {
    key: 'compute',
    label: '计算工具',
    description: '计算任务与工作流类工具',
    emptyText: '即将开放',
    icon: 'Cpu',
  },
  {
    key: 'vertical',
    label: '垂类算法工具',
    description: '已部署的垂类算法',
    emptyText: '暂无可用算法工具',
    icon: 'MagicStick',
  },
  {
    key: 'other',
    label: '其他',
    description: '检索、集成等扩展工具',
    emptyText: '即将开放',
    icon: 'MoreFilled',
  },
]

const COMPUTE_FAMILIES = new Set(['compute', 'computation', 'simulation'])
const COMPUTE_TYPES = new Set(['simulator', 'optimizer', 'calculator', 'computation', 'xtb', 'workflow'])

export function categorizeTool(tool) {
  const family = String(tool?.algorithm_family || '').toLowerCase()
  const capabilityGroup = String(tool?.capability_group || '').toLowerCase()
  const type = String(tool?.tool_type || '').toLowerCase()
  if (family === 'vertical_prediction' || capabilityGroup === 'vertical_algorithm' || type === 'predictor') {
    return 'vertical'
  }
  if (COMPUTE_FAMILIES.has(family) || COMPUTE_TYPES.has(type)) {
    return 'compute'
  }
  return 'other'
}

export function groupToolsByCategory(tools = []) {
  const counts = { compute: 0, vertical: 0, other: 0 }
  for (const tool of tools) {
    counts[categorizeTool(tool)] += 1
  }
  return TOOL_MENU_CATEGORIES.map((category) => ({
    ...category,
    count: counts[category.key] || 0,
  }))
}
