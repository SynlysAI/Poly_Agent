"""受控外部 Agent 执行（agent_exec）契约定义。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


AGENT_EXEC_TASK_TYPES: tuple[str, ...] = ("structured_file_task",)
AgentExecTaskType = Literal["structured_file_task"]
AgentExecRole = Literal["admin", "user"]


class AgentExecProviderReadiness(BaseModel):
    """外部 Agent provider 就绪状态。"""

    provider_id: str
    available: bool = False
    reason_code: str = ""
    message: str = ""
    checked_at: datetime
    details: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def unavailable(
        cls,
        *,
        provider_id: str,
        reason_code: str,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> AgentExecProviderReadiness:
        """构建结构化 unavailable 结果。

        Args:
            provider_id: provider 唯一标识。
            reason_code: 稳定机器可读原因码。
            message: 面向管理员的安全描述。
            details: 脱敏后的附加信息。

        Returns:
            available=False 的 readiness 对象。
        """
        from app.core.time import utc_now

        return cls(
            provider_id=provider_id,
            available=False,
            reason_code=reason_code,
            message=message,
            checked_at=utc_now(),
            details=details or {},
        )


class AgentExecInputFileData(BaseModel):
    """进入受限 workdir 的显式输入文件清单项。"""

    name: str = Field(description="workdir 内的安全文件名")
    size_bytes: int = Field(ge=0)
    sha256: str
    source_object_id: str = Field(description="服务端受管来源对象 ID")


class AgentExecTaskRequest(BaseModel):
    """一次文件型任务请求。"""

    task_type: AgentExecTaskType
    prompt: str = Field(min_length=1)
    input_files: list[AgentExecInputFileData] = Field(default_factory=list)
    output_schema: dict[str, Any]
    timeout_seconds: int = Field(gt=0)


class AgentExecExecutionRequest(BaseModel):
    """agent_exec 执行请求，包含调用方与确认上下文。"""

    provider_id: str = Field(min_length=1)
    task: AgentExecTaskRequest
    actor_user_id: str = Field(min_length=1)
    actor_role: AgentExecRole
    confirmed: bool = False
    chat_id: str = ""
    assistant_tool_call_id: str = ""


class AgentExecArtifactData(BaseModel):
    """provider 输出 artifact 清单项。"""

    path: str = Field(description="相对 run workdir 的输出路径")
    size_bytes: int = Field(ge=0)
    sha256: str
    content_type: str = ""


class AgentExecProviderResult(BaseModel):
    """provider 执行结果契约。"""

    provider_id: str
    success: bool
    output: dict[str, Any] | None = None
    artifacts: list[AgentExecArtifactData] = Field(default_factory=list)
    stdout_digest: str = ""
    stderr_digest: str = ""
    error_code: str = ""
    error_message: str = ""


class AgentExecProviderPolicy(BaseModel):
    """Agent 连接器调用策略，默认关闭且仅管理员可用。"""

    provider_id: str
    enabled: bool = False
    allowed_task_types: list[str] = Field(
        default_factory=lambda: list(AGENT_EXEC_TASK_TYPES)
    )
    allowed_roles: list[AgentExecRole] = Field(default_factory=lambda: ["admin"])
    requires_confirmation: bool = True
    updated_by: str = ""
    updated_at: datetime | None = None


class AgentExecRunData(BaseModel):
    """一次 agent_exec run 的权威状态摘要。"""

    run_id: str
    provider_id: str
    task_type: AgentExecTaskType
    status: Literal["requested", "running", "completed", "failed", "cancelled"]
    created_by: str
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    policy_snapshot: AgentExecProviderPolicy
    input_files: list[AgentExecInputFileData] = Field(default_factory=list)
    artifacts: list[AgentExecArtifactData] = Field(default_factory=list)
    error_code: str = ""
    error_message: str = ""
    chat_id: str = ""
    assistant_tool_call_id: str = ""


class AgentExecProviderConnection(BaseModel):
    """Agent 连接器卡片数据，仅包含脱敏后的公开元数据。"""

    provider_id: str
    display_name: str
    description: str = ""
    supported_task_types: list[str] = Field(default_factory=list)
    sandbox_summary: str = ""
    config_source: str = Field(default="", description="脱敏后的配置来源摘要")
    attribution: str = ""
    readiness: AgentExecProviderReadiness
    policy: AgentExecProviderPolicy


class AgentExecPolicyUpdateRequest(BaseModel):
    """管理员更新连接器策略的请求体。"""

    enabled: bool | None = None
    allowed_task_types: list[str] | None = None
    allowed_roles: list[AgentExecRole] | None = None
    requires_confirmation: bool | None = None
