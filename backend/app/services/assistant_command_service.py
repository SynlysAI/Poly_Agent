"""Assistant Slash Command 执行平面与会话控制服务。"""

from __future__ import annotations

import difflib
import hashlib
import json
import time
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.time import utc_now
from app.infra.assistant_command_repositories import (
    AssistantCommandRunRepository,
    AssistantFeedbackRepository,
)
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.agent_tools import AssistantToolCall, AssistantToolCallCreate
from app.schemas.assistant_commands import (
    AssistantFeedback,
    CommandCatalogData,
    CommandChatReference,
    CommandChoice,
    CommandDescriptor,
    CommandExecution,
    CommandInteraction,
    SessionControlState,
)
from app.schemas.assistant_chats import AssistantChatCreate, AssistantMessageCreate
from app.schemas.assistant_runs import AssistantRun, AssistantRunCreate
from app.services.assistant_compaction_service import assistant_compaction_service
from app.services.assistant_export_service import (
    AGENT_VERSION,
    AssistantExportService,
)
from app.services.assistant_chat_service import actor_id, assistant_chat_service
from app.services.assistant_command_parser import CommandParseError, parse_command
from app.services.assistant_command_registry import AssistantCommandRegistry
from app.services.assistant_run_service import AssistantRunService
from app.services.assistant_session_control import (
    PERMISSION_LABELS,
    PERMISSION_MODES,
    control_state,
    tool_execution_block_reason,
)
from app.services.assistant_tool_service import assistant_tool_call_service
from app.services.assistant_tool_command_provider import AssistantToolCommandProvider
from app.services.llm_model_service import LLMModelService


CATALOG_VERSION = "assistant-command-catalog-v4"
ACTIVE_RUN_STATUSES = {"queued", "running"}
ACTIVE_TOOL_PHASES = {"requested", "awaiting_input", "awaiting_confirmation", "queued", "running"}
CATALOG_LATENCY_SAMPLES: list[tuple[datetime, float, bool]] = []


@dataclass
class CommandHandlerResult:
    """内置命令处理器的内部执行结果。"""

    status: str
    message: str
    interaction: CommandInteraction | None = None
    run: AssistantRun | None = None
    tool_call: AssistantToolCall | None = None
    chat: CommandChatReference | None = None
    source_event: str | None = None
    download_url: str | None = None
    download_filename: str | None = None
    export_path: str | None = None


class AssistantCommandService:
    """统一命令解析、目录、权限、处理器与事件生命周期。"""

    def __init__(self) -> None:
        self.registry = AssistantCommandRegistry()
        self.run_service = AssistantRunService()
        self.llm_model_service = LLMModelService()
        self.export_service = AssistantExportService()
        self.registry.register_provider(
            AssistantToolCommandProvider(),
            self._handle_tool_command,
        )
        self._install_handlers()

    @staticmethod
    def _owned_chat(chat_id: str, current_user: dict[str, str] | None) -> dict[str, Any]:
        """读取并校验当前用户拥有的会话。

        Args:
            chat_id: 会话 ID。
            current_user: 当前登录用户。

        Returns:
            会话文档。
        """
        owner_id = actor_id(current_user)
        chat = AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id})
        if not chat:
            raise HTTPException(status_code=404, detail=f"会话 '{chat_id}' 不存在")
        return chat

    @staticmethod
    def _model_pair(model: dict[str, Any]) -> tuple[str, str]:
        """从会话模型对象读取 provider/model 标识。

        Args:
            model: 会话中的模型选择对象。

        Returns:
            (provider_id,model_id) 元组，缺失时为空字符串。
        """
        return (
            str(model.get("providerId") or model.get("provider_id") or ""),
            str(model.get("modelId") or model.get("model_id") or ""),
        )

    @staticmethod
    def _objective_digest(objective: str) -> str:
        """生成目标摘要，避免命令事件复制完整用户目标文本。

        Args:
            objective: 用户设置的目标。

        Returns:
            sha256 摘要字符串。
        """
        return f"sha256:{hashlib.sha256(objective.encode('utf-8')).hexdigest()}"

    @classmethod
    def _model_choices(cls, current_model: dict[str, Any]) -> list[CommandChoice]:
        """构建当前可用模型选项。

        Args:
            current_model: 会话当前模型选择。

        Returns:
            provider::model 单选项列表。
        """
        current_value = "::".join(cls._model_pair(current_model))
        choices: list[CommandChoice] = []
        try:
            catalog = LLMModelService().get_catalog()
        except Exception:
            return choices
        for provider in catalog.providers:
            for model in provider.models:
                value = f"{provider.provider_id}::{model.model_id}"
                choices.append(
                    CommandChoice(
                        value=value,
                        label=f"{provider.display_name} / {model.display_name}",
                        description=model.model_id,
                        selected=value == current_value,
                    )
                )
        return choices

    @classmethod
    def _available_chat_model(cls, chat: dict[str, Any]) -> dict[str, str]:
        """读取仍存在于当前目录中的会话模型。

        Args:
            chat: 会话文档。

        Returns:
            可用的 provider/model 对；缺失或失效时返回空对象。
        """
        provider_id, model_id = cls._model_pair(chat.get("model") or {})
        if not provider_id or not model_id:
            return {}
        try:
            catalog = LLMModelService().get_catalog()
        except Exception:
            return {}
        for provider in catalog.providers:
            if provider.provider_id != provider_id:
                continue
            if any(model.model_id == model_id for model in provider.models):
                return {"providerId": provider_id, "modelId": model_id}
            break
        return {}

    @staticmethod
    def _tool_command_inputs(
        raw_args: str,
        payload: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any], str]:
        """解析动态工具命令的预填参数和可选续答任务说明。

        Args:
            raw_args: 命令名后的原样参数文本。
            payload: 命令请求附带的结构化 payload。

        Returns:
            (预填参数, 附件引用, 任务说明) 元组；自然语言 raw_args 只作为任务说明。
        """
        arguments: dict[str, Any] = {}
        raw_value = str(raw_args or "").strip()
        payload_arguments = payload.get("arguments")
        if isinstance(payload_arguments, dict):
            arguments.update(payload_arguments)
        elif not arguments and raw_value.startswith("{"):
            try:
                parsed = json.loads(raw_value)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = None
            if isinstance(parsed, dict):
                arguments.update(parsed)

        task_content = str(payload.get("task_content") or "").strip()
        if not task_content and not arguments:
            task_content = raw_value
        payload_asset_refs = payload.get("input_asset_refs")
        input_asset_refs = payload_asset_refs if isinstance(payload_asset_refs, dict) else {}
        return arguments, input_asset_refs, task_content

    @staticmethod
    def _tool_command_unavailable_reason(chat: dict[str, Any]) -> str | None:
        """生成当前会话控制状态下动态工具命令的不可用提示。

        Args:
            chat: 当前会话文档。

        Returns:
            工具命令不可用时的用户可读原因；可执行时返回 None。
        """
        reason = tool_execution_block_reason(chat)
        if reason == "plan_mode_blocked":
            return "Plan Mode 已开启，工具命令暂不可执行"
        if reason == "read_only_blocked":
            return "当前权限为只读，工具命令不可执行"
        return None

    @classmethod
    def _latest_chat(cls, chat_id: str, owner_id: str) -> dict[str, Any]:
        """读取最新会话文档；并发删除时返回空文档以闭合命令结果。

        Args:
            chat_id: 会话 ID。
            owner_id: 会话 owner。

        Returns:
            最新会话文档或空对象。
        """
        return AssistantChatRepository.find_one({"chat_id": chat_id, "created_by": owner_id}) or {
            "chat_id": chat_id,
            "model": {},
        }

    def _install_handlers(self) -> None:
        """把注册表占位 handler 替换为当前服务方法。"""
        handlers = {
            "plan": self._handle_plan,
            "goal": self._handle_goal,
            "permission": self._handle_permission,
            "model": self._handle_model,
            "status": self._handle_status,
            "reset": self._handle_reset,
            "clear": self._handle_clear,
            "compact": self._handle_compact,
            "export": self._handle_export,
            "feedback": self._handle_feedback,
        }
        for name, handler in handlers.items():
            registered = self.registry._commands.get(name)
            if registered:
                self.registry._commands[name] = replace(registered, handler=handler)

    def catalog(
        self,
        chat_id: str,
        current_user: dict[str, str] | None,
    ) -> CommandCatalogData:
        """返回当前会话可发现的 handler-free 命令目录。

        Args:
            chat_id: 会话 ID。
            current_user: 当前登录用户。

        Returns:
        命令目录、控制状态与目录版本。
        """
        started_at = time.perf_counter()
        try:
            chat = self._owned_chat(chat_id, current_user)
            items = self.registry.descriptors(current_user)
            items = [
                item.model_copy(
                    update={"choices": self._model_choices(chat.get("model") or {})},
                )
                if item.name == "model" and item.input_mode == "single_choice"
                else item
                for item in items
            ]
            unavailable_reason = self._tool_command_unavailable_reason(chat)
            if unavailable_reason:
                items = [
                    item.model_copy(
                        update={
                            "available": False,
                            "unavailable_reason": unavailable_reason,
                        }
                    )
                    if item.tool_id
                    else item
                    for item in items
                ]
            return CommandCatalogData(
                items=items,
                total=len(items),
                session_state=control_state(chat),
                catalog_version=CATALOG_VERSION,
            )
        finally:
            elapsed_ms = (time.perf_counter() - started_at) * 1000
            CATALOG_LATENCY_SAMPLES.append((utc_now(), elapsed_ms, True))
            if len(CATALOG_LATENCY_SAMPLES) > 500:
                del CATALOG_LATENCY_SAMPLES[:-500]

    def session_state(
        self,
        chat_id: str,
        current_user: dict[str, str] | None,
    ) -> SessionControlState:
        """读取带旧数据默认值的会话控制状态。

        Args:
            chat_id: 会话 ID。
            current_user: 当前登录用户。

        Returns:
            会话控制状态。
        """
        return control_state(self._owned_chat(chat_id, current_user))

    def execute(
        self,
        payload: Any,
        current_user: dict[str, str] | None,
    ) -> CommandExecution:
        """执行一行 Slash Command 并保证 command.run/done 成对。

        Args:
            payload: CommandExecuteRequest Pydantic 对象。
            current_user: 当前登录用户。

        Returns:
            不进入模型历史的直接命令执行结果。
        """
        owner_id = actor_id(current_user)
        chat = self._owned_chat(payload.chat_id, current_user)
        try:
            parsed = parse_command(payload.line)
            parsed_name = parsed.name
            raw_args = parsed.raw_args
        except CommandParseError:
            parsed = None
            parsed_name = "unknown"
            raw_args = payload.line

        registered = self.registry.resolve(parsed_name, current_user) if parsed else None
        descriptor = registered.descriptor if registered else None
        name = descriptor.name if descriptor else parsed_name
        source = descriptor.source if descriptor else "unknown"
        source_kind = descriptor.source_kind if descriptor else "unknown"
        command_id = f"cmd_{uuid4().hex[:16]}"
        now = utc_now()
        document = {
            "command_id": command_id,
            "chat_id": chat["chat_id"],
            "created_by": owner_id,
            "name": name,
            "title": descriptor.title if descriptor else "Unknown command",
            "source": source,
            "source_kind": source_kind,
            "raw_args": raw_args,
            "status": "running",
            "message": "",
            "state_after": None,
            "interaction": None,
            "run_id": None,
            "call_id": None,
            "tool_id": descriptor.tool_id if descriptor else None,
            "algorithm_id": descriptor.algorithm_id if descriptor else None,
            "download_url": None,
            "download_filename": None,
            "source_event": None,
            "created_at": now,
            "updated_at": now,
            "started_at": now,
            "finished_at": None,
        }
        AssistantCommandRunRepository.start(document)
        run_event = AssistantCommandRunRepository.append_chat_event(
            chat,
            {
                "type": "command.run",
                "command_id": command_id,
                "name": name,
                "raw_args": raw_args,
                "source": source,
                "chat_id": chat["chat_id"],
            },
        )

        try:
            if registered is None or descriptor is None:
                suggestions = difflib.get_close_matches(parsed_name, self.registry._commands.keys(), n=3)
                suffix = f"；可尝试: {', '.join('/' + item for item in suggestions)}" if suggestions else ""
                raise ValueError(f"未知命令 /{parsed_name}{suffix}")
            if descriptor.tool_id:
                reason = tool_execution_block_reason(chat)
                if reason:
                    AssistantCommandRunRepository.append_chat_event(
                        chat,
                        {
                            "type": "permission.decision",
                            "command_id": command_id,
                            "trace_id": command_id,
                            "tool_id": descriptor.tool_id,
                            "decision": "denied",
                            "reason": reason,
                            "mode": str(chat.get("permission_mode") or "workspace_write"),
                            "plan_mode": bool(chat.get("plan_mode", False)),
                        },
                    )
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "code": reason,
                            "message": (
                                "Plan Mode 已阻断工具命令创建"
                                if reason == "plan_mode_blocked"
                                else "只读模式已阻断工具命令创建"
                            ),
                        },
                    )
            if registered.handler is None:
                raise ValueError(f"命令 /{name} 尚未注册处理器")
            handler_args = [chat, parsed.raw_args, payload.payload, current_user, command_id]
            if descriptor.tool_id:
                result = registered.handler(*handler_args, descriptor=descriptor)
            else:
                result = registered.handler(*handler_args)
            final_status = result.status
            message = result.message
            interaction = result.interaction
            run = result.run
            tool_call = result.tool_call
            chat_reference = result.chat
            source_event = result.source_event
            download_url = result.download_url
            download_filename = result.download_filename
            export_path = result.export_path
            error = None
        except Exception as exc:
            final_status = "failed"
            if isinstance(exc, HTTPException):
                detail = exc.detail
                if isinstance(detail, dict):
                    message = str(detail.get("message") or detail.get("code") or exc.__class__.__name__)
                else:
                    message = str(detail)
            else:
                message = str(exc) or exc.__class__.__name__
            interaction = None
            run = None
            tool_call = None
            chat_reference = None
            download_url = None
            download_filename = None
            export_path = None
            source_event = (run_event or {}).get("event_id")
            error = {"error_type": exc.__class__.__name__, "message": message}

        latest_chat = self._latest_chat(payload.chat_id, owner_id)
        state_chat = latest_chat
        if chat_reference and chat_reference.chat_id:
            state_chat = self._latest_chat(str(chat_reference.chat_id), owner_id)
        state = control_state(state_chat)
        finished_at = utc_now()
        result_document = {
            **document,
            "status": final_status,
            "message": message,
            "state_after": state.model_dump(mode="python"),
            "interaction": interaction.model_dump(mode="python") if interaction else None,
            "run_id": getattr(run, "run_id", None),
            "call_id": getattr(tool_call, "call_id", None),
            "chat": chat_reference.model_dump(mode="python") if chat_reference else None,
            "download_url": download_url,
            "download_filename": download_filename,
            "export_path": export_path,
            "source_event": source_event,
            "error": error,
            "finished_at": finished_at,
            "updated_at": finished_at,
        }
        AssistantCommandRunRepository.finish(command_id, result_document)
        AssistantCommandRunRepository.append_chat_event(
            latest_chat,
            {
                "type": "command.done",
                "command_id": command_id,
                "name": name,
                "status": final_status,
                "message": message,
                "call_id": getattr(tool_call, "call_id", None),
                "source_event": source_event,
                "chat_id": payload.chat_id,
            },
        )
        return CommandExecution.model_validate(
            {
                **result_document,
                "state_after": state,
                "interaction": interaction,
                "run": run,
                "tool_call": tool_call,
                "chat": chat_reference,
            }
        )

    def command_events(
        self,
        chat_id: str,
        current_user: dict[str, str] | None,
        after_seq: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """读取会话级命令生命周期事件。

        Args:
            chat_id: 会话 ID。
            current_user: 当前登录用户。
            after_seq: 事件游标。

        Returns:
            (事件列表, 下一个游标) 元组。
        """
        chat = self._owned_chat(chat_id, current_user)
        events = AssistantCommandRunRepository.events_after(
            chat_id,
            str(chat.get("created_by") or ""),
            after_seq,
            event_types={"command.run", "command.done", "permission.decision"},
        )
        next_seq = max([int(item.get("seq", 0)) for item in events], default=int(after_seq))
        return events, next_seq

    def _update_state(
        self,
        chat: dict[str, Any],
        fields: dict[str, Any],
        event: dict[str, Any],
    ) -> dict[str, Any] | None:
        """写会话控制状态并记录状态事件。

        Args:
            chat: 当前会话文档。
            fields: 需要更新的控制字段。
            event: 统一事件 payload。

        Returns:
            插入的 assistant_events 文档。
        """
        now = utc_now()
        AssistantChatRepository.update_owned(
            str(chat["chat_id"]),
            str(chat["created_by"]),
            {**fields, "updated_at": now},
        )
        return AssistantCommandRunRepository.append_chat_event(
            {**chat, **fields},
            {"chat_id": chat["chat_id"], **event},
        )

    def _handle_tool_command(
        self,
        chat: dict[str, Any],
        raw_args: str,
        payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
        *,
        descriptor: CommandDescriptor,
    ) -> CommandHandlerResult:
        """为动态算法命令创建同一条 AssistantToolCall 状态机记录。

        Args:
            chat: 当前会话文档。
            raw_args: 命令名后的原样参数。
            payload: 结构化命令 payload。
            current_user: 当前登录用户。
            command_id: 命令生命周期 ID。
            descriptor: 被选中的动态工具命令描述符。

        Returns:
            附带工具调用卡片的命令处理结果。
        """
        if not descriptor.tool_id or not descriptor.algorithm_id:
            raise ValueError("动态工具命令缺少 tool_id 或 algorithm_id")
        if not descriptor.tool_json_schema:
            raise ValueError("算法工具缺少输入 schema，无法打开参数表单")

        arguments, input_asset_refs, task_content = self._tool_command_inputs(raw_args, payload)
        command_line = f"/{descriptor.name}{raw_args}"
        message = assistant_chat_service.create_message(
            str(chat["chat_id"]),
            AssistantMessageCreate(
                role="user",
                content=task_content or command_line,
                metadata={
                    "origin": "slash_command",
                    "model_visible": False,
                    "command_id": command_id,
                    "command_name": descriptor.name,
                    "command_line": command_line,
                    "task_content": task_content,
                    "tool_id": descriptor.tool_id,
                    "algorithm_id": descriptor.algorithm_id,
                },
            ),
            current_user,
        )
        model_request = dict(chat.get("model") or {})
        call = assistant_tool_call_service.create(
            AssistantToolCallCreate(
                tool_id=descriptor.tool_id,
                chat_id=str(chat["chat_id"]),
                message_id=message.message_id,
                trace_id=command_id,
                command_id=command_id,
                arguments=arguments,
                input_asset_refs=input_asset_refs,
                selection_reason="slash_command_direct_execution",
                proposal_route=model_request,
                source_context={
                    "origin": "slash_command",
                    "command_id": command_id,
                    "task_content": task_content,
                    "selected_tool_ids": [descriptor.tool_id],
                    "mode": "qa",
                    "model_request": model_request,
                    "route_snapshot": model_request,
                },
            ),
            current_user,
        )
        if call.phase in {"awaiting_input", "awaiting_confirmation"}:
            status = "interaction"
            result_message = "已创建算法工具调用，请在参数表单中确认。"
        elif call.phase == "failed":
            status = "failed"
            result_message = (call.error or {}).get("message") or "算法工具调用创建失败"
        else:
            status = "success"
            result_message = "算法工具命令已提交执行。"
        return CommandHandlerResult(
            status=status,
            message=result_message,
            tool_call=call,
            source_event=command_id,
        )

    def _handle_plan(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /plan 命令。

        Args:
            chat: 会话文档。
            raw_args: 原样参数。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前登录用户。
            command_id: 命令执行 ID。

        Returns:
            命令处理结果；带消息时包含计划模式 run。
        """
        actor = actor_id(current_user)
        normalized = raw_args.strip()
        active = normalized.lower() != "off"
        event = self._update_state(
            chat,
            {"plan_mode": active},
            {
                "type": "plan.mode.changed",
                "command_id": command_id,
                "active": active,
                "actor": actor,
            },
        )
        message = "Plan Mode 已启用" if active else "Plan Mode 已退出"
        if not normalized:
            return CommandHandlerResult(status="success", message=message, source_event=(event or {}).get("event_id"))
        if not active:
            return CommandHandlerResult(status="success", message=message, source_event=(event or {}).get("event_id"))
        run = self.run_service.create(
            str(chat["chat_id"]),
            AssistantRunCreate(
                content=normalized,
                context={
                    "plan_mode": True,
                    "command_id": command_id,
                    "model": self._available_chat_model(chat),
                    "session_state": control_state({**chat, "plan_mode": True}).model_dump(mode="python"),
                },
            ),
            current_user,
        )
        return CommandHandlerResult(
            status="success",
            message=f"{message}，已创建计划任务",
            run=run,
            source_event=(event or {}).get("event_id"),
        )

    def _handle_goal(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /goal 命令。

        Args:
            chat: 会话文档。
            raw_args: 原样目标文本或 clear。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前登录用户。
            command_id: 命令执行 ID。

        Returns:
            当前目标查看、设置或清除结果。
        """
        objective = raw_args.strip()
        current = chat.get("goal")
        if not objective:
            if current:
                return CommandHandlerResult(status="success", message=f"当前目标：{current['objective']}")
            return CommandHandlerResult(status="success", message="当前没有长期目标")
        if objective.lower() == "clear":
            event = self._update_state(
                chat,
                {"goal": None},
                {
                    "type": "goal.changed",
                    "command_id": command_id,
                    "action": "clear",
                    "goal_id": (current or {}).get("goal_id", ""),
                    "objective_digest": self._objective_digest(str((current or {}).get("objective") or "")),
                },
            )
            return CommandHandlerResult(
                status="success",
                message="已清除长期目标",
                source_event=(event or {}).get("event_id"),
            )
        if len(objective) > 2_000:
            raise ValueError("目标文本不能超过 2000 个字符")
        now = utc_now()
        goal = {
            "goal_id": f"goal_{uuid4().hex[:12]}",
            "objective": objective,
            "status": "active",
            "created_by": actor_id(current_user),
            "created_at": now,
            "updated_at": now,
        }
        event = self._update_state(
            chat,
            {"goal": goal},
            {
                "type": "goal.changed",
                "command_id": command_id,
                "action": "set",
                "goal_id": goal["goal_id"],
                "objective_digest": self._objective_digest(objective),
            },
        )
        return CommandHandlerResult(
            status="success",
            message="已设置长期目标",
            source_event=(event or {}).get("event_id"),
        )

    def _handle_permission(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        _current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /permission 命令。

        Args:
            chat: 会话文档。
            raw_args: 原样模式参数。
            _payload: 前端交互 payload，当前命令不使用。
            _current_user: 当前登录用户。
            command_id: 命令执行 ID。

        Returns:
            模式选项交互或切换结果。
        """
        current = str(chat.get("permission_mode") or "workspace_write")
        if not raw_args.strip():
            choices = [
                CommandChoice(
                    value=mode,
                    label=PERMISSION_LABELS[mode],
                    selected=mode == current,
                )
                for mode in PERMISSION_MODES
            ]
            return CommandHandlerResult(
                status="interaction",
                message=f"当前权限：{PERMISSION_LABELS[current]}",
                interaction=CommandInteraction(kind="choice", prompt="选择会话权限模式", choices=choices),
            )
        mode = raw_args.strip().lower().replace("-", "_")
        if mode not in PERMISSION_MODES:
            raise ValueError("无效权限模式，可选 read-only / workspace-write / full-access")
        event = self._update_state(
            chat,
            {"permission_mode": mode},
            {
                "type": "permission.mode.changed",
                "command_id": command_id,
                "before": current,
                "after": mode,
            },
        )
        return CommandHandlerResult(
            status="success",
            message=f"权限模式已切换为 {PERMISSION_LABELS[mode]}",
            source_event=(event or {}).get("event_id"),
        )

    def _handle_model(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        _current_user: dict[str, str] | None,
        _command_id: str,
    ) -> CommandHandlerResult:
        """处理 /model 命令，切换模型时不重置其他控制状态。

        Args:
            chat: 会话文档。
            raw_args: provider::model 或空。
            _payload: 前端交互 payload，当前命令不使用。
            _current_user: 当前登录用户。
            _command_id: 命令执行 ID。

        Returns:
            模型选项交互或切换结果。
        """
        current = dict(chat.get("model") or {})
        if not raw_args.strip():
            return CommandHandlerResult(
                status="interaction",
                message="当前模型：" + ("::".join(self._model_pair(current)) or "未选择"),
                interaction=CommandInteraction(
                    kind="choice",
                    prompt="选择会话模型",
                    choices=self._model_choices(current),
                ),
            )
        value = raw_args.strip()
        if value.count("::") != 1:
            raise ValueError("模型参数必须为 <provider_id>::<model_id>")
        provider_id, model_id = [part.strip() for part in value.split("::", 1)]
        if not provider_id or not model_id:
            raise ValueError("provider_id 和 model_id 不能为空")
        choices = self._model_choices(current)
        if choices and value not in {choice.value for choice in choices}:
            raise ValueError("模型不可用或当前用户无权限选择")
        next_model = {"providerId": provider_id, "modelId": model_id}
        AssistantChatRepository.update_owned(
            str(chat["chat_id"]),
            str(chat["created_by"]),
            {"model": next_model, "updated_at": utc_now()},
        )
        return CommandHandlerResult(status="success", message=f"模型已切换为 {provider_id}::{model_id}")

    def _handle_reset(
        self,
        chat: dict[str, Any],
        raw_args: str,
        payload: dict[str, Any],
        _current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /reset 命令。

        Args:
            chat: 会话文档。
            raw_args: confirm 或 cancel 参数。
            payload: 结构化 payload，支持 confirmed=true。
            _current_user: 当前用户，重置动作以会话归属校验为准。
            command_id: 命令生命周期 ID。

        Returns:
            重置确认交互，或仅重置控制状态的结果。
        """
        argument = raw_args.strip().lower().replace("-", "_")
        confirmed = argument in {"confirm", "confirmed", "yes"} or bool(payload.get("confirmed"))
        canceled = argument in {"cancel", "no"} or bool(payload.get("canceled"))
        payload_has_decision = "confirmed" in payload or "canceled" in payload
        payload_decision = bool(payload.get("confirmed")) or bool(payload.get("canceled"))
        if not argument and (not payload_has_decision or not payload_decision):
            return CommandHandlerResult(
                status="interaction",
                message="确认重置当前会话控制状态吗？消息、run、工具调用与事件会全部保留。",
                interaction=CommandInteraction(
                    kind="confirmation",
                    prompt="仅重置 Plan、权限、目标与 Todo",
                    choices=[
                        CommandChoice(value="confirm", label="确认重置", description="保留全部审计历史"),
                        CommandChoice(value="cancel", label="取消", description="不做任何修改"),
                    ],
                ),
            )
        if canceled:
            return CommandHandlerResult(status="success", message="已取消重置，控制状态保持不变")
        if not confirmed:
            raise ValueError("无效 reset 参数；请使用 /reset confirm 或 /reset cancel")

        before = {
            "plan_mode": bool(chat.get("plan_mode", False)),
            "permission_mode": str(chat.get("permission_mode") or "workspace_write"),
            "goal_id": (chat.get("goal") or {}).get("goal_id"),
            "todo_count": len(chat.get("todos") or []),
        }
        event = self._update_state(
            chat,
            {
                "plan_mode": False,
                "permission_mode": "workspace_write",
                "goal": None,
                "todos": [],
            },
            {
                "type": "session.reset",
                "command_id": command_id,
                "trace_id": command_id,
                "before": before,
                "after": {
                    "plan_mode": False,
                    "permission_mode": "workspace_write",
                    "goal": None,
                    "todos": [],
                },
            },
        )
        return CommandHandlerResult(
            status="success",
            message="控制状态已重置；消息、run、工具调用与事件均已保留",
            source_event=(event or {}).get("event_id"),
        )

    def _handle_clear(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /clear 命令。

        Args:
            chat: 旧会话文档。
            raw_args: 原样参数；clear 不接受额外参数。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前用户。
            command_id: 命令生命周期 ID。

        Returns:
            新会话引用；旧会话数据不做删除。
        """
        if raw_args.strip():
            raise ValueError("/clear 不支持额外参数")
        new_chat = assistant_chat_service.create(
            AssistantChatCreate(
                title="新对话",
                model=dict(chat.get("model") or {}),
                mode=str(chat.get("mode") or "qa"),
                knowledge_base_ids=list(chat.get("knowledge_base_ids") or []),
                knowledge_base_names=list(chat.get("knowledge_base_names") or []),
                use_web_search=bool(chat.get("use_web_search", False)),
                selected_tool_ids=list(chat.get("selected_tool_ids") or []),
            ),
            current_user,
        )
        event = AssistantCommandRunRepository.append_chat_event(
            chat,
            {
                "type": "session.clear",
                "command_id": command_id,
                "trace_id": command_id,
                "new_chat_id": new_chat.chat_id,
                "old_chat_id": str(chat["chat_id"]),
            },
        )
        reference = CommandChatReference(
            chat_id=new_chat.chat_id,
            title=new_chat.title,
            model=new_chat.model,
            plan_mode=new_chat.plan_mode,
            permission_mode=new_chat.permission_mode,
        )
        return CommandHandlerResult(
            status="success",
            message=f"已创建新会话并保留旧会话 {chat['chat_id']}",
            chat=reference,
            source_event=(event or {}).get("event_id"),
        )

    def _handle_compact(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /compact 命令。

        Args:
            chat: 会话文档。
            raw_args: 原样参数；compact 不接受额外参数。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前登录用户。
            command_id: 命令执行 ID。

        Returns:
            上下文压缩结果。
        """
        if raw_args.strip():
            raise ValueError("/compact 不支持额外参数")
        snapshot = assistant_compaction_service.compact(chat, current_user, command_id)
        reduction = max(0, snapshot.original_token_estimate - snapshot.token_estimate)
        method = "辅助模型" if snapshot.summary_method == "llm" else "确定性兜底"
        return CommandHandlerResult(
            status="success",
            message=(
                f"上下文已压缩（{method}）：{snapshot.original_token_estimate} → "
                f"{snapshot.token_estimate} tokens，节省 {reduction} tokens"
            ),
        )

    def _handle_export(
        self,
        chat: dict[str, Any],
        raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /export 命令。

        Args:
            chat: 当前会话文档。
            raw_args: 原样导出格式参数。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前登录用户。
            command_id: 命令生命周期 ID。

        Returns:
            格式选择交互或导出下载结果。
        """
        export_format = raw_args.strip()
        if not export_format:
            return CommandHandlerResult(
                status="interaction",
                message="请选择会话导出格式。",
                interaction=CommandInteraction(
                    kind="choice",
                    prompt="选择导出格式",
                    choices=[
                        CommandChoice(value="json", label="JSON", description="单一结构化对象"),
                        CommandChoice(value="markdown", label="Markdown", description="人类可读报告"),
                        CommandChoice(value="zip", label="ZIP", description="包含 Trace 与 artifact 的归档"),
                    ],
                ),
            )
        exported = self.export_service.export(chat, current_user, command_id, export_format)
        return CommandHandlerResult(
            status="success",
            message=(
                f"会话导出完成：{exported.filename}，"
                f"{exported.counts.get('messages', 0)} 条消息 / "
                f"{exported.counts.get('execution_trace', 0)} 条 Trace 事件"
            ),
            download_url=f"/api/v1/assistant/commands/{command_id}/download",
            download_filename=exported.filename,
            export_path=str(exported.path),
            source_event=command_id,
        )

    def _handle_feedback(
        self,
        chat: dict[str, Any],
        raw_args: str,
        payload: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
    ) -> CommandHandlerResult:
        """处理 /feedback 命令。

        Args:
            chat: 当前会话文档。
            raw_args: 原样参数；提交正文必须走结构化 payload。
            payload: 包含 rating、comment 和可选目标 command_id 的表单数据。
            current_user: 当前登录用户。
            command_id: 当前反馈命令生命周期 ID。

        Returns:
            反馈表单交互或权威反馈写入结果。
        """
        if raw_args.strip():
            raise ValueError("反馈正文不能作为命令参数重复记录，请在表单中提交")
        rating = payload.get("rating")
        if not rating:
            return CommandHandlerResult(
                status="interaction",
                message="请提交会话反馈。",
                interaction=CommandInteraction(
                    kind="form",
                    prompt="这次模型执行有帮助吗？",
                    choices=[
                        CommandChoice(value="helpful", label="有帮助"),
                        CommandChoice(value="not_helpful", label="需改进"),
                    ],
                ),
            )
        comment = str(payload.get("comment") or "").strip()
        target_command_id = payload.get("command_id")
        context = self._feedback_context(chat, current_user, target_command_id)
        feedback = AssistantFeedback(
            feedback_id=f"fb_{uuid4().hex[:16]}",
            chat_id=str(chat["chat_id"]),
            rating=rating,
            comment=comment,
            command_id=context["command_id"],
            submitted_by_command_id=command_id,
            trace_id=context["trace_id"],
            model_route=context["model_route"],
            agent_version=AGENT_VERSION,
            created_by=actor_id(current_user),
            created_at=utc_now(),
        )
        document = AssistantFeedbackRepository.create(feedback.model_dump(mode="python"))
        feedback_event = AssistantCommandRunRepository.append_chat_event(
            chat,
            {
                "type": "feedback.recorded",
                "command_id": command_id,
                "feedback_command_id": context["command_id"],
                "feedback_id": feedback.feedback_id,
                "rating": feedback.rating,
                "trace_id": feedback.trace_id,
                "model_route": feedback.model_route,
                "agent_version": feedback.agent_version,
                "comment_digest": self._objective_digest(comment) if comment else "",
                "chat_id": str(chat["chat_id"]),
            },
        )
        rating_label = "有帮助" if feedback.rating == "helpful" else "需改进"
        return CommandHandlerResult(
            status="success",
            message=f"反馈已记录（{rating_label}），关联 Trace {feedback.trace_id}",
            source_event=str((feedback_event or {}).get("event_id") or document["feedback_id"]),
        )

    def _feedback_context(
        self,
        chat: dict[str, Any],
        current_user: dict[str, str] | None,
        target_command_id: Any = None,
    ) -> dict[str, Any]:
        """从权威 run / command 记录解析反馈关联上下文。

        Args:
            chat: 当前会话文档。
            current_user: 当前登录用户。
            target_command_id: 用户指定的目标命令 ID。

        Returns:
            实际模型 run 的 command_id、trace_id 与 model_route。
        """
        owner_id = actor_id(current_user)
        chat_id = str(chat["chat_id"])
        runs, _ = AssistantRunRepository.list_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=100,
        )
        candidate_run_ids: set[str] = set()
        normalized_target = str(target_command_id or "").strip() or None
        if normalized_target:
            command = AssistantCommandRunRepository.find_one(
                {
                    "command_id": normalized_target,
                    "chat_id": chat_id,
                    "created_by": owner_id,
                }
            )
            if not command:
                raise ValueError("反馈目标命令不存在")
            if command.get("run_id"):
                candidate_run_ids.add(str(command["run_id"]))
            call = AssistantToolCallRepository.find_one(
                {"command_id": normalized_target, "chat_id": chat_id, "created_by": owner_id}
            )
            if call:
                for key in ("assistant_run_id", "continuation_run_id"):
                    if call.get(key):
                        candidate_run_ids.add(str(call[key]))
        run = next((item for item in runs if str(item.get("run_id")) in candidate_run_ids), None)
        if run is None and not candidate_run_ids:
            run = runs[0] if runs else None
        if run is None:
            raise ValueError("当前会话暂无可反馈的实际模型执行记录")
        route = dict(run.get("route") or {})
        route.update(
            {
                "provider_id": run.get("provider_id") or route.get("provider_id") or "",
                "model_id": run.get("model_id") or route.get("model_id") or "",
                "run_id": run.get("run_id"),
            }
        )
        return {
            "command_id": normalized_target,
            "trace_id": str(run.get("trace_id") or run.get("run_id") or ""),
            "model_route": route,
        }

    def _handle_status(
        self,
        chat: dict[str, Any],
        _raw_args: str,
        _payload: dict[str, Any],
        current_user: dict[str, str] | None,
        _command_id: str,
    ) -> CommandHandlerResult:
        """处理 /status 命令。

        Args:
            chat: 会话文档。
            _raw_args: 原样参数，当前命令忽略。
            _payload: 前端交互 payload，当前命令不使用。
            current_user: 当前登录用户。
            _command_id: 命令执行 ID。

        Returns:
            会话控制与执行摘要。
        """
        owner_id = actor_id(current_user)
        chat_id = str(chat["chat_id"])
        runs, _ = AssistantRunRepository.list_for_chat(chat_id, owner_id, page=1, page_size=100)
        calls = AssistantToolCallRepository.list_for_chat(chat_id, created_by=owner_id)
        active_runs = [run for run in runs if run.get("status") in ACTIVE_RUN_STATUSES]
        active_calls = [call for call in calls if call.get("phase") in ACTIVE_TOOL_PHASES]
        provider_id, model_id = self._model_pair(dict(chat.get("model") or {}))
        state = control_state(chat)
        goal = state.goal.objective if state.goal else "无"
        todos = ", ".join(f"{item.content}[{item.status}]" for item in state.todos) or "无"
        trace_summary = (
            f"runs={len(runs)}, completed={sum(run.get('status') == 'completed' for run in runs)}, "
            f"failed={sum(run.get('status') == 'failed' for run in runs)}, "
            f"latest_trace={(runs[0].get('trace_id') if runs else '无')}"
        )
        message = (
            f"模型：{provider_id}::{model_id or '未选择'}；"
            f"Plan Mode：{'开' if state.plan_mode else '关'}；"
            f"权限：{PERMISSION_LABELS[state.permission_mode]}；"
            f"目标：{goal}；Todo：{todos}；"
            f"active run：{active_runs[0].get('run_id') if active_runs else '无'}；"
            f"active tool call：{active_calls[0].get('call_id') if active_calls else '无'}；"
            f"Trace：{trace_summary}"
        )
        return CommandHandlerResult(status="success", message=message)


assistant_command_service = AssistantCommandService()
