"""外部 Agent provider 协议、错误类型与结构化结果契约。"""

from __future__ import annotations

from pathlib import Path
from typing import Callable
from typing import Protocol, runtime_checkable

from app.schemas.agent_exec import (
    AgentExecProviderReadiness,
    AgentExecProviderResult,
    AgentExecTaskRequest,
)


class AgentExecProviderError(Exception):
    """provider 执行失败的统一错误。

    Attributes:
        code: 稳定机器可读错误码。
        message: 面向管理员的安全错误描述，不包含敏感信息。
    """

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class AgentExecProviderUnavailable(AgentExecProviderError):
    """provider 缺失、禁用或配置无效时的结构化 unavailable 错误。"""

    def __init__(self, provider_id: str, reason_code: str, message: str) -> None:
        super().__init__(reason_code, message)
        self.provider_id = provider_id


@runtime_checkable
class AgentExecProvider(Protocol):
    """受控外部 Agent provider 必须满足的最小协议。"""

    provider_id: str
    display_name: str
    supported_task_types: tuple[str, ...]

    def readiness(self) -> AgentExecProviderReadiness:
        """返回 provider 当前就绪状态。

        Returns:
            不执行任何外部二进制、无副作用的 readiness 结果。
        """
        ...

    def execute(
        self,
        *,
        task: AgentExecTaskRequest,
        workdir: Path,
        timeout_seconds: int,
        should_cancel: Callable[[], bool] | None = None,
    ) -> AgentExecProviderResult:
        """在受限 workdir 内执行文件型任务。

        Args:
            task: 显式任务与输入清单。
            workdir: run 专属受限工作目录。
            timeout_seconds: 执行超时秒数。
            should_cancel: 服务端取消检查回调。

        Returns:
            结构化 provider 结果；失败时抛出 AgentExecProviderError。
        """
        ...
