"""Ordered delivery state machine for assistant algorithm tool calls."""

from __future__ import annotations

import re
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
from app.services.research_engine_service import ResearchEngineService


CALLABLE_PHASES = {"requested", "awaiting_input", "awaiting_confirmation"}
SENSITIVE_KEYS = {
    "access-key",
    "api_key",
    "api-key",
    "access_key",
    "authorization",
    "credential",
    "password",
    "secret",
    "secret-key",
    "secret_key",
    "token",
}


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
        schema = tool.input_schema
        fields = schema.fields or {}
        sensitive = sorted(set(arguments) & SENSITIVE_KEYS)
        if sensitive:
            raise HTTPException(
                status_code=422,
                detail=f"对话参数不能包含凭据字段: {', '.join(sensitive)}",
            )
        unknown = sorted(set(arguments) - set(fields))
        if unknown:
            raise HTTPException(status_code=422, detail=f"参数不在算法契约中: {', '.join(unknown)}")
        missing = [
            field
            for field in schema.required
            if field not in arguments or arguments[field] is None or arguments[field] == ""
        ]
        errors: dict[str, str] = {}
        for field, value in arguments.items():
            description = str(fields.get(field, "")).lower()
            type_name = description.split(" -", 1)[0].strip()
            normalized_type = (
                "list"
                if type_name.startswith(("list[", "array["))
                else "object"
                if type_name.startswith(("dict[", "map["))
                else type_name
            )
            valid = (
                normalized_type in {"", "any"}
                or normalized_type == "object" and isinstance(value, dict)
                or normalized_type in {"string", "str", "text"} and isinstance(value, str)
                or normalized_type in {"number", "float"}
                and isinstance(value, (int, float))
                and not isinstance(value, bool)
                or normalized_type in {"integer", "int"}
                and isinstance(value, int)
                and not isinstance(value, bool)
                or normalized_type in {"boolean", "bool"} and isinstance(value, bool)
                or normalized_type in {"array", "list"} and isinstance(value, list)
            )
            if not valid:
                errors[field] = f"参数类型不匹配，期望 {type_name or 'object'}"
            allowed = schema.field_options.get(field) or []
            if allowed and value not in allowed:
                errors[field] = f"参数值不在允许范围: {', '.join(allowed)}"
            constraints = schema.constraints.get(field) or {}
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                if constraints.get("minimum") is not None and value < constraints["minimum"]:
                    errors[field] = f"参数不能小于 {constraints['minimum']}"
                if constraints.get("maximum") is not None and value > constraints["maximum"]:
                    errors[field] = f"参数不能大于 {constraints['maximum']}"
            if isinstance(value, str):
                if constraints.get("min_length") is not None and len(value) < constraints["min_length"]:
                    errors[field] = f"参数长度不能小于 {constraints['min_length']}"
                if constraints.get("max_length") is not None and len(value) > constraints["max_length"]:
                    errors[field] = f"参数长度不能大于 {constraints['max_length']}"
                if constraints.get("pattern") and not re.fullmatch(str(constraints["pattern"]), value):
                    errors[field] = "参数格式不符合约束"
        if errors:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "TOOL_INPUT_INVALID",
                    "message": "算法参数校验失败",
                    "details": errors,
                },
            )
        return missing, errors

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
        return AssistantToolCallEvent(
            call_id=document["call_id"],
            provider_tool_call_id=document.get("provider_tool_call_id"),
            tool_id=document["tool_id"],
            algorithm_id=document["algorithm_id"],
            algorithm_version_id=document.get("algorithm_version_id"),
            tool_name=document["tool_name"],
            phase=document["phase"],
            arguments=_redact(document.get("arguments") or {}),
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
            missing_fields=missing_fields,
            field_schema=tool.input_schema,
            required_assets=required_assets,
            created_at=utc_now(),
        ).model_dump(mode="python")
        AssistantToolCallRepository.append_event(document["call_id"], event)

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
        arguments = dict(tool.input_schema.field_defaults or {})
        arguments.update(payload.arguments)
        missing_fields, _ = cls._validate_arguments(tool, arguments)
        cls._validate_asset_refs(tool, payload.input_asset_refs)
        uploaded_assets: list[dict[str, Any]] = []
        missing_assets = cls._missing_assets(tool, payload.input_asset_refs, uploaded_assets)
        next_phase = "awaiting_input" if missing_fields or missing_assets else "awaiting_confirmation"
        now = utc_now()
        document = {
            "call_id": f"atc_{uuid4().hex[:16]}",
            "provider_tool_call_id": payload.provider_tool_call_id,
            "chat_id": payload.chat_id,
            "message_id": payload.message_id,
            "tool_id": payload.tool_id,
            "algorithm_id": algorithm_id,
            "algorithm_version_id": tool.active_version_id,
            "algorithm_version": tool.version,
            "tool_name": tool.name,
            "phase": "requested",
            "arguments": _redact(arguments),
            "input_asset_refs": _redact(payload.input_asset_refs),
            "uploaded_assets": uploaded_assets,
            "missing_fields": missing_fields,
            "required_assets": [item.model_dump(mode="python") for item in missing_assets],
            "requires_confirmation": tool.requires_confirmation,
            "run_id": None,
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
        return cls._public_document(document)

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
        target_root = settings.runtime_root / "assistant-tool-calls" / call_id
        target_root.mkdir(parents=True, exist_ok=True)
        uploaded = list(document.get("uploaded_assets") or [])
        tool = cls._tool(document["algorithm_id"], current_user)
        input_specs = {spec.key: spec for spec in tool.input_assets}
        new_paths: list[Path] = []
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
            safe_key = re.sub(r"[^A-Za-z0-9_.-]", "_", asset_key)
            target = target_root / f"{safe_key}-{uuid4().hex[:8]}{Path(filename).suffix}"
            target.write_bytes(content)
            new_paths.append(target)
            uploaded = [item for item in uploaded if item.get("asset_key") != asset_key]
            uploaded.append(
                {
                    "asset_key": asset_key,
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": len(content),
                    "_path": str(target),
                }
            )
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
            for path in new_paths:
                path.unlink(missing_ok=True)
            raise
        cls._append_input_event(document, tool)
        return cls._public_document(document)

    @classmethod
    def confirm(
        cls,
        call_id: str,
        payload: AssistantToolCallConfirm,
        current_user: dict[str, str] | None,
    ) -> AssistantToolCall:
        cls.get(call_id, current_user)
        document = AssistantToolCallRepository.find_one({"call_id": call_id}) or {}
        phase = document.get("phase")
        if phase == "completed":
            return cls._public_document(document)
        if phase in {"canceled", "failed"}:
            raise HTTPException(status_code=409, detail="当前工具调用已结束，不能确认")
        if phase == "running":
            return cls._public_document(document)
        tool = cls._tool(document["algorithm_id"], current_user)
        arguments = dict(document.get("arguments") or {})
        if payload.arguments is not None:
            arguments.update(payload.arguments)
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
            "phase": "running",
            "arguments": _redact(arguments),
            "input_asset_refs": _redact(refs),
            "algorithm_version_id": tool.active_version_id,
            "algorithm_version": tool.version,
            "started_at": now,
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
        cls._append_phase_event(document)
        cls._audit(
            document,
            "assistant_tool_call_confirmed",
            {"status": "running", "algorithm_version_id": tool.active_version_id},
        )
        user_id, _role, is_admin = _actor_context(current_user)
        try:
            try:
                uploads = {
                    item["asset_key"]: {
                        "filename": item["filename"],
                        "content_type": item.get("content_type"),
                        "content": Path(item["_path"]).read_bytes(),
                    }
                    for item in document.get("uploaded_assets") or []
                    if item.get("_path")
                }
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

            output_summary = dict(getattr(run, "output_summary", {}) or {})
            artifact_refs = cls._public_artifact_refs(getattr(run, "artifact_refs", []) or [])
            update = {
                "run_id": getattr(run, "run_id", None),
                "result_summary": _redact(output_summary),
                "artifact_refs": artifact_refs,
                "finished_at": utc_now(),
            }
            cls._transition(document, "completed", **update)
            cls._audit(
                document,
                "assistant_tool_call_completed",
                {"status": "completed", "run_id": update["run_id"]},
            )
            return cls._public_document(document)
        finally:
            cls._cleanup_uploads(document)

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
        public_assets = [
            {key: value for key, value in item.items() if key != "_path"}
            for item in (document.get("uploaded_assets") or [])
        ]
        document["uploaded_assets"] = public_assets
        AssistantToolCallRepository.update_fields(
            document["call_id"],
            {"uploaded_assets": public_assets},
        )

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
    def stream_events(cls, call_id: str, current_user: dict[str, str] | None) -> Iterator[dict[str, Any]]:
        cls.get(call_id, current_user)
        yield from AssistantToolCallRepository.list_events(call_id)


assistant_tool_call_service = AssistantToolCallService()
