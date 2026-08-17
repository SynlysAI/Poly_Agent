"""Assistant Slash Command 执行平面与会话控制服务。"""

from __future__ import annotations

import difflib
import hashlib
from dataclasses import dataclass, replace
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.time import utc_now
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.research_engine_repositories import (
    AssistantChatRepository,
    AssistantRunRepository,
    AssistantToolCallRepository,
)
from app.schemas.assistant_commands import (
    CommandCatalogData,
    CommandChoice,
    CommandDescriptor,
    CommandExecution,
    CommandInteraction,
    SessionControlState,
)
from app.schemas.assistant_runs import AssistantRun, AssistantRunCreate
from app.services.assistant_chat_service import actor_id
from app.services.assistant_command_parser import CommandParseError, parse_command
from app.services.assistant_command_registry import AssistantCommandRegistry
from app.services.assistant_run_service import AssistantRunService
from app.services.assistant_session_control import (
    PERMISSION_LABELS,
    PERMISSION_MODES,
    control_state,
    tool_execution_block_reason,
)
from app.services.llm_model_service import LLMModelService


CATALOG_VERSION = "assistant-command-catalog-v1"
ACTIVE_RUN_STATUSES = {"queued", "running"}
ACTIVE_TOOL_PHASES = {"requested", "awaiting_input", "awaiting_confirmation", "queued", "running"}


@dataclass
class CommandHandlerResult:
    """内置命令处理器的内部执行结果。"""

    status: str
    message: str
    interaction: CommandInteraction | None = None
    run: AssistantRun | None = None
    source_event: str | None = None


class AssistantCommandService:
    """统一命令解析、目录、权限、处理器与事件生命周期。"""

    def __init__(self) -> None:
        self.registry = AssistantCommandRegistry()
        self.run_service = AssistantRunService()
        self.llm_model_service = LLMModelService()
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
        chat = self._owned_chat(chat_id, current_user)
        items = self.registry.descriptors()
        return CommandCatalogData(
            items=items,
            total=len(items),
            session_state=control_state(chat),
            catalog_version=CATALOG_VERSION,
        )

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

        registered = self.registry.resolve(parsed_name) if parsed else None
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
            "download_url": None,
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
            if descriptor.category == "tool":
                reason = tool_execution_block_reason(chat)
                if reason:
                    raise HTTPException(
                        status_code=403,
                        detail={"code": reason, "message": "当前会话权限不允许执行工具命令"},
                    )
            if registered.handler is None:
                raise ValueError(f"命令 /{name} 尚未注册处理器")
            result = registered.handler(
                chat,
                parsed.raw_args,
                payload.payload,
                current_user,
                command_id,
            )
            final_status = result.status
            message = result.message
            interaction = result.interaction
            run = result.run
            source_event = result.source_event
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
            source_event = (run_event or {}).get("event_id")
            error = {"error_type": exc.__class__.__name__, "message": message}

        latest_chat = self._latest_chat(payload.chat_id, owner_id)
        state = control_state(latest_chat)
        finished_at = utc_now()
        result_document = {
            **document,
            "status": final_status,
            "message": message,
            "state_after": state.model_dump(mode="python"),
            "interaction": interaction.model_dump(mode="python") if interaction else None,
            "run_id": getattr(run, "run_id", None),
            "call_id": None,
            "download_url": None,
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
            event_types={"command.run", "command.done"},
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
