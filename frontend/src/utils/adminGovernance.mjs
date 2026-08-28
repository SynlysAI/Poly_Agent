/** 用户与邀请码治理视图纯函数。 */

/**
 * 判断用户状态是否允许切换。
 *
 * @param {object} user 用户行。
 * @returns {boolean} 非 admin 用户允许启用或禁用。
 */
export function canToggleUser(user) {
  return Boolean(user) && user.role !== 'admin' && ['active', 'disabled'].includes(user.status)
}

/**
 * 计算下一次用户状态。
 *
 * @param {object} user 用户行。
 * @returns {string} active 或 disabled。
 */
export function nextUserStatus(user) {
  return user?.status === 'disabled' ? 'active' : 'disabled'
}

/**
 * 构建创建邀请码请求体，固定 user 角色。
 *
 * @param {object} form 邀请码表单。
 * @returns {object} POST 请求体。
 */
export function buildInviteCodePayload(form) {
  return {
    expires_hours: Number(form.expiresHours || 72),
    max_uses: Number(form.maxUses || 1),
  }
}

/**
 * 用户状态中文。
 *
 * @param {string} status 用户状态。
 * @returns {string} 中文状态。
 */
export function userStatusLabel(status) {
  const map = { active: '启用', disabled: '禁用' }
  return map[status] || status
}

/**
 * 邀请码状态中文。
 *
 * @param {string} status 邀请码状态。
 * @returns {string} 中文状态。
 */
export function inviteStatusLabel(status) {
  const map = { active: '有效', disabled: '已禁用' }
  return map[status] || status
}
