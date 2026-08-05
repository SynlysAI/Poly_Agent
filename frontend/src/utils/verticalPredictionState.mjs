export function predictionStepState({ running = false, lastRun = null } = {}) {
  if (running) {
    return { activeStep: 2, inputLabel: '处理中', hasResult: false }
  }
  if (lastRun) {
    return { activeStep: 3, inputLabel: '填写输入', hasResult: true }
  }
  return { activeStep: 2, inputLabel: '填写输入', hasResult: false }
}

/**
 * 判断缺失的模型选择是否需要退出当前工作流。
 */
export function shouldReturnToCenterAfterSelectionReconciliation({
  activeMode,
  uploadContextMode,
  selectedAlgorithmId,
  selectedAlgorithmExists,
}) {
  if (!selectedAlgorithmId || selectedAlgorithmExists) return false
  return activeMode === 'detail'
    || activeMode === 'interface-config'
    || (activeMode === 'upload' && uploadContextMode === 'new_version')
}

export function suggestNextPatch(versions = []) {
  const parsed = versions
    .map((item) => String(item?.version || item || '').trim())
    .map((version) => {
      const match = version.match(/^(\d+)\.(\d+)\.(\d+)$/)
      return match ? match.slice(1).map(Number) : null
    })
    .filter(Boolean)
    .sort((left, right) => (
      right[0] - left[0]
      || right[1] - left[1]
      || right[2] - left[2]
    ))
  const [major, minor, patch] = parsed[0] || [0, 1, -1]
  return `${major}.${minor}.${patch + 1}`
}

export function canManageUploadedAlgorithm(algorithm, user) {
  if (!algorithm || !['uploaded_package', 'remote_interface'].includes(algorithm.source)) {
    return false
  }
  if (!user?.authEnabled) {
    return true
  }
  return user.role === 'admin' || String(algorithm.owner || algorithm.owner_user_id || '') === String(user.userId || '')
}

export function canEditRemoteInterfaceVersion(version) {
  return ['validated', 'deployed_staging'].includes(String(version?.status || ''))
}

export function algorithmSourceLabel(source) {
  if (source === 'uploaded_package') return '算法上传'
  if (source === 'remote_interface') return '接口调用'
  return '内置能力'
}

export function interfaceProtocolLabel(protocol) {
  const value = String(protocol || '').toLowerCase()
  if (value === 'fastapi') return 'FastAPI'
  if (value === 'mcp') return 'MCP'
  if (value === 'http') return 'HTTP'
  return value ? value.toUpperCase() : '-'
}

export function versionLifecycleLabel(version) {
  if (version?.rollback_status === 'completed') {
    return '回滚完成'
  }
  const labels = {
    active: '已激活',
    deployed_staging: '待激活',
    built: '已构建',
    validated: '已校验',
    frozen: '已冻结',
    decommissioned: '已下线',
  }
  return labels[version?.status] || version?.status || '-'
}
