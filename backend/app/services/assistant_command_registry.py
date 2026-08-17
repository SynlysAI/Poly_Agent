"""Assistant Slash Command 注册表与动态 provider seam。"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.schemas.assistant_commands import (
    CommandChoice,
    CommandDescriptor,
    CommandVariant,
)


CommandHandler = Callable[..., Any]


class CommandProvider(Protocol):
    """动态命令提供方协议，为未来算法工具和自定义命令预留。"""

    def descriptors(self) -> list[CommandDescriptor]:
        """返回当前进程可提供的 handler-free descriptor 列表。"""


@dataclass(frozen=True)
class RegisteredCommand:
    """内部注册项；handler 永不出现在 API 响应中。"""

    descriptor: CommandDescriptor
    handler: CommandHandler | None
    reserved: bool = False


def dynamic_slug(source: str) -> str:
    """把算法或 provider 标识转换为稳定的小写 ASCII command slug。

    Args:
        source: 工具 ID、算法 ID或自定义来源标识。

    Returns:
    规范化 slug；冲突处理由注册表追加短哈希。
    """
    normalized = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(source or "")).strip("-").lower()
    if not normalized or not re.match(r"^[a-z]", normalized):
        normalized = f"tool-{normalized}" if normalized else "tool"
    return normalized[:64].rstrip("-") or "tool"


class AssistantCommandRegistry:
    """管理内置保留命令、动态 provider 和名称冲突策略。"""

    def __init__(self) -> None:
        self._commands: dict[str, RegisteredCommand] = {}
        self._providers: list[CommandProvider] = []
        self._register_builtins()

    def register(
        self,
        descriptor: CommandDescriptor,
        handler: CommandHandler | None = None,
        *,
        reserved: bool = False,
    ) -> CommandDescriptor:
        """注册命令，动态命令不得遮蔽内置保留名。

        Args:
            descriptor: Handler-free 对外描述符。
            handler: 命令平面处理器。
            reserved: 是否内置保留命令。

        Returns:
            实际注册后的 descriptor；冲突时名称会追加稳定短哈希。
        """

        def insert(item: CommandDescriptor) -> None:
            self._commands[item.name] = RegisteredCommand(
                descriptor=item,
                handler=handler,
                reserved=reserved,
            )

        if descriptor.name in self._commands:
            existing = self._commands[descriptor.name]
            if reserved:
                raise ValueError(f"内置命令名冲突: {descriptor.name}")
            suffix = hashlib.sha256(descriptor.source.encode()).hexdigest()[:6]
            renamed = descriptor.model_copy(update={"name": f"{descriptor.name}-{suffix}"})
            insert(renamed)
            return renamed
        insert(descriptor)
        return descriptor

    def register_provider(self, provider: CommandProvider) -> None:
        """注册动态 descriptor provider。

        Args:
            provider: 实现 descriptors() 的提供方。
        """
        self._providers.append(provider)

    def refresh_dynamic_commands(self) -> None:
        """刷新动态命令目录，不移除内置保留命令。"""
        dynamic_names = {
            name
            for name, command in self._commands.items()
            if not command.reserved
        }
        for name in dynamic_names:
            self._commands.pop(name, None)
        for provider in self._providers:
            for descriptor in provider.descriptors():
                self.register(descriptor)

    def resolve(self, name: str) -> RegisteredCommand | None:
        """按规范化命令名解析注册项。

        Args:
            name: 小写命令名。

        Returns:
            注册项；未知命令返回 None。
        """
        self.refresh_dynamic_commands()
        return self._commands.get(name)

    def descriptors(self) -> list[CommandDescriptor]:
        """返回排序后的 handler-free 命令目录。"""
        self.refresh_dynamic_commands()
        return [command.descriptor for command in self._commands.values()]

    def _register_builtins(self) -> None:
        """注册 PR-01 的内置控制命令。"""
        self.register(
            CommandDescriptor(
                name="plan",
                title="Plan Mode",
                description=(
                    "启用或退出计划模式；带消息时会创建受计划政策约束的回答任务。"
                ),
                usage="/plan [off|<message>]",
                category="system",
                source="PolyAgent Assistant Command Plane",
                source_kind="builtin",
                input_mode="text",
                argument_hint="off 或计划请求",
                variants=[
                    CommandVariant(usage="/plan", description="启用 Plan Mode"),
                    CommandVariant(usage="/plan off", description="退出 Plan Mode"),
                    CommandVariant(usage="/plan <message>", description="启用后创建计划任务"),
                ],
                risk_level="medium",
            ),
            self._placeholder_handler,
            reserved=True,
        )
        self.register(
            CommandDescriptor(
                name="goal",
                title="Session Goal",
                description="查看、设置或清除当前会话的长期目标。",
                usage="/goal [clear|<objective>]",
                category="agent",
                source="PolyAgent Assistant Command Plane",
                source_kind="builtin",
                input_mode="text",
                argument_hint="clear 或目标描述",
            ),
            self._placeholder_handler,
            reserved=True,
        )
        self.register(
            CommandDescriptor(
                name="permission",
                title="Permission Mode",
                description="查看或切换会话工具执行边界。",
                usage="/permission [read-only|workspace-write|full-access]",
                category="system",
                source="PolyAgent Assistant Command Plane",
                source_kind="builtin",
                input_mode="single_choice",
                choices=[
                    CommandChoice(value="read_only", label="只读"),
                    CommandChoice(value="workspace_write", label="工作区写入", selected=True),
                    CommandChoice(value="full_access", label="完全访问"),
                ],
                risk_level="high",
            ),
            self._placeholder_handler,
            reserved=True,
        )
        self.register(
            CommandDescriptor(
                name="model",
                title="Model Selection",
                description="查看当前模型或切换 provider::model，控制状态随会话保留。",
                usage="/model [<provider_id>::<model_id>]",
                category="system",
                source="PolyAgent Assistant Command Plane",
                source_kind="builtin",
                input_mode="single_choice",
            ),
            self._placeholder_handler,
            reserved=True,
        )
        self.register(
            CommandDescriptor(
                name="status",
                title="Session Status",
                description="汇总模型、模式、目标、权限与活动执行状态。",
                usage="/status",
                category="agent",
                source="PolyAgent Assistant Command Plane",
                source_kind="builtin",
                input_mode="none",
            ),
            self._placeholder_handler,
            reserved=True,
        )

    @staticmethod
    def _placeholder_handler(*_args: object, **_kwargs: object) -> None:
        """由 AssistantCommandService 在初始化时替换为真实处理器。"""
