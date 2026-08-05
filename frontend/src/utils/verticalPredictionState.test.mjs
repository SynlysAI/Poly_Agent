import assert from 'node:assert/strict'

import {
  canManageUploadedAlgorithm,
  canEditRemoteInterfaceVersion,
  algorithmSourceLabel,
  interfaceProtocolLabel,
  predictionStepState,
  shouldReturnToCenterAfterSelectionReconciliation,
  suggestNextPatch,
  versionLifecycleLabel,
} from './verticalPredictionState.mjs'

assert.deepEqual(predictionStepState(), { activeStep: 2, inputLabel: '填写输入', hasResult: false })
assert.deepEqual(
  predictionStepState({ running: true }),
  { activeStep: 2, inputLabel: '处理中', hasResult: false },
)
assert.equal(predictionStepState({ lastRun: { status: 'completed' } }).activeStep, 3)
assert.equal(predictionStepState({ lastRun: { status: 'failed' } }).activeStep, 3)
assert.equal(
  predictionStepState({ running: true, lastRun: { status: 'failed' } }).inputLabel,
  '处理中',
)
assert.equal(predictionStepState({ running: false, lastRun: null }).activeStep, 2)
assert.equal(suggestNextPatch([{ version: '0.1.0' }]), '0.1.1')
assert.equal(suggestNextPatch([{ version: '0.1.9' }, { version: '0.2.1' }]), '0.2.2')
assert.equal(suggestNextPatch([{ version: 'not-semver' }]), '0.1.0')
assert.equal(
  canManageUploadedAlgorithm(
    { source: 'uploaded_package', owner: 'user-a' },
    { authEnabled: true, userId: 'user-a', role: 'user' },
  ),
  true,
)
assert.equal(
  canManageUploadedAlgorithm(
    { source: 'remote_interface', owner: 'user-a' },
    { authEnabled: true, userId: 'user-a', role: 'user' },
  ),
  true,
)
assert.equal(algorithmSourceLabel('uploaded_package'), '算法上传')
assert.equal(algorithmSourceLabel('remote_interface'), '接口调用')
assert.equal(interfaceProtocolLabel('fastapi'), 'FastAPI')
assert.equal(interfaceProtocolLabel('mcp'), 'MCP')
assert.equal(
  shouldReturnToCenterAfterSelectionReconciliation({
    activeMode: 'interface-config',
    selectedAlgorithmId: '',
    selectedAlgorithmExists: false,
  }),
  false,
)
assert.equal(
  shouldReturnToCenterAfterSelectionReconciliation({
    activeMode: 'interface-config',
    selectedAlgorithmId: 'missing-interface-model',
    selectedAlgorithmExists: false,
  }),
  true,
)
assert.equal(
  canManageUploadedAlgorithm(
    { source: 'uploaded_package', owner: 'user-a' },
    { authEnabled: true, userId: 'user-b', role: 'user' },
  ),
  false,
)
assert.equal(
  canManageUploadedAlgorithm(
    { source: 'uploaded_package', owner: 'user-a' },
    { authEnabled: true, userId: 'system-admin', role: 'admin' },
  ),
  true,
)
assert.equal(
  canManageUploadedAlgorithm(
    { source: 'uploaded_package', owner: 'user-a' },
    { authEnabled: false, userId: '', role: '' },
  ),
  true,
)
assert.equal(versionLifecycleLabel({ status: 'active', rollback_status: 'completed' }), '回滚完成')
assert.equal(versionLifecycleLabel({ status: 'active' }), '已激活')
assert.equal(versionLifecycleLabel({ status: 'deployed_staging' }), '待激活')
assert.equal(canEditRemoteInterfaceVersion({ status: 'validated' }), true)
assert.equal(canEditRemoteInterfaceVersion({ status: 'deployed_staging' }), true)
assert.equal(canEditRemoteInterfaceVersion({ status: 'active' }), false)
assert.equal(canEditRemoteInterfaceVersion({ status: 'frozen' }), false)

console.log('vertical prediction state tests passed')
