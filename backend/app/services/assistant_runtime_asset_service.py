"""受管 LUI 运行时附件服务。"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.config import settings
from app.core.time import utc_now
from app.infra.research_engine_repositories import AssistantRuntimeAssetRepository
from app.schemas.agent_tools import AssistantRuntimeAsset


SAFE_ASSET_KEY = re.compile(r"[^A-Za-z0-9_.-]")


class AssistantRuntimeAssetService:
    """把对话附件从临时文件迁移到受管 runtime asset。"""

    @staticmethod
    def _root(call_id: str) -> Path:
        """返回指定工具调用的受管附件根目录。"""
        return (settings.runtime_root / "assistant-runtime-assets" / call_id).resolve()

    def store(
        self,
        *,
        call_id: str,
        chat_id: str | None,
        created_by: str | None,
        asset_key: str,
        filename: str,
        content_type: str,
        content: bytes,
    ) -> dict[str, Any]:
        """保存上传内容并登记受管附件。"""
        now = utc_now()
        root = self._root(call_id)
        root.mkdir(parents=True, exist_ok=True)
        safe_key = SAFE_ASSET_KEY.sub("_", asset_key)
        suffix = Path(str(filename or asset_key)).suffix
        asset_id = f"ara_{uuid4().hex[:16]}"
        target = root / f"{safe_key}-{asset_id}{suffix}"
        target.write_bytes(content)
        document = {
            "asset_id": asset_id,
            "call_id": call_id,
            "chat_id": chat_id,
            "created_by": created_by,
            "asset_key": asset_key,
            "filename": filename,
            "content_type": content_type,
            "size_bytes": len(content),
            "path": str(target),
            "status": "active",
            "expires_at": now + timedelta(seconds=settings.assistant_runtime_asset_ttl_seconds),
            "created_at": now,
            "updated_at": now,
        }
        AssistantRuntimeAssetRepository.save("asset_id", document)
        return document

    def read(self, *, call_id: str, asset_id: str) -> bytes:
        """读取仍处于 active 状态的受管附件内容。"""
        document = self.get(asset_id)
        if document.call_id != call_id:
            raise HTTPException(status_code=403, detail="附件不属于当前工具调用")
        if document.status != "active":
            raise HTTPException(status_code=410, detail="附件已释放或过期")
        path = Path(document.path)
        if not path.is_file():
            raise HTTPException(status_code=410, detail="附件文件不存在")
        return path.read_bytes()

    def get(self, asset_id: str) -> AssistantRuntimeAsset:
        """读取受管附件元数据。"""
        document = AssistantRuntimeAssetRepository.find_one({"asset_id": asset_id})
        if not document:
            raise HTTPException(status_code=404, detail=f"附件 '{asset_id}' 不存在")
        return AssistantRuntimeAsset.model_validate(document)

    @staticmethod
    def public_metadata(document: dict[str, Any]) -> dict[str, Any]:
        """把内部文档转换为可返回给前端的附件摘要。"""
        return {
            "asset_key": document.get("asset_key"),
            "asset_id": document.get("asset_id"),
            "filename": document.get("filename"),
            "content_type": document.get("content_type"),
            "size_bytes": document.get("size_bytes"),
            "status": document.get("status"),
            "expires_at": document.get("expires_at"),
        }

    def release_call_assets(self, call_id: str) -> int:
        """释放工具调用下所有 active 附件，删除文件并更新状态。"""
        released = 0
        for document in AssistantRuntimeAssetRepository.list_for_call(call_id):
            if document.get("status") != "active":
                continue
            self._release_document(document)
            released += 1
        try:
            self._root(call_id).rmdir()
        except OSError:
            pass
        return released

    def cleanup_expired(self, *, limit: int = 200) -> int:
        """清理超过 TTL 的 active 附件。"""
        cleaned = 0
        for document in AssistantRuntimeAssetRepository.list_expired(limit=limit):
            self._release_document(document)
            cleaned += 1
        return cleaned

    @staticmethod
    def _release_document(document: dict[str, Any]) -> None:
        """删除单个受管附件文件并标记为 released。"""
        raw_path = document.get("path")
        if raw_path:
            try:
                Path(raw_path).unlink(missing_ok=True)
            except OSError:
                pass
        AssistantRuntimeAssetRepository.update_fields(
            document["asset_id"],
            {
                "status": "released",
                "updated_at": utc_now(),
            },
        )


assistant_runtime_asset_service = AssistantRuntimeAssetService()
