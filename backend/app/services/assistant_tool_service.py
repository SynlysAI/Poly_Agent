"""Ordered delivery state machine for assistant algorithm tool calls."""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.core.time import utc_now
from app.infra.computation_repositories import AuditEventRepository
from app.infra.research_engine_repositories import (
    AlgorithmRunRepository,
    AssistantChatRepository,
    AssistantMessageRepository,
    AssistantToolCallRepository,
)
from app.schemas.agent_tools import (
    AgentTool,
    AssistantToolCall,
    AssistantToolCallConfirm,
    AssistantToolCallCreate,
    AssistantToolCallEvent,
    AssistantToolCallInputUpdate,
    AssistantToolInputRequiredEvent,
)
from app.schemas.research_engine import AlgorithmAssetSpec, AlgorithmRunCreate
from app.services.agent_tool_service import agent_tool_service
from app.services.assistant_provider_errors import TOOL_ARGUMENTS_INVALID
from app.services.assistant_runtime_asset_service import assistant_runtime_asset_service
from app.services.assistant_session_control import ensure_tool_confirmation_allowed
from app.services.assistant_tool_contract import SENSITIVE_KEYS, missing_inputs, validate_arguments
from app.services.research_engine_service import ResearchEngineService


CALLABLE_PHASES = {"requested", "awaiting_input", "awaiting_confirmation"}
TERMINAL_PHASES = {"completed", "failed", "canceled"}
CONTINUATION_TERMINAL_PHASES = {"completed", "failed"}
CONTINUATION_EVENT_TYPE = "tool.continuation.scheduled"


def _actor_context(current_user: dict[str, str] | None) -> tuple[str, str, bool]:
    if current_user is None:
        return "demo_user", "admin", True
    role = current_user.get("role", "user")
    return current_user.get("user_id", ""), role, role == "admin"


def _redact(value: Any, key: str = "") -> Any:
    if key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, dict):
        return {str(k): _redact(v, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact(item, key) for item in value]
    return value


class AssistantToolCallService:
    """持久化调用状态并把确认后的执行委托给 ResearchEngine。"""

    @staticmethod
    def _tool(algorithm_id: str, current_user: dict[str, str] | None) -> AgentTool:
        user_id, role, is_admin = _actor_context(current_user)
        tool = agent_tool_service.resolve_callable(
            algorithm_id,
            user_id=user_id,
            role=role,
            is_admin=is_admin,
        )
        if tool is None:
            raise HTTPException(status_code=403, detail="算法工具不可用或当前用户无权限调用")
        return tool

    @staticmethod
    def _validate_arguments(tool: AgentTool, arguments: dict[str, Any]) -> tuple[list[str], dict[str, str]]:
        missing, errors = validate_arguments(tool, arguments)
        sensitive_error = errors.pop("__sensitive__", None)
        if sensitive_error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": TOOL_ARGUMENTS_INVALID,
                    "message": sensitive_error,
                    "details": {},
                },
            )
        unknown_error = errors.pop("__unknown__", None)
        if unknown_error:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": TOOL_ARGUMENTS_INVALID,
                    "message": unknown_error,
                    "details": {},
                },
            )
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": TOOL_ARGUMENTS_INVALID,
                    "message": "算法参数校验失败",
                    "details": errors,
                },
            )
        return missing, errors

    @staticmethod
    def _field_type_token(tool: AgentTool, field: str) -> str:
        description = str((tool.input_schema.fields or {}).get(field, "")).strip()
        return description.split(" -", 1)[0].strip().lower()

    @classmethod
    def _coerce_arguments(cls, tool: AgentTool, arguments: dict[str, Any]) -> dict[str, Any]:
        """修正模型提案里“列表字段传成单个值”的常见错误。

        模型经常把 list 类型的字段直接传成单个对象/字符串，导致校验返回
        TOOL_INPUT_INVALID。这里对 list/array 字段做保守修复：
        - 已是 list 原样保留；
        - 字符串能解析成 JSON list 时直接采用；
        - 其余非 list 值包装成单元素列表。
        """
        coerced = dict(arguments or {})
        for field, value in list(coerced.items()):
            token = cls._field_type_token(tool, field)
            if not token.startswith(("list", "array")):
                continue
            if value is None:
                # 缺失值留给 missing_fields 校验，生成“等待补充参数”卡片。
                continue
            if isinstance(value, list):
                continue
            if isinstance(value, str):
                try:
                    parsed = json.loads(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    parsed = None
                if isinstance(parsed, list):
                    coerced[field] = parsed
                    continue
                if isinstance(parsed, dict):
                    coerced[field] = [parsed]
                    continue
            coerced[field] = [value]
        return coerced

    @staticmethod
    def _initial_argument_sources(
        provider_arguments: dict[str, Any],
        field_defaults: dict[str, Any],
    ) -> dict[str, str]:
        """记录初始参数来源，区分 provider 提案与输入契约默认值。

        Args:
            provider_arguments: provider 或受信任编排器提交的参数。
            field_defaults: 输入契约声明的字段默认值。

        Returns:
            字段到 provider / schema_default 来源的映射。
        """
        sources = {field: "provider" for field in provider_arguments}
        sources.update({
            field: "schema_default"
            for field in field_defaults
            if field not in provider_arguments
        })
        return sources

    @staticmethod
    def _validate_asset_refs(tool: AgentTool, refs: dict[str, Any]) -> None:
        declared_keys = {spec.key for spec in tool.input_assets}
        unknown = sorted(set(refs) - declared_keys)
        if unknown:
            raise HTTPException(status_code=422, detail=f"未声明的输入文件引用: {', '.join(unknown)}")
        for asset_key, raw_ref in refs.items():
            artifact_id = raw_ref.get("artifact_id") if isinstance(raw_ref, dict) else raw_ref
            if not isinstance(artifact_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", artifact_id):
                raise HTTPException(status_code=422, detail=f"输入文件 {asset_key} 的 artifact_id 无效")

    @staticmethod
    def _missing_assets(
        tool: AgentTool,
        refs: dict[str, Any],
        uploaded: list[dict[str, Any]],
    ) -> list[AlgorithmAssetSpec]:
        uploaded_keys = {str(item.get("asset_key")) for item in uploaded}
        return [
            spec
            for spec in tool.input_assets
            if spec.required and spec.key not in refs and spec.key not in uploaded_keys
        ]

    @staticmethod
    def _public_document(document: dict[str, Any]) -> AssistantToolCall:
        public = {key: value for key, value in document.items() if not key.startswith("_")}
        public["uploaded_assets"] = [
            {key: value for key, value in item.items() if key != "_path"}
            for item in (public.get("uploaded_assets") or [])
        ]
        # Events are replayed by the dedicated SSE endpoint and aggregated into
        # chat restoration responses; omit them from the compact call response.
        public.pop("events", None)
        return AssistantToolCall.model_validate(public)

    @staticmethod
    def _ensure_chat_link(
        chat_id: str | None,
        message_id: str | None,
        user_id: str,
    ) -> None:
        if not chat_id:
            if message_id:
                raise HTTPException(status_code=422, detail="message_id 必须和 chat_id 一起提供")
            return
        chat = AssistantChatRepository.find_one({"chat_id": chat_id})
        if chat is None:
            # Legacy callers may provide a stable chat ID before the first message.
            now = utc_now()
            AssistantChatRepository.save(
                "chat_id",
                {
                    "chat_id": chat_id,
                    "title": "新对话",
                    "created_by": user_id,
                    "archived": False,
                    "model": {},
                    "mode": "qa",
                    "knowledge_base_ids": [],
                    "knowledge_base_names": [],
                    "use_web_search": False,
                    "selected_tool_ids": [],
                    "plan_mode": False,
                    "permission_mode": "workspace_write",
                    "goal": None,
                    "todos": [],
                    "compaction": None,
                    "command_event_seq": 0,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        elif chat.get("created_by") != user_id:
            raise HTTPException(status_code=403, detail="无权限关联该会话")
        if message_id:
            message = AssistantMessageRepository.find_one(
                {"message_id": message_id, "chat_id": chat_id, "created_by": user_id}
            )
            if message is None:
                raise HTTPException(status_code=404, detail=f"消息 '{message_id}' 不存在")

    @staticmethod
    def _event(document: dict[str, Any]) -> dict[str, Any]:
        """把工具调用文档转换为前端可回放的状态事件。"""
        return AssistantToolCallEvent(
            call_id=document["call_id"],
            command_id=document.get("command_id"),
            provider_tool_call_id=document.get("provider_tool_call_id"),
            tool_id=document["tool_id"],
            algorithm_id=document["algorithm_id"],
            algorithm_version_id=document.get("algorithm_version_id"),
            tool_name=document["tool_name"],
            phase=document["phase"],
            arguments=_redact(document.get("arguments") or {}),
            function_name=document.get("function_name"),
            provider_tool_call_index=document.get("provider_tool_call_index"),
            raw_arguments=_redact(document.get("raw_arguments")),
            arguments_parse_error=document.get("arguments_parse_error"),
            finish_reason=document.get("finish_reason"),
            proposal_route=document.get("proposal_route"),
            proposal_usage=document.get("proposal_usage"),
            schema_digest=document.get("schema_digest"),
            result_summary=_redact(document.get("result_summary") or {}),
            artifact_refs=document.get("artifact_refs") or [],
            error=_redact(document.get("error")) if document.get("error") else None,
            created_at=utc_now(),
        ).model_dump(mode="python")

    @classmethod
    def _append_phase_event(cls, document: dict[str, Any]) -> None:
        AssistantToolCallRepository.append_event(document["call_id"], cls._event(document))

    @classmethod
    def _append_input_event(cls, document: dict[str, Any], tool: AgentTool) -> None:
        missing_fields = document.get("missing_fields") or []
        missing_assets = cls._missing_assets(
            tool,
            document.get("input_asset_refs") or {},
            document.get("uploaded_assets") or [],
        )
        required_assets = [item.model_dump(mode="python") for item in missing_assets]
        if not missing_fields and not required_assets:
            return
        event = AssistantToolInputRequiredEvent(
            call_id=document["call_id"],
            command_id=document.get("command_id"),
            missing_fields=missing_fields,
            field_schema=tool.input_schema,
            input_json_schema=tool.input_json_schema,
            presentation=tool.presentation,
            required_assets=required_assets,
            created_at=utc_now(),
        ).model_dump(mode="python")
        AssistantToolCallRepository.append_event(document["call_id"], event)

    @classmethod
    def _fallback_source_context(cls, document: dict[str, Any]) -> dict[str, Any]:
        """为历史数据构建最小可续答上下文。

        Args:
            document: 旧版工具调用文档。

        Returns:
            包含原消息、会话和模型快照的可续答上下文。
        """
        return {
            "original_user_message_id": document.get("message_id"),
            "chat_id": document.get("chat_id"),
            "selected_tool_ids": [document.get("tool_id")] if document.get("tool_id") else [],
            "mode": "qa",
            "model_request": document.get("proposal_route") or {},
            "route_snapshot": document.get("proposal_route") or {},
            "context_manifest_digest": document.get("context_manifest_digest"),
        }

    @classmethod
    def _schedule_continuation(cls, document: dict[str, Any]) -> None:
        """在工具成功或失败后写入服务端续答 outbox。"""
        if document.get("phase") not in CONTINUATION_TERMINAL_PHASES:
            return
        if document.get("continuation_state") in {"scheduled", "completed"} and document.get("continuation_run_id"):
            return
        source_context = document.get("source_context") or cls._fallback_source_context(document)
        command_owned = bool(
            source_context.get("command_id")
            or source_context.get("origin") == "slash_command"
            or document.get("command_id")
        )
        task_content = str(source_context.get("task_content") or "").strip()
        if command_owned and not task_content:
            skip_update = {
                "continuation_state": "skipped",
                "continuation_error": {
                    "error_type": "MISSING_TASK_CONTENT",
                    "message": "未提供任务说明，仅展示工具结果，不自动生成续答",
                },
                "updated_at": utc_now(),
            }
            AssistantToolCallRepository.update_fields(document["call_id"], skip_update)
            document.update(skip_update)
            return
        if not source_context.get("original_user_message_id") and not document.get("message_id"):
            AssistantToolCallRepository.update_fields(
                document["call_id"],
                {
                    "continuation_state": "skipped",
                    "continuation_error": {
                        "error_type": "MISSING_CONTINUATION_CONTEXT",
                        "message": "缺少原用户消息，无法自动续答",
                    },
                    "updated_at": utc_now(),
                },
            )
            document.update(
                {
                    "continuation_state": "skipped",
                    "continuation_error": {
                        "error_type": "MISSING_CONTINUATION_CONTEXT",
                        "message": "缺少原用户消息，无法自动续答",
                    },
                    "updated_at": utc_now(),
                }
            )
            return

        update = {
            "continuation_state": "pending",
            "continuation_attempts": 0,
            "continuation_next_retry_at": None,
            "continuation_dead_letter_reason": None,
            "continuation_error": None,
            "updated_at": utc_now(),
        }
        AssistantToolCallRepository.update_fields(document["call_id"], update)
        document.update(update)
        AssistantToolCallRepository.append_event(
            document["call_id"],
            {
                "type": CONTINUATION_EVENT_TYPE,
                "call_id": document["call_id"],
                "continuation_state": "pending",
                "source_context": _redact(source_context),
            },
        )

    @classmethod
    def _transition(cls, document: dict[str, Any], phase: str, **fields: Any) -> dict[str, Any]:
        now = utc_now()
        update = {"phase": phase, "updated_at": now, **fields}
        AssistantToolCallRepository.update_fields(document["call_id"], update)
        document.update(update)
        if document.get("chat_id"):
            AssistantChatRepository.update_owned(
                document["chat_id"],
                document.get("created_by", ""),
                {"updated_at": now},
            )
        cls._append_phase_event(document)
        if phase in CONTINUATION_TERMINAL_PHASES:
            cls._schedule_continuation(document)
        return document

    @classmethod
    def _transition_pending(
        cls,
        document: dict[str, Any],
        phase: str,
        **fields: Any,
    ) -> dict[str, Any]:
        update = {"phase": phase, "updated_at": utc_now(), **fields}
        claimed = AssistantToolCallRepository.update_if_phase(
            document["call_id"],
            CALLABLE_PHASES,
            update,
        )
        if not claimed:
            raise HTTPException(status_code=409, detail="工具调用状态已变化，请刷新后重试")
        document.update(update)
        if document.get("chat_id"):
            AssistantChatRepository.update_owned(
                document["chat_id"],
                document.get("created_by", ""),
                {"updated_at": update["updated_at"]},
            )
        cls._append_phase_event(document)
        return document

    @classmethod
    def create(cls, payload: AssistantToolCallCreate, current_user: dict[str, str] | None) -> AssistantToolCall:
        user_id, role, _is_admin = _actor_context(current_user)
        algorithm_id = payload.tool_id.removeprefix("algorithm:")
        cls._ensure_chat_link(payload.chat_id, payload.message_id, user_id)
        tool = cls._tool(algorithm_id, current_user)
        field_defaults = dict(tool.input_schema.field_defaults or {})
        arguments = dict(field_defaults)
        arguments.update(payload.arguments)
        argument_sources = cls._initial_argument_sources(payload.arguments, field_defaults)
        arguments = cls._coerce_arguments(tool, arguments)
        missing_fields, _ = cls._validate_arguments(tool, arguments)
        cls._validate_asset_refs(tool, payload.input_asset_refs)
        uploaded_assets: list[dict[str, Any]] = []
        missing_result = missing_inputs(tool, arguments, payload.input_asset_refs, uploaded_assets)
        missing_assets = missing_result["assets"]
        next_phase = "awaiting_input" if missing_fields or missing_assets else "awaiting_confirmation"
        now = utc_now()
        source_context = dict(payload.source_context or {})
        trace_id = str(payload.trace_id or source_context.get("trace_id") or payload.assistant_run_id or "")
        source_context["argument_sources"] = _redact(argument_sources)
        source_context["trace_id"] = trace_id
        source_context["command_id"] = payload.command_id
        source_context.setdefault("original_user_message_id", payload.message_id)
        source_context.setdefault("chat_id", payload.chat_id)
        source_context.setdefault("selected_tool_ids", [payload.tool_id])
        source_context.setdefault("model_request", payload.proposal_route or {})
        source_context.setdefault("route_snapshot", payload.proposal_route or {})
        source_context.setdefault("context_manifest_digest", payload.schema_digest)
        document = {
            "call_id": f"atc_{uuid4().hex[:16]}",
            "trace_id": trace_id,
            "command_id": payload.command_id,
            "provider_tool_call_id": payload.provider_tool_call_id,
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "assistant_run_id": payload.assistant_run_id,
            "tool_id": payload.tool_id,
            "algorithm_id": algorithm_id,
            "algorithm_version_id": tool.active_version_id,
            "algorithm_version": tool.version,
            "tool_name": tool.name,
            "selection_reason": payload.selection_reason,
            "selection_confidence": payload.selection_confidence,
            "phase": "requested",
            "continuation_state": None,
            "continuation_run_id": None,
            "continuation_error": None,
            "continuation_attempts": 0,
            "continuation_next_retry_at": None,
            "continuation_dead_letter_reason": None,
            "source_context": _redact(source_context),
            "field_schema": tool.input_schema.model_dump(mode="python"),
            "input_json_schema": tool.input_json_schema,
            "presentation": tool.presentation,
            "output_schema": tool.output_schema.model_dump(mode="python"),
            "attributions": [
                item.model_dump(mode="python")
                for item in [tool.developer_attribution, *tool.framework_attributions, *tool.method_attributions]
                if item is not None
            ],
            "arguments": _redact(arguments),
            "function_name": payload.function_name,
            "provider_tool_call_index": payload.provider_tool_call_index,
            "raw_arguments": _redact(payload.raw_arguments),
            "arguments_parse_error": payload.arguments_parse_error,
            "finish_reason": payload.finish_reason,
            "proposal_route": payload.proposal_route,
            "proposal_usage": payload.proposal_usage,
            "schema_digest": payload.schema_digest or tool.schema_digest,
            "input_asset_refs": _redact(payload.input_asset_refs),
            "uploaded_assets": uploaded_assets,
            "missing_fields": missing_fields,
            "required_assets": [item.model_dump(mode="python") for item in missing_assets],
            "requires_confirmation": tool.requires_confirmation,
            "run_id": None,
            "run_status": None,
            "result_summary": {},
            "artifact_refs": [],
            "error": None,
            "created_by": user_id,
            "_actor_role": role,
            "created_at": now,
            "updated_at": now,
            "confirmed_at": None,
            "canceled_at": None,
            "started_at": None,
            "finished_at": None,
            "events": [],
        }
        AssistantToolCallRepository.save("call_id", document)
        cls._append_phase_event(document)
        cls._audit(document, "assistant_tool_call_requested", {"status": "requested"})
        cls._transition(document, next_phase)
        cls._append_input_event(document, tool)
        if next_phase == "awaiting_confirmation" and not tool.requires_confirmation:
            return cls.confirm(document["call_id"], AssistantToolCallConfirm(), current_user)
        return cls._public_document(document)

    @classmethod
    def get(cls, call_id: str, current_user: dict[str, str] | None) -> AssistantToolCall:
        user_id, _role, _is_admin = _actor_context(current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id})
        if not document:
            raise HTTPException(status_code=404, detail=f"工具调用 '{call_id}' 不存在")
        if document.get("created_by") != user_id:
            raise HTTPException(status_code=403, detail="无权限访问该工具调用")
        cls._sync_run_state(document, current_user)
        return cls._public_document(document)

    @classmethod
    def _sync_run_state(cls, document: dict[str, Any], current_user: dict[str, str] | None) -> None:
        run_id = document.get("run_id")
        if not run_id:
            return
        run_doc = AlgorithmRunRepository.find_one({"run_id": run_id})
        if not run_doc:
            return
        status = str(run_doc.get("status") or "queued")
        phase = {"queued": "queued", "running": "running", "completed": "completed", "failed": "failed", "canceled": "canceled"}.get(status)
        if not phase or (phase == document.get("phase") and document.get("run_status") == status):
            return
        update = {
            "phase": phase,
            "run_status": status,
            "result_summary": _redact(run_doc.get("output_summary") or {}),
            "artifact_refs": cls._public_artifact_refs(run_doc.get("artifact_refs") or []),
            "error": _redact(run_doc.get("error")) if run_doc.get("error") else None,
            "started_at": run_doc.get("started_at") or document.get("started_at"),
            "finished_at": run_doc.get("finished_at"),
            "updated_at": run_doc.get("updated_at") or utc_now(),
        }
        AssistantToolCallRepository.update_fields(document["call_id"], update)
        document.update(update)
        cls._append_phase_event(document)
        if phase in TERMINAL_PHASES:
            cls._cleanup_uploads(document)
        if phase in CONTINUATION_TERMINAL_PHASES:
            cls._schedule_continuation(document)

    @classmethod
    def reconcile_orphans(cls) -> int:
        """扫描 queued/running 工具调用并对账其 AlgorithmRun 状态。

        Returns:
            本轮对账的调用数量。
        """
        count = 0
        for document in AssistantToolCallRepository.list_orphan_running():
            run_id = document.get("run_id")
            if not run_id:
                continue
            cls._sync_run_state(document, None)
            count += 1
        return count

    @classmethod
    def update_input(
        cls,
        call_id: str,
        payload: AssistantToolCallInputUpdate,
        current_user: dict[str, str] | None,
    ) -> AssistantToolCall:
        cls.get(call_id, current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        if document.get("phase") not in CALLABLE_PHASES:
            raise HTTPException(status_code=409, detail="当前工具调用已结束，不能补充参数")
        tool = cls._tool(document["algorithm_id"], current_user)
        arguments = dict(document.get("arguments") or {})
        arguments.update(payload.arguments)
        source_context = dict(document.get("source_context") or {})
        argument_sources = dict(source_context.get("argument_sources") or {})
        argument_sources.update({field: "user_edit" for field in payload.arguments})
        source_context["argument_sources"] = _redact(argument_sources)
        refs = dict(document.get("input_asset_refs") or {})
        refs.update(payload.input_asset_refs)
        missing_fields, _ = cls._validate_arguments(tool, arguments)
        cls._validate_asset_refs(tool, refs)
        missing_assets = cls._missing_assets(tool, refs, document.get("uploaded_assets") or [])
        phase = "awaiting_input" if missing_fields or missing_assets else "awaiting_confirmation"
        cls._transition_pending(
            document,
            phase,
            arguments=_redact(arguments),
            input_asset_refs=_redact(refs),
            source_context=_redact(source_context),
            missing_fields=missing_fields,
            required_assets=[item.model_dump(mode="python") for item in missing_assets],
        )
        cls._append_input_event(document, tool)
        return cls._public_document(document)

    @classmethod
    def upload_input_assets(
        cls,
        call_id: str,
        uploads: dict[str, dict[str, Any]],
        current_user: dict[str, str] | None,
    ) -> AssistantToolCall:
        cls.get(call_id, current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        if document.get("phase") not in CALLABLE_PHASES:
            raise HTTPException(status_code=409, detail="当前工具调用已结束，不能上传附件")
        assistant_runtime_asset_service.cleanup_expired()
        uploaded = list(document.get("uploaded_assets") or [])
        tool = cls._tool(document["algorithm_id"], current_user)
        input_specs = {spec.key: spec for spec in tool.input_assets}
        new_asset_ids: list[str] = []
        for asset_key, upload in uploads.items():
            if asset_key not in input_specs:
                raise HTTPException(status_code=422, detail=f"未声明的输入文件: {asset_key}")
            filename = Path(str(upload.get("filename") or asset_key)).name
            content = upload.get("content") or b""
            content_type = str(upload.get("content_type") or "application/octet-stream")
            ResearchEngineService._validate_input_asset_upload(
                asset_key,
                filename,
                content_type,
                content,
                input_specs[asset_key],
            )
            stored = assistant_runtime_asset_service.store(
                call_id=call_id,
                chat_id=document.get("chat_id"),
                created_by=document.get("created_by"),
                asset_key=asset_key,
                filename=filename,
                content_type=content_type,
                content=content,
            )
            new_asset_ids.append(stored["asset_id"])
            uploaded = [item for item in uploaded if item.get("asset_key") != asset_key]
            uploaded.append(assistant_runtime_asset_service.public_metadata(stored))
        missing_fields, _ = cls._validate_arguments(tool, document.get("arguments") or {})
        missing_assets = cls._missing_assets(tool, document.get("input_asset_refs") or {}, uploaded)
        phase = "awaiting_input" if missing_fields or missing_assets else "awaiting_confirmation"
        try:
            cls._transition_pending(
                document,
                phase,
                uploaded_assets=uploaded,
                missing_fields=missing_fields,
                required_assets=[item.model_dump(mode="python") for item in missing_assets],
            )
        except Exception:
            for asset_id in new_asset_ids:
                cls._release_asset_by_id(asset_id)
            raise
        cls._append_input_event(document, tool)
        for asset in uploaded:
            AssistantToolCallRepository.append_event(
                document["call_id"],
                {
                    "type": "asset.uploaded",
                    "call_id": document["call_id"],
                    "asset_id": asset.get("asset_id"),
                    "asset_key": asset.get("asset_key"),
                    "filename": asset.get("filename"),
                    "size_bytes": asset.get("size_bytes"),
                    "created_at": utc_now(),
                },
            )
        return cls._public_document(document)

    @classmethod
    def confirm(
        cls,
        call_id: str,
        payload: AssistantToolCallConfirm,
        current_user: dict[str, str] | None,
    ) -> AssistantToolCall:
        cls.get(call_id, current_user)
        user_id, _role, _is_admin = _actor_context(current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        phase = document.get("phase")
        if phase == "completed":
            return cls._public_document(document)
        if phase in {"canceled", "failed"}:
            raise HTTPException(status_code=409, detail="当前工具调用已结束，不能确认")
        if phase in {"queued", "running"}:
            return cls._public_document(document)
        ensure_tool_confirmation_allowed(document, user_id)
        tool = cls._tool(document["algorithm_id"], current_user)
        arguments = dict(document.get("arguments") or {})
        if payload.arguments is not None:
            arguments.update(payload.arguments)
        source_context = dict(document.get("source_context") or {})
        argument_sources = dict(source_context.get("argument_sources") or {})
        argument_sources.update({field: "user_edit" for field in payload.arguments or {}})
        source_context["argument_sources"] = _redact(argument_sources)
        refs = dict(document.get("input_asset_refs") or {})
        if payload.input_asset_refs is not None:
            refs.update(payload.input_asset_refs)
        missing_fields, _ = cls._validate_arguments(tool, arguments)
        cls._validate_asset_refs(tool, refs)
        missing_assets = cls._missing_assets(tool, refs, document.get("uploaded_assets") or [])
        if missing_fields or missing_assets:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "TOOL_INPUT_REQUIRED",
                    "missing_fields": missing_fields,
                    "missing_assets": [item.key for item in missing_assets],
                },
            )
        if tool.requires_confirmation is True and phase != "awaiting_confirmation":
            raise HTTPException(status_code=409, detail="工具调用尚未完成参数补充")
        # The version is resolved only after confirmation, then frozen on the call and run.
        now = utc_now()
        running_fields = {
            "phase": "queued",
            "run_status": "queued",
            "arguments": _redact(arguments),
            "input_asset_refs": _redact(refs),
            "source_context": _redact(source_context),
            "algorithm_version_id": tool.active_version_id,
            "algorithm_version": tool.version,
            "started_at": None,
            "confirmed_at": now,
            "updated_at": now,
            "missing_fields": [],
            "required_assets": [],
        }
        claimed = AssistantToolCallRepository.update_if_phase(call_id, CALLABLE_PHASES, running_fields)
        if not claimed:
            latest = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
            if latest.get("phase") in {"running", "completed"}:
                return cls._public_document(latest)
            raise HTTPException(status_code=409, detail="当前工具调用不能确认")
        document.update(running_fields)
        AssistantToolCallRepository.append_event(
            call_id,
            {
                "type": "tool.confirmed",
                "call_id": call_id,
                "arguments": _redact(arguments),
                "confirmed_at": now,
            },
        )
        cls._audit(
            document,
            "assistant_tool_call_confirmed",
            {"status": "queued", "algorithm_version_id": tool.active_version_id},
        )
        is_admin = _is_admin
        legacy_sync = False
        try:
            try:
                uploads = cls._uploads_from_document(document)
                run_payload = AlgorithmRunCreate(
                    algorithm_id=document["algorithm_id"],
                    algorithm_version_id=document.get("algorithm_version_id"),
                    trigger_source="human_workflow",
                    trigger_context_id=call_id,
                    input_snapshot=arguments,
                    input_asset_refs=refs,
                    reason=f"Assistant 工具调用 {call_id}",
                )
                run = ResearchEngineService().create_algorithm_run(
                    run_payload,
                    actor_user_id=user_id,
                    is_admin=is_admin,
                    input_asset_uploads=uploads,
                    execute=False,
                )
            except TypeError:
                # Compatibility with legacy test doubles/integrations that expose the old signature.
                legacy_sync = True
                run = ResearchEngineService().create_algorithm_run(
                    run_payload,
                    actor_user_id=user_id,
                    is_admin=is_admin,
                    input_asset_uploads=uploads,
                )
            except Exception as exc:
                run_doc = AlgorithmRunRepository.find_one({"trigger_context_id": call_id})
                error = {
                    "error_type": type(exc).__name__,
                    "message": cls._safe_error_message(exc),
                    "retryable": False,
                }
                update = {
                    "run_id": (run_doc or {}).get("run_id"),
                    "error": _redact(error),
                    "finished_at": utc_now(),
                }
                cls._transition(document, "failed", **update)
                cls._audit(
                    document,
                    "assistant_tool_call_failed",
                    {"status": "failed", "error": update["error"]},
                )
                return cls._public_document(document)

            run_id = getattr(run, "run_id", None)
            if legacy_sync:
                cls._transition(document, "running", run_status="running", started_at=now)
                output_summary = dict(getattr(run, "output_summary", {}) or {})
                artifact_refs = cls._public_artifact_refs(getattr(run, "artifact_refs", []) or [])
                update = {
                    "run_id": run_id,
                    "run_status": getattr(run, "status", "completed"),
                    "result_summary": _redact(output_summary),
                    "artifact_refs": artifact_refs,
                    "finished_at": utc_now(),
                }
                cls._transition(document, "completed", **update)
                cls._audit(document, "assistant_tool_call_completed", {"status": "completed", "run_id": run_id})
                cls._cleanup_uploads(document)
                return cls._public_document(document)
            update = {
                "run_id": run_id,
                "run_status": getattr(run, "status", "queued"),
            }
            cls._transition(document, "queued", **update)
            cls._schedule_run(document, run_payload, user_id, is_admin, uploads)
            return cls._public_document(document)
        except Exception:
            raise

    @classmethod
    def _schedule_run(cls, document: dict[str, Any], payload: AlgorithmRunCreate, user_id: str, is_admin: bool, uploads: dict[str, dict[str, Any]]) -> None:
        def execute() -> None:
            try:
                if not AlgorithmRunRepository.claim_queued(document.get("run_id"), f"lui-{document.get('call_id')}", utc_now()):
                    return
                run = ResearchEngineService().create_algorithm_run(
                    payload,
                    actor_user_id=user_id,
                    is_admin=is_admin,
                    input_asset_uploads=uploads,
                    existing_run_id=document.get("run_id"),
                )
                current = AssistantToolCallRepository.find_one({"call_id": document["call_id"]}) or dict(document)
                cls._sync_run_state(current, None)
            except Exception as exc:
                latest = AssistantToolCallRepository.find_one({"call_id": document["call_id"]}) or dict(document)
                error = {"error_type": type(exc).__name__, "message": cls._safe_error_message(exc), "retryable": False}
                cls._transition(latest, "failed", error=error, finished_at=utc_now(), run_status="failed")
            finally:
                cls._cleanup_uploads(document)
        threading.Thread(target=execute, name=f"algorithm-run-{document.get('run_id')}", daemon=True).start()

    @classmethod
    def cancel(cls, call_id: str, current_user: dict[str, str] | None) -> AssistantToolCall:
        cls.get(call_id, current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        if document.get("phase") == "canceled":
            return cls._public_document(document)
        if document.get("phase") in {"running", "completed", "failed"}:
            raise HTTPException(status_code=409, detail="运行中的工具调用不能取消，或调用已经结束")
        cls._transition_pending(document, "canceled", canceled_at=utc_now())
        cls._audit(document, "assistant_tool_call_canceled", {"status": "canceled"})
        cls._cleanup_uploads(document)
        return cls._public_document(document)

    @staticmethod
    def _cleanup_uploads(document: dict[str, Any]) -> None:
        call_id = document["call_id"]
        AssistantToolCallService._release_legacy_paths(document)
        assistant_runtime_asset_service.release_call_assets(call_id)
        public_assets = [
            {
                key: value
                for key, value in item.items()
                if key != "_path" and key != "status"
            }
            for item in (document.get("uploaded_assets") or [])
        ]
        document["uploaded_assets"] = public_assets
        AssistantToolCallRepository.update_fields(
            document["call_id"],
            {"uploaded_assets": public_assets},
        )

    @staticmethod
    def _release_legacy_paths(document: dict[str, Any]) -> None:
        """兼容旧临时文件路径，迁移期间仍执行本地删除。"""
        root = (settings.runtime_root / "assistant-tool-calls" / document["call_id"]).resolve()
        for item in document.get("uploaded_assets") or []:
            raw_path = item.get("_path")
            if not raw_path:
                continue
            path = Path(raw_path).resolve()
            if not path.is_relative_to(root):
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass

    @staticmethod
    def _release_asset_by_id(asset_id: str) -> None:
        """按资产 ID 释放单个受管附件，避免上传半途留下孤儿文件。"""
        try:
            assistant_runtime_asset_service.release_call_assets(
                assistant_runtime_asset_service.get(asset_id).call_id
            )
        except Exception:
            pass

    @staticmethod
    def _uploads_from_document(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """从工具调用文档构造 ResearchEngine 输入文件上传字典。"""
        uploads: dict[str, dict[str, Any]] = {}
        for item in document.get("uploaded_assets") or []:
            asset_key = str(item.get("asset_key") or "")
            if not asset_key:
                continue
            asset_id = item.get("asset_id")
            if asset_id:
                content = assistant_runtime_asset_service.read(
                    call_id=document["call_id"],
                    asset_id=str(asset_id),
                )
            elif item.get("_path"):
                content = Path(item["_path"]).read_bytes()
            else:
                continue
            uploads[asset_key] = {
                "filename": item.get("filename") or asset_key,
                "content_type": item.get("content_type"),
                "content": content,
            }
        return uploads

    @staticmethod
    def _safe_error_message(exc: Exception) -> str:
        message = str(exc)
        for path in (settings.runtime_root, settings.outputs_root):
            path_text = str(path)
            if path_text:
                message = message.replace(path_text, "[INTERNAL_PATH]")
        return re.sub(
            r"(?i)\b(api[_-]?key|access[_-]?key|token|password|secret)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            message,
        )

    @staticmethod
    def _public_artifact_refs(refs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        allowed = {
            "artifact_id",
            "type",
            "artifact_type",
            "name",
            "content_type",
            "mime_type",
            "download_url",
            "description",
            "metadata",
        }
        return [
            {key: value for key, value in item.items() if key in allowed}
            for item in refs
            if isinstance(item, dict)
        ]

    @staticmethod
    def _audit(document: dict[str, Any], event_type: str, after: dict[str, Any]) -> None:
        AuditEventRepository.append({
            "event_id": f"audit_{uuid4().hex[:12]}",
            "event_type": event_type,
            "actor_user_id": document.get("created_by"),
            "actor_role": document.get("_actor_role"),
            "request_id": None,
            "entity_type": "assistant_tool_call",
            "entity_id": document.get("call_id"),
            "related_ids": {"algorithm_id": document.get("algorithm_id"), "run_id": document.get("run_id")},
            "before": {},
            "after": after,
            "metadata": {"source": "poly_agent"},
            "created_at": utc_now(),
        })

    @classmethod
    def stream_events(
        cls,
        call_id: str,
        current_user: dict[str, str] | None,
        after_seq: int = 0,
    ) -> Iterator[dict[str, Any]]:
        cls.get(call_id, current_user)
        yield from AssistantToolCallRepository.events_after(call_id, after_seq)


assistant_tool_call_service = AssistantToolCallService()
