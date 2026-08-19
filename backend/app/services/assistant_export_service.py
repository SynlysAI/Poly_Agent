"""Assistant 会话导出服务。"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.time import utc_now
from app.infra.assistant_command_repositories import AssistantCommandRunRepository
from app.infra.computation_repositories import ComputationArtifactRepository
from app.infra.research_engine_repositories import (
    AlgorithmRunRepository,
    AssistantMessageRepository,
    AssistantRunRepository,
    AssistantRuntimeAssetRepository,
    AssistantToolCallRepository,
)
from app.services.assistant_chat_service import actor_id
from app.services.assistant_session_control import control_state


AGENT_VERSION = "0.1.0"
EXPORT_MEDIA_TYPES = {
    "json": "application/json",
    "markdown": "text/markdown; charset=utf-8",
    "zip": "application/zip",
}
EXPORT_EXTENSIONS = {"json": "json", "markdown": "md", "zip": "zip"}
EXPORT_LIMIT = 10_000


@dataclass(frozen=True)
class AssistantExportResult:
    """一次会话导出的交付结果。"""

    command_id: str
    format: str
    path: Path
    filename: str
    media_type: str
    size_bytes: int
    manifest_digest: str
    counts: dict[str, int]


class AssistantExportService:
    """生成可审计的 JSON、Markdown 与 ZIP 会话交付物。"""

    def export(
        self,
        chat: dict[str, Any],
        current_user: dict[str, str] | None,
        command_id: str,
        export_format: str,
    ) -> AssistantExportResult:
        """导出当前会话权威数据。

        Args:
            chat: 已通过 owner 校验的会话文档。
            current_user: 当前登录用户。
            command_id: 触发导出的命令执行 ID。
            export_format: json、markdown 或 zip。

        Returns:
            导出文件路径、下载名、digest 与核心计数。
        """
        normalized_format = self._normalize_format(export_format)
        chat_id = str(chat["chat_id"])
        owner_id = actor_id(current_user)
        self._export_event(
            chat,
            command_id,
            normalized_format,
            "started",
        )
        try:
            snapshot = self._collect_snapshot(chat, owner_id)
            metadata = self._metadata(
                command_id,
                normalized_format,
                owner_id,
                snapshot,
            )
            metadata["manifest_digest"] = self._manifest_digest(metadata)
            content = self._render(normalized_format, snapshot, metadata)
            output = self._write_export(command_id, normalized_format, content)
            digest = str(metadata["manifest_digest"])
            counts = dict(metadata["counts"])
            self._export_event(
                chat,
                command_id,
                normalized_format,
                "completed",
                manifest_digest=digest,
                counts=counts,
                file_size_bytes=output.stat().st_size,
            )
            return AssistantExportResult(
                command_id=command_id,
                format=normalized_format,
                path=output,
                filename=self._filename(chat_id, normalized_format),
                media_type=EXPORT_MEDIA_TYPES[normalized_format],
                size_bytes=output.stat().st_size,
                manifest_digest=digest,
                counts=counts,
            )
        except Exception as exc:
            self._export_event(
                chat,
                command_id,
                normalized_format,
                "failed",
                error={"error_type": exc.__class__.__name__, "message": str(exc)},
            )
            raise

    @staticmethod
    def _normalize_format(export_format: str) -> str:
        """校验并规范化导出格式。

        Args:
            export_format: 用户输入的格式。

        Returns:
            小写格式名。
        """
        normalized = str(export_format or "").strip().lower().lstrip("/")
        aliases = {"md": "markdown", "markdown": "markdown", "json": "json", "zip": "zip"}
        if normalized not in aliases:
            raise ValueError("导出格式必须为 json、markdown 或 zip")
        return aliases[normalized]

    @staticmethod
    def _filename(chat_id: str, export_format: str) -> str:
        """生成稳定且安全的下载文件名。

        Args:
            chat_id: 会话 ID。
            export_format: 导出格式。

        Returns:
            下载文件名。
        """
        safe_chat_id = re.sub(r"[^A-Za-z0-9_.-]+", "-", chat_id).strip("-") or "chat"
        return f"polyagent-chat-{safe_chat_id}.{EXPORT_EXTENSIONS[export_format]}"

    def _collect_snapshot(self, chat: dict[str, Any], owner_id: str) -> dict[str, Any]:
        """一次性读取会话权威数据快照。

        Args:
            chat: 会话文档。
            owner_id: 会话 owner。

        Returns:
            包含会话、消息、命令、run、Trace、工具与 artifact 的快照。
        """
        chat_id = str(chat["chat_id"])
        messages, _ = AssistantMessageRepository.list_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        commands, _ = AssistantCommandRunRepository.list_runs_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        runs, _ = AssistantRunRepository.list_for_chat(
            chat_id,
            owner_id,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        calls = AssistantToolCallRepository.list_for_chat(chat_id, created_by=owner_id)
        events = AssistantCommandRunRepository.events_after(
            chat_id,
            owner_id,
            after_seq=0,
            limit=EXPORT_LIMIT,
        )
        events.sort(
            key=lambda item: (
                int(item.get("seq") or 0),
                str(item.get("at") or ""),
                str(item.get("event_id") or ""),
            )
        )
        algorithm_runs = self._algorithm_runs(calls)
        runtime_assets, _ = AssistantRuntimeAssetRepository.list_all(
            {"chat_id": chat_id, "created_by": owner_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        artifacts = self._artifacts(calls, algorithm_runs)
        tool_results = self._tool_results(calls)
        associations = self._algorithm_associations(calls)
        return {
            "session": dict(chat),
            "control_state": control_state(chat).model_dump(mode="python"),
            "messages": messages,
            "commands": [self._public_command(item) for item in commands],
            "assistant_runs": runs,
            "execution_trace": events,
            "tool_calls": calls,
            "tool_results": tool_results,
            "algorithm_runs": algorithm_runs,
            "runtime_assets": [self._public_runtime_asset(item) for item in runtime_assets],
            "artifact_references": artifacts,
            "algorithm_run_associations": associations,
        }

    @staticmethod
    def _public_command(document: dict[str, Any]) -> dict[str, Any]:
        """移除命令文档中的服务端内部路径。

        Args:
            document: 命令执行文档。

        Returns:
            可导出的命令文档。
        """
        payload = dict(document)
        payload.pop("export_path", None)
        return payload

    @staticmethod
    def _public_runtime_asset(document: dict[str, Any]) -> dict[str, Any]:
        """移除运行时附件的本地绝对路径。

        Args:
            document: 受管附件文档。

        Returns:
            可导出的附件元数据。
        """
        payload = dict(document)
        payload.pop("path", None)
        return payload

    @staticmethod
    def _algorithm_runs(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """从工具调用推导并读取关联 AlgorithmRun。

        Args:
            calls: 会话内工具调用列表。

        Returns:
            按创建时间排序的 AlgorithmRun 文档。
        """
        run_ids = sorted(
            {
                str(call.get("run_id"))
                for call in calls
                if call.get("run_id")
            }
            | {
                str(call.get("continuation_run_id"))
                for call in calls
                if call.get("continuation_run_id")
            }
        )
        if not run_ids:
            return []
        items, _ = AlgorithmRunRepository.list_all(
            {"run_id": {"$in": run_ids}},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        return items

    @staticmethod
    def _artifacts(
        calls: list[dict[str, Any]],
        algorithm_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """收集会话关联的计算 artifact 元数据。

        Args:
            calls: 会话内工具调用列表。
            algorithm_runs: 已按会话推导出的 AlgorithmRun 列表。

        Returns:
            去重后的 artifact 引用列表。
        """
        references: dict[str, dict[str, Any]] = {}
        source_calls = {
            str(call.get("call_id") or ""): call for call in calls
        }
        for call in calls:
            call_id = str(call.get("call_id") or "")
            for ref in call.get("artifact_refs") or []:
                if not isinstance(ref, dict) or not ref.get("artifact_id"):
                    continue
                artifact_id = str(ref["artifact_id"])
                references.setdefault(
                    artifact_id,
                    {**ref, "source_kind": "computation_artifact", "call_id": call_id},
                )
        for run in algorithm_runs:
            for ref in run.get("artifact_refs") or []:
                if not isinstance(ref, dict) or not ref.get("artifact_id"):
                    continue
                artifact_id = str(ref["artifact_id"])
                references.setdefault(
                    artifact_id,
                    {**ref, "source_kind": "algorithm_run_artifact", "call_id": ""},
                )
        artifact_ids = sorted(references)
        if not artifact_ids:
            return []
        documents, _ = ComputationArtifactRepository.list_all(
            {"artifact_id": {"$in": artifact_ids}},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=EXPORT_LIMIT,
        )
        by_id = {str(item.get("artifact_id")): item for item in documents}
        result = []
        for artifact_id in artifact_ids:
            document = by_id.get(artifact_id)
            if not document:
                result.append(
                    {
                        **references[artifact_id],
                        "status": "missing",
                        "error": "artifact metadata not found",
                    }
                )
                continue
            owner_id = str(document.get("owner_id") or document.get("run_id") or "")
            related_call = source_calls.get(str(references[artifact_id].get("call_id") or ""))
            if document.get("owner_type") == "algorithm_run" and not any(
                str(run.get("run_id")) == owner_id for run in algorithm_runs
            ):
                result.append(
                    {
                        **references[artifact_id],
                        "status": "forbidden",
                        "error": "artifact owner is outside this chat snapshot",
                    }
                )
                continue
            if document.get("owner_type") != "algorithm_run" and not related_call:
                result.append(
                    {
                        **references[artifact_id],
                        "status": "forbidden",
                        "error": "artifact is not referenced by a chat tool call",
                    }
                )
                continue
            result.append(
                {
                    **references[artifact_id],
                    "name": document.get("name") or references[artifact_id].get("name"),
                    "mime_type": document.get("mime_type"),
                    "size_bytes": document.get("size_bytes"),
                    "checksum_sha256": document.get("checksum_sha256"),
                    "owner_type": document.get("owner_type"),
                    "owner_id": owner_id,
                    "run_id": document.get("run_id"),
                    "created_at": document.get("created_at"),
                    "status": "available",
                }
            )
        return result

    @staticmethod
    def _tool_results(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """提取工具调用的结果摘要与 artifact 引用。

        Args:
            calls: 会话内工具调用列表。

        Returns:
            工具结果语义列表。
        """
        return [
            {
                "call_id": call.get("call_id"),
                "command_id": call.get("command_id"),
                "run_id": call.get("run_id"),
                "continuation_run_id": call.get("continuation_run_id"),
                "phase": call.get("phase"),
                "result_summary": call.get("result_summary") or {},
                "artifact_refs": call.get("artifact_refs") or [],
                "error": call.get("error"),
                "finished_at": call.get("finished_at"),
            }
            for call in calls
        ]

    @staticmethod
    def _algorithm_associations(calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """记录工具调用与 AlgorithmRun / Trace 的关联。

        Args:
            calls: 会话内工具调用列表。

        Returns:
            关联关系列表。
        """
        return [
            {
                "call_id": call.get("call_id"),
                "command_id": call.get("command_id"),
                "trace_id": call.get("trace_id"),
                "algorithm_run_id": call.get("run_id"),
                "continuation_run_id": call.get("continuation_run_id"),
                "assistant_run_id": call.get("assistant_run_id"),
            }
            for call in calls
        ]

    def _metadata(
        self,
        command_id: str,
        export_format: str,
        owner_id: str,
        snapshot: dict[str, Any],
    ) -> dict[str, Any]:
        """构建导出 metadata 与 artifact manifest。

        Args:
            command_id: 导出命令 ID。
            export_format: 导出格式。
            owner_id: 会话 owner。
            snapshot: 权威数据快照。

        Returns:
            可写入 metadata.json 的对象。
        """
        artifact_manifest, _ = self._artifact_manifest(snapshot)
        counts = {
            "messages": len(snapshot["messages"]),
            "commands": len(snapshot["commands"]),
            "assistant_runs": len(snapshot["assistant_runs"]),
            "execution_trace": len(snapshot["execution_trace"]),
            "tool_calls": len(snapshot["tool_calls"]),
            "tool_results": len(snapshot["tool_results"]),
            "algorithm_runs": len(snapshot["algorithm_runs"]),
            "artifacts": len(artifact_manifest),
            "runtime_assets": len(snapshot["runtime_assets"]),
        }
        return {
            "export_id": command_id,
            "format": export_format,
            "generated_at": utc_now(),
            "generated_by": owner_id,
            "agent_version": AGENT_VERSION,
            "counts": counts,
            "artifact_manifest": artifact_manifest,
            "algorithm_run_associations": snapshot["algorithm_run_associations"],
            "schema_version": "assistant-session-export-v1",
        }

    def _artifact_manifest(self, snapshot: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Path]]:
        """生成 artifact 打包 manifest，并容忍单项读取失败。

        Args:
            snapshot: 权威数据快照。

        Returns:
            每个引用的打包状态、目标路径或错误说明。
        """
        manifest: list[dict[str, Any]] = []
        source_paths: dict[str, Path] = {}
        used_names: set[str] = set()
        for reference in snapshot["artifact_references"]:
            entry = {
                "artifact_id": reference.get("artifact_id"),
                "source_kind": "computation_artifact",
                "filename": reference.get("name") or "artifact.dat",
                "status": reference.get("status") or "available",
                "error": reference.get("error"),
            }
            if entry["status"] != "available":
                manifest.append(entry)
                continue
            path = self._computation_artifact_path(str(reference.get("artifact_id") or ""))
            if path is None:
                entry["status"] = "error"
                entry["error"] = "artifact file missing or outside managed outputs"
                manifest.append(entry)
                continue
            entry["archive_path"] = f"artifacts/{self._unique_zip_name(str(entry['filename']), used_names)}"
            entry["size_bytes"] = path.stat().st_size
            source_paths[str(entry["archive_path"])] = path
            manifest.append(entry)

        asset_statuses = {
            str(item.get("asset_id")): item for item in snapshot["runtime_assets"]
        }
        calls = snapshot["tool_calls"]
        for call in calls:
            for uploaded in call.get("uploaded_assets") or []:
                if not isinstance(uploaded, dict) or not uploaded.get("asset_id"):
                    continue
                asset_id = str(uploaded["asset_id"])
                asset_document = AssistantRuntimeAssetRepository.find_one(
                    {"asset_id": asset_id}
                )
                asset = (
                    self._public_runtime_asset(asset_document)
                    if asset_document
                    else asset_statuses.get(asset_id)
                )
                if not asset:
                    continue
                entry = {
                    "artifact_id": asset_id,
                    "source_kind": "assistant_runtime_asset",
                    "filename": asset.get("filename") or "runtime-asset.dat",
                    "status": "available",
                    "error": None,
                }
                if asset.get("status") != "active":
                    entry.update({"status": "expired", "error": "runtime asset released or expired"})
                    manifest.append(entry)
                    continue
                path = self._runtime_asset_path(asset_document or {})
                if path is None:
                    entry.update({"status": "error", "error": "runtime asset file missing"})
                    manifest.append(entry)
                    continue
                entry["archive_path"] = f"artifacts/{self._unique_zip_name(str(entry['filename']), used_names)}"
                entry["size_bytes"] = path.stat().st_size
                source_paths[str(entry["archive_path"])] = path
                manifest.append(entry)
        return manifest, source_paths

    @staticmethod
    def _computation_artifact_path(artifact_id: str) -> Path | None:
        """安全解析计算 artifact 文件路径。

        Args:
            artifact_id: artifact ID。

        Returns:
            位于受管 outputs 目录内的文件路径；无效时返回 None。
        """
        document = ComputationArtifactRepository.find_one({"artifact_id": artifact_id})
        if not document:
            return None
        raw_path = Path(str(document.get("storage_uri") or ""))
        path = raw_path.resolve() if raw_path.is_absolute() else (settings.project_root / raw_path).resolve()
        output_root = settings.outputs_root.resolve()
        try:
            path.relative_to(output_root)
        except ValueError:
            return None
        return path if path.is_file() else None

    @staticmethod
    def _runtime_asset_path(asset: dict[str, Any]) -> Path | None:
        """安全解析 LUI 受管附件路径。

        Args:
            asset: 附件元数据。

        Returns:
           位于受管 runtime 目录内的文件路径；无效时返回 None。
        """
        raw_path = Path(str(asset.get("path") or ""))
        if not raw_path.is_absolute():
            return None
        path = raw_path.resolve()
        root = (settings.runtime_root / "assistant-runtime-assets").resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        return path if path.is_file() else None

    @staticmethod
    def _unique_zip_name(filename: str, used_names: set[str]) -> str:
        """生成 ZIP 内安全且不重名的文件名。

        Args:
            filename: 原始文件名。
            used_names: 已占用名称集合，函数会原地更新。

        Returns:
            ZIP 内相对 artifacts/ 的文件名。
        """
        candidate = re.sub(r"[\\/\r\n\t]+", "_", Path(filename).name).strip() or "artifact.dat"
        stem = Path(candidate).stem or "artifact"
        suffix = Path(candidate).suffix
        unique = candidate
        serial = 2
        while unique in used_names:
            unique = f"{stem}-{serial}{suffix}"
            serial += 1
        used_names.add(unique)
        return unique

    @staticmethod
    def _manifest_digest(metadata: dict[str, Any]) -> str:
        """计算 metadata manifest 摘要。

        Args:
            metadata: 导出 metadata。

        Returns:
            sha256 摘要字符串。
        """
        canonical = json.dumps(
            metadata,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        return f"sha256:{hashlib.sha256(canonical.encode('utf-8')).hexdigest()}"

    def _render(
        self,
        export_format: str,
        snapshot: dict[str, Any],
        metadata: dict[str, Any],
    ) -> bytes | Path:
        """渲染导出内容。

        Args:
            export_format: 导出格式。
            snapshot: 权威数据快照。
            metadata: 导出 metadata。

        Returns:
            JSON/Markdown 字节内容；ZIP 返回已写入的临时文件路径。
        """
        if export_format == "json":
            return self._json_bytes({**snapshot, "metadata": metadata})
        if export_format == "markdown":
            return self._markdown(snapshot, metadata).encode("utf-8")
        return self._write_zip(snapshot, metadata)

    @staticmethod
    def _json_bytes(value: Any) -> bytes:
        """序列化 JSON 内容。

        Args:
            value: 可 JSON 化对象。

        Returns:
            UTF-8 JSON 字节。
        """
        return json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
        ).encode("utf-8")

    def _write_zip(self, snapshot: dict[str, Any], metadata: dict[str, Any]) -> Path:
        """生成固定结构的 ZIP 导出。

        Args:
            snapshot: 权威数据快照。
            metadata: 导出 metadata。

        Returns:
            ZIP 文件路径。
        """
        target = settings.runtime_root / "assistant-exports" / f"{metadata['export_id']}.zip.tmp"
        target.parent.mkdir(parents=True, exist_ok=True)
        _, source_paths = self._artifact_manifest(snapshot)
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "session.json",
                self._json_bytes(
                    {
                        "session": snapshot["session"],
                        "control_state": snapshot["control_state"],
                    }
                ),
            )
            archive.writestr("messages.json", self._json_bytes(snapshot["messages"]))
            with archive.open("commands.jsonl", "w") as stream:
                for command in snapshot["commands"]:
                    stream.write(
                        (json.dumps(command, ensure_ascii=False, sort_keys=True, default=str) + "\n").encode("utf-8")
                    )
            with archive.open("execution_trace.jsonl", "w") as stream:
                for event in snapshot["execution_trace"]:
                    stream.write(
                        (json.dumps(event, ensure_ascii=False, sort_keys=True, default=str) + "\n").encode("utf-8")
                    )
            archive.writestr(
                "tool_calls.json",
                self._json_bytes(
                    {
                        "tool_calls": snapshot["tool_calls"],
                        "tool_results": snapshot["tool_results"],
                        "algorithm_runs": snapshot["algorithm_runs"],
                        "algorithm_run_associations": snapshot["algorithm_run_associations"],
                    }
                ),
            )
            self._write_artifacts(archive, metadata["artifact_manifest"], source_paths)
            archive.writestr("metadata.json", self._json_bytes(metadata))
        final_path = target.with_suffix("")
        target.replace(final_path)
        return final_path

    @staticmethod
    def _write_artifacts(
        archive: zipfile.ZipFile,
        manifest: list[dict[str, Any]],
        source_paths: dict[str, Path],
    ) -> None:
        """把可用 artifact 写入 ZIP。

        Args:
            archive: ZIP 文件对象。
            manifest: artifact 打包 manifest。
        """
        for entry in manifest:
            archive_path = entry.get("archive_path")
            if entry.get("status") != "available" or not archive_path:
                continue
            source = source_paths.get(str(archive_path))
            if source is None:
                continue
            if not source.is_file():
                continue
            archive.write(source, arcname=archive_path)

    def _write_export(
        self,
        command_id: str,
        export_format: str,
        content: bytes | Path,
    ) -> Path:
        """原子写入导出文件。

        Args:
            command_id: 命令 ID。
            export_format: 导出格式。
            content: 字节内容或 ZIP 文件路径。

        Returns:
            最终导出文件路径。
        """
        extension = EXPORT_EXTENSIONS[export_format]
        root = settings.runtime_root / "assistant-exports"
        root.mkdir(parents=True, exist_ok=True)
        final_path = root / f"{command_id}.{extension}"
        temp_path = root / f"{command_id}.{extension}.tmp"
        if isinstance(content, Path):
            content.replace(temp_path)
        else:
            temp_path.write_bytes(content)
        temp_path.replace(final_path)
        return final_path

    @staticmethod
    def _export_event(
        chat: dict[str, Any],
        command_id: str,
        export_format: str,
        status: str,
        **fields: Any,
    ) -> dict[str, Any] | None:
        """写入导出开始 / 结束统一事件。

        Args:
            chat: 会话文档。
            command_id: 命令 ID。
            export_format: 导出格式。
            status: started、completed 或 failed。
            fields: digest、计数或错误等附加字段。

        Returns:
            插入的 assistant_events 文档。
        """
        return AssistantCommandRunRepository.append_chat_event(
            chat,
            {
                "type": "session.exported",
                "command_id": command_id,
                "format": export_format,
                "status": status,
                "chat_id": str(chat["chat_id"]),
                **fields,
            },
        )

    def _markdown(
        self,
        snapshot: dict[str, Any],
        metadata: dict[str, Any],
    ) -> str:
        """生成人类可读 Markdown 报告。

        Args:
            snapshot: 权威数据快照。
            metadata: 导出 metadata。

        Returns:
            Markdown 文本。
        """
        session = snapshot["session"]
        state = snapshot["control_state"]
        counts = metadata["counts"]
        lines = [
            "# PolyAgent 会话导出",
            "",
            f"- 会话：{session.get('title') or session.get('chat_id')}",
            f"- Chat ID：`{session.get('chat_id')}`",
            f"- 导出格式：markdown",
            f"- 生成时间：{metadata['generated_at']}",
            f"- Agent 版本：{metadata['agent_version']}",
            f"- Manifest digest：`{metadata.get('manifest_digest', '待生成')}`",
            "",
            "## 控制状态",
            "",
            f"- Plan Mode：{'开启' if state.get('plan_mode') else '关闭'}",
            f"- Permission Mode：`{state.get('permission_mode')}`",
            f"- 模型：`{state.get('model')}`",
            f"- Goal：{(state.get('goal') or {}).get('objective', '无')}",
            f"- Todo 数量：{len(state.get('todos') or [])}",
            "",
            "## 数量统计",
            "",
            "| 数据 | 数量 |",
            "|---|---:|",
        ]
        lines.extend(f"| {label} | {counts[key]} |" for label, key in [
            ("消息", "messages"),
            ("命令", "commands"),
            ("Assistant Run", "assistant_runs"),
            ("Trace 事件", "execution_trace"),
            ("工具调用", "tool_calls"),
            ("工具结果", "tool_results"),
            ("Algorithm Run", "algorithm_runs"),
            ("Artifact", "artifacts"),
        ])
        lines.extend(["", "## 消息", ""])
        for message in snapshot["messages"]:
            lines.append(f"### {message.get('role')} · {message.get('created_at')}")
            lines.append("")
            lines.extend(f"> {line}" for line in str(message.get("content") or "").splitlines() or [""])
            lines.append("")
        lines.extend(["## 命令", "", "| 命令 | 状态 | 时间 | Command ID |", "|---|---|---|---|"])
        lines.extend(
            f"| `/{item.get('name')}` | {item.get('status')} | {item.get('created_at')} | `{item.get('command_id')}` |"
            for item in snapshot["commands"]
        )
        lines.extend(["", "## Assistant Run", "", "| Run | Trace | 状态 | 模型 |", "|---|---|---|---|"])
        lines.extend(
            f"| `{item.get('run_id')}` | `{item.get('trace_id') or ''}` | {item.get('status')} | "
            f"`{item.get('provider_id') or ''}::{item.get('model_id') or ''}` |"
            for item in snapshot["assistant_runs"]
        )
        lines.extend(["", "## 工具调用与结果", "", "| Call | Algorithm Run | 阶段 | Artifact |", "|---|---|---|---:|"])
        result_by_call = {str(item.get("call_id")): item for item in snapshot["tool_results"]}
        lines.extend(
            f"| `{call.get('call_id')}` | `{call.get('run_id') or ''}` | {call.get('phase')} | "
            f"{len((result_by_call.get(str(call.get('call_id'))) or {}).get('artifact_refs') or [])} |"
            for call in snapshot["tool_calls"]
        )
        lines.extend(["", "## Execution Trace", "", "| Seq | 事件 | 时间 | Trace |", "|---:|---|---|---|"])
        lines.extend(
            f"| {event.get('seq')} | `{event.get('type')}` | {event.get('at')} | `{event.get('trace_id') or ''}` |"
            for event in snapshot["execution_trace"]
        )
        lines.extend(["", "## Artifact Manifest", "", "| Artifact | 状态 | ZIP 路径 / 错误 |", "|---|---|---|"])
        lines.extend(
            f"| `{item.get('artifact_id')}` | {item.get('status')} | {item.get('archive_path') or item.get('error') or ''} |"
            for item in metadata["artifact_manifest"]
        )
        lines.append("")
        return "\n".join(lines)
