"""外部 Agent provider 注册表。

注册表初始化不探测外部二进制、不抛异常、不阻断应用启动；
provider 缺失只返回结构化 unavailable。
"""

from __future__ import annotations

from app.schemas.agent_exec import AgentExecProviderReadiness
from app.services.agent_exec_providers.base import (
    AgentExecProvider,
    AgentExecProviderUnavailable,
)


class AgentExecProviderRegistry:
    """按 provider_id / task_type 解析受控 provider。"""

    def __init__(self) -> None:
        self._providers: dict[str, AgentExecProvider] = {}

    def register(self, provider: AgentExecProvider) -> None:
        """注册一个服务端代码内声明的 provider。

        Args:
            provider: 实现 AgentExecProvider 协议的适配器。
        """
        self._providers[provider.provider_id] = provider

    def get(self, provider_id: str) -> AgentExecProvider | None:
        """按 ID 查找 provider。

        Args:
            provider_id: provider 唯一标识。

        Returns:
            provider 实例；不存在时返回 None。
        """
        return self._providers.get(provider_id)

    def require(self, provider_id: str) -> AgentExecProvider:
        """按 ID 获取 provider，缺失时抛出结构化 unavailable。

        Args:
            provider_id: provider 唯一标识。

        Returns:
            provider 实例。

        Raises:
            AgentExecProviderUnavailable: provider 未注册。
        """
        provider = self._providers.get(provider_id)
        if provider is None:
            raise AgentExecProviderUnavailable(
                provider_id=provider_id,
                reason_code="provider_not_registered",
                message=f"外部 Agent provider '{provider_id}' 未注册",
            )
        return provider

    def resolve(self, provider_id: str, task_type: str) -> AgentExecProvider:
        """按 provider 与任务类型解析可用 provider。

        Args:
            provider_id: provider 唯一标识。
            task_type: 显式任务类型。

        Returns:
            声明支持该任务类型的 provider 实例。

        Raises:
            AgentExecProviderUnavailable: provider 缺失或任务类型不支持。
        """
        provider = self.require(provider_id)
        if task_type not in provider.supported_task_types:
            raise AgentExecProviderUnavailable(
                provider_id=provider_id,
                reason_code="task_type_not_supported",
                message=f"provider '{provider_id}' 不支持任务类型 '{task_type}'",
            )
        return provider

    def list_providers(self) -> list[AgentExecProvider]:
        """列出全部已注册 provider。

        Returns:
            按 provider_id 排序的 provider 列表。
        """
        return [self._providers[key] for key in sorted(self._providers)]

    def readiness(self, provider_id: str) -> AgentExecProviderReadiness:
        """聚合单个 provider 的 readiness。

        Args:
            provider_id: provider 唯一标识。

        Returns:
            provider readiness；provider 缺失时返回结构化 unavailable。
        """
        provider = self.get(provider_id)
        if provider is None:
            return AgentExecProviderReadiness.unavailable(
                provider_id=provider_id,
                reason_code="provider_not_registered",
                message=f"外部 Agent provider '{provider_id}' 未注册",
            )
        return provider.readiness()
