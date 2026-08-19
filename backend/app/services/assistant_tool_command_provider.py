"""从当前用户可用算法工具派生 Slash Command 目录。"""

from __future__ import annotations

from app.schemas.agent_tools import AgentTool
from app.schemas.assistant_commands import CommandDescriptor
from app.schemas.attribution import AttributionItem
from app.services.agent_tool_service import AgentToolService
from app.services.assistant_command_registry import dynamic_slug


def _command_category(tool: AgentTool) -> str:
    """按工具元数据把动态命令映射到 tool 或 skill 分类。

    Args:
        tool: 算法工具目录项。

    Returns:
        Slash Command 分类名称。
    """
    markers = {
        str(tool.algorithm_family or "").lower(),
        str(tool.tool_type or "").lower(),
        str(tool.capability_group or "").lower(),
    }
    return "skill" if any("skill" in item or "workflow" in item for item in markers) else "tool"


def _attributions(tool: AgentTool) -> list[AttributionItem]:
    """合并算法开发者、框架与方法来源。

    Args:
        tool: 算法工具目录项。

    Returns:
        可序列化的 AttributionItem 列表。
    """
    return [
        item
        for item in (
            tool.developer_attribution,
            *tool.framework_attributions,
            *tool.method_attributions,
        )
        if item is not None
    ]


def tool_command_descriptor(tool: AgentTool) -> CommandDescriptor:
    """把一个可用算法工具转换为动态命令 descriptor。

    Args:
        tool: 当前用户可调用的算法工具。

    Returns:
        Handler-free 且携带 schema 与 attribution 摘要的命令描述符。
    """
    slug = dynamic_slug(tool.algorithm_id)
    developer_source = None
    if tool.developer_attribution:
        developer_source = (
            tool.developer_attribution.organization
            or tool.developer_attribution.name
        )
    return CommandDescriptor(
        name=slug,
        title=tool.name,
        description=tool.description or f"直接创建 {tool.name} 算法工具调用。",
        usage=f"/{slug} [<JSON 参数>|<任务说明>]",
        category=_command_category(tool),
        source=developer_source or tool.source or "算法工具",
        source_kind=tool.source_kind or "algorithm_tool",
        input_mode="tool_schema",
        argument_hint="JSON 参数或工具完成后的任务说明",
        tool_id=tool.tool_id,
        algorithm_id=tool.algorithm_id,
        tool_json_schema=tool.input_json_schema,
        attributions=_attributions(tool),
        requires_confirmation=tool.requires_confirmation,
        risk_level="medium" if tool.requires_confirmation else "high",
    )


class AssistantToolCommandProvider:
    """按请求用户提供动态算法命令，不把用户目录写入全局注册表。"""

    def descriptors(
        self,
        current_user: dict[str, str] | None = None,
    ) -> list[CommandDescriptor]:
        """返回当前用户可调用的算法工具命令。

        Args:
            current_user: 当前登录用户。

        Returns:
            动态命令 descriptor 列表。
        """
        return [
            tool_command_descriptor(tool)
            for tool in AgentToolService.list_tools(current_user).items
        ]
