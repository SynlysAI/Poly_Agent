import test from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInviteCodePayload,
  canToggleUser,
  inviteStatusLabel,
  nextUserStatus,
  userStatusLabel,
} from './adminGovernance.mjs'

test('管理员账号不可被状态操作，普通用户可启用或禁用', () => {
  assert.equal(canToggleUser({ role: 'admin', status: 'active' }), false)
  assert.equal(canToggleUser({ role: 'user', status: 'active' }), true)
  assert.equal(canToggleUser({ role: 'user', status: 'disabled' }), true)
})

test('用户状态切换固定在 active 与 disabled 之间', () => {
  assert.equal(nextUserStatus({ status: 'disabled' }), 'active')
  assert.equal(nextUserStatus({ status: 'active' }), 'disabled')
})

test('邀请码创建 payload 固定为有效期和次数，不提交角色', () => {
  assert.deepEqual(
    buildInviteCodePayload({ expiresHours: '48', maxUses: '3' }),
    { expires_hours: 48, max_uses: 3 },
  )
})

test('状态中文标签覆盖用户与邀请码', () => {
  assert.equal(userStatusLabel('active'), '启用')
  assert.equal(userStatusLabel('disabled'), '禁用')
  assert.equal(inviteStatusLabel('active'), '有效')
  assert.equal(inviteStatusLabel('disabled'), '已禁用')
})
