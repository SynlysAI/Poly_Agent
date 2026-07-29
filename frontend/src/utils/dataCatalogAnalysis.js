export function normalizeCollectionAnalysis(payload) {
  const data = payload && typeof payload === 'object' ? payload : {}
  return {
    ...data,
    field_stats: Array.isArray(data.field_stats) ? data.field_stats.map((field) => ({
      ...field,
      numeric_summary: field?.numeric_summary && typeof field.numeric_summary === 'object' ? field.numeric_summary : {},
      top_values: Array.isArray(field?.top_values) ? field.top_values : [],
      histogram: Array.isArray(field?.histogram) ? field.histogram : [],
    })) : [],
    correlations: Array.isArray(data.correlations) ? data.correlations : [],
    insights: Array.isArray(data.insights) ? data.insights.map((insight) => ({
      ...insight,
      evidence_fields: Array.isArray(insight?.evidence_fields) ? insight.evidence_fields : [],
    })) : [],
  }
}

export function collectionAnalysisStatusLabel(status) {
  return {
    ready: '全量可用',
    partial: '全量计数 + 抽样分析',
    degraded: '服务降级',
    not_configured: '未配置',
  }[status] || '未知'
}
