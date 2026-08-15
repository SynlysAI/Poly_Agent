/**
 * LUI 工具菜单展示字段的纯函数。
 * 工具菜单只需要读取目录项的基础字段，不应在这里引入组件状态。
 */

const HEALTH_LABEL_MAP = {
  healthy: '健康',
  unknown: '状态未知',
  unavailable: '不可用',
}

const HEALTH_CLASS_MAP = {
  healthy: 'is-healthy',
  unknown: 'is-unknown',
  unavailable: 'is-unavailable',
}

export function toolHealthLabel(status) {
  return HEALTH_LABEL_MAP[status] || HEALTH_LABEL_MAP.unknown
}

export function toolHealthClass(status) {
  return HEALTH_CLASS_MAP[status] || HEALTH_CLASS_MAP.unknown
}

export function toolRequiresFile(tool) {
  return Boolean((tool?.input_assets || []).some((item) => item?.required))
}

export function toolRecentSuccessText(tool) {
  if (!tool?.recent_run_count) return '暂无运行数据'
  if (typeof tool.recent_success_rate !== 'number') return '暂无成功率'
  return `最近成功率 ${Math.round(tool.recent_success_rate * 100)}%`
}

export function toolRecentSuccessClass(tool) {
  if (!tool?.recent_run_count || typeof tool.recent_success_rate !== 'number') {
    return 'is-muted'
  }
  if (tool.recent_success_rate >= 0.8) return 'is-success'
  if (tool.recent_success_rate >= 0.6) return 'is-warning'
  return 'is-danger'
}
