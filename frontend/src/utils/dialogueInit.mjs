/**
 * 判断对话页初始化是否因登录失效而必须中止。
 *
 * Args:
 *   results: Promise.allSettled 返回的结果列表。
 *
 * Returns:
 *   任一初始化请求因 401 失败时返回 true。
 */
export function shouldAbortDialogueInitialization(results) {
  return Array.isArray(results) && results.some((result) => (
    result?.status === 'rejected' && Number(result.reason?.status) === 401
  ))
}
