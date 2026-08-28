"""Agent 连接器策略治理服务。"""

from __future__ import annotations

from typing import Callable

from app.core.time import utc_now
from app.infra.agent_exec_repositories import AgentExecAuditWriter
from app.schemas.agent_exec import (
    AgentExecExecutionRequest,
    AgentExecPolicyUpdateRequest,
    AgentExecProviderPolicy,
)
from app.services.agent_exec_providers.base import AgentExecProvider


class AgentExecPolicyRejected(Exception):
    """连接器策略校验拒绝。"""

    def __init__(self, *, status_code: int, reason_code: str, message: str) -> None:
        """初始化策略拒绝错误。

        Args:
            status_code: API 应返回的 HTTP 状态码。
            reason_code: 稳定机器可读拒绝原因。
            message: 面向管理员的安全描述。
        """
        super().__init__(message)
        self.status_code = status_code
        self.reason_code = reason_code
        self.message = message


class AgentExecPolicyService:
    """连接器策略读取、更新与固定顺序校验。"""

    def __init__(
        self,
        *,
        policy_loader: Callable[[str], AgentExecProviderPolicy | None] | None = None,
        policy_saver: Callable[[AgentExecProviderPolicy], None] | None = None,
    ) -> None:
        """初始化策略服务。

        Args:
            policy_loader: 策略读取函数；缺省使用内存覆盖表。
            policy_saver: 策略保存函数；缺省写入内存覆盖表。
        """
        self._loader = policy_loader
        self._saver = policy_saver
        self._memory_policies: dict[str, AgentExecProviderPolicy] = {}

    def get_policy(self, provider_id: str) -> AgentExecProviderPolicy:
        """读取 provider 策略，无记录时返回安全默认值。

        Args:
            provider_id: provider 唯一标识。

        Returns:
            生效中的策略对象。
        """
        if self._loader is not None:
            policy = self._loader(provider_id)
            if policy is not None:
                return policy
        elif provider_id in self._memory_policies:
            return self._memory_policies[provider_id]
        return AgentExecProviderPolicy(provider_id=provider_id)

    def update_policy(
        self,
        provider: AgentExecProvider,
        request: AgentExecPolicyUpdateRequest,
        *,
        updated_by: str,
        actor_role: str = "admin",
    ) -> tuple[AgentExecProviderPolicy, AgentExecProviderPolicy]:
        """更新 provider 策略并返回变更前后快照。

        Args:
            provider: 目标 provider。
            request: 管理员提交的策略更新。
            updated_by: 操作人用户 ID。
            actor_role: 操作人真实角色。

        Returns:
            (变更前策略, 变更后策略) 元组。

        Raises:
            AgentExecPolicyRejected: 任务类型越界或角色列表为空。
        """
        current = self.get_policy(provider.provider_id)
        updates = request.model_dump(exclude_unset=True, exclude_none=True)
        allowed_task_types = updates.get(
            "allowed_task_types", current.allowed_task_types
        )
        unsupported = [
            item for item in allowed_task_types
            if item not in provider.supported_task_types
        ]
        if unsupported:
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="task_type_not_supported",
                message=(
                    f"provider '{provider.provider_id}' 不支持任务类型："
                    f"{', '.join(unsupported)}"
                ),
            )
        if not allowed_task_types:
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="task_types_empty",
                message="allowed_task_types 不能为空",
            )
        if "allowed_roles" in updates and not updates["allowed_roles"]:
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="roles_empty",
                message="allowed_roles 不能为空",
            )
        updated = current.model_copy(
            update={**updates, "updated_by": updated_by, "updated_at": utc_now()}
        )
        if self._saver is not None:
            self._saver(updated)
        else:
            self._memory_policies[provider.provider_id] = updated
        AgentExecAuditWriter.write_policy_updated(
            provider_id=provider.provider_id,
            before=current,
            after=updated,
            updated_by=updated_by,
            actor_role=actor_role,
        )
        return current, updated

    def check_request_policy(
        self,
        provider: AgentExecProvider,
        request: AgentExecExecutionRequest,
    ) -> AgentExecProviderPolicy:
        """按固定顺序校验角色、enabled 与 task_type。

        Args:
            provider: 目标 provider。
            request: 执行请求。

        Returns:
            生效中的策略快照。

        Raises:
            AgentExecPolicyRejected: 任一步骤不通过。
        """
        policy = self.get_policy(provider.provider_id)
        if request.actor_role not in policy.allowed_roles:
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="role_not_allowed",
                message=f"角色 '{request.actor_role}' 不允许调用该连接器",
            )
        if not policy.enabled:
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="provider_disabled",
                message="该连接器策略处于关闭状态",
            )
        task_type = request.task.task_type
        if task_type not in provider.supported_task_types:
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="task_type_not_supported",
                message=f"provider 不支持任务类型 '{task_type}'",
            )
        if task_type not in policy.allowed_task_types:
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="task_type_not_allowed",
                message=f"策略未允许任务类型 '{task_type}'",
            )
        return policy

    @staticmethod
    def check_confirmation(
        policy: AgentExecProviderPolicy,
        request: AgentExecExecutionRequest,
    ) -> None:
        """校验 Plan 10 确认状态机前置条件。

        Args:
            policy: 生效中的策略。
            request: 执行请求。

        Raises:
            AgentExecPolicyRejected: 未确认、只读权限或 Plan Mode 中。
        """
        if request.plan_mode:
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="plan_mode_blocked",
                message="Plan Mode 中不允许执行外部 Agent 任务",
            )
        if request.permission_mode == "read_only":
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="read_only_blocked",
                message="只读权限下不允许执行外部 Agent 任务",
            )
        if request.permission_mode != "workspace_write":
            raise AgentExecPolicyRejected(
                status_code=400,
                reason_code="permission_mode_unsupported",
                message="外部 Agent 连接器仅允许 workspace_write 受限执行语义",
            )
        if request.actor_role == "user" and not request.confirmed:
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="confirmation_required",
                message="普通用户必须在每次调用前显式确认",
            )
        if policy.requires_confirmation and not request.confirmed:
            raise AgentExecPolicyRejected(
                status_code=403,
                reason_code="confirmation_required",
                message="该连接器要求用户显式确认后才能执行",
            )
