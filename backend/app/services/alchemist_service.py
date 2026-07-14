"""ALchemist 实验设计服务 — Session 生命周期与持久化管理。"""

from __future__ import annotations

import json
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.alchemist_core.session import OptimizationSession
from app.core.config import settings
from app.core.logging import get_logger
from app.core.time import utc_now
from app.infra.alchemist_repositories import AlchemistSessionRepository

logger = get_logger("poly_agent.alchemist_service")

MODEL_STATE_KEY = "model_config"


def _runtime_dir() -> Path:
    """获取 alchemist 运行时目录。"""
    d = settings.alchemist_runtime_root
    d.mkdir(parents=True, exist_ok=True)
    return d


def _session_runtime_dir(session_id: str) -> Path:
    """获取单个 session 的运行时目录。"""
    d = _runtime_dir() / session_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _model_state_path(session_id: str) -> Path:
    """获取模型状态文件路径。"""
    return _session_runtime_dir(session_id) / "model.json"


class AlchemistService:
    """ALchemist 实验设计 Session 服务。"""

    @staticmethod
    def create_session(
        name: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        *,
        created_by: str,
    ) -> dict[str, Any]:
        """创建新的优化 Session。

        Args:
            name: Session 名称。
            description: Session 描述。
            tags: 标签列表。
            created_by: 创建者 user_id。

        Returns:
            包含 session_id 和 created_at 的字典。
        """
        session_id = str(uuid.uuid4())
        session = OptimizationSession()
        session.metadata.session_id = session_id
        if name:
            session.metadata.name = name
        if description:
            session.metadata.description = description
        if tags:
            session.metadata.tags = tags

        now = utc_now()
        doc = {
            "session_id": session_id,
            "name": name,
            "description": description,
            "tags": tags or [],
            "created_by": created_by,
            "status": "active",
            "variables": [],
            "experiments": [],
            "staged_experiments": [],
            "audit_log": [],
            "model_trained": False,
            "model_backend": None,
            "model_kernel": None,
            "variable_count": 0,
            "experiment_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        AlchemistSessionRepository.save(doc)

        # 保存完整 session 状态（无模型）
        AlchemistService._persist_session_state(session_id, session)

        logger.info(f"创建 ALchemist Session: {session_id} by {created_by}")
        return {"session_id": session_id, "created_at": now}

    @staticmethod
    def get_session(session_id: str, *, actor_user_id: str | None = None, is_admin: bool = False) -> OptimizationSession:
        """加载 Session 并返回 OptimizationSession 实例。

        Args:
            session_id: Session 标识符。
            actor_user_id: 请求用户 ID（用于权限校验）。
            is_admin: 是否管理员。

        Returns:
            OptimizationSession 实例。

        Raises:
            HTTPException: Session 不存在或无权访问。
        """
        doc = AlchemistSessionRepository.find_by_id(session_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} 不存在")

        if not is_admin and actor_user_id and doc.get("created_by") != actor_user_id:
            raise HTTPException(status_code=403, detail="无权访问此 Session")

        return AlchemistService._reconstruct_session(session_id, doc)

    @staticmethod
    def get_session_detail(session_id: str, *, actor_user_id: str | None = None, is_admin: bool = False) -> dict[str, Any]:
        """获取 Session 详情（不含完整模型状态）。

        Args:
            session_id: Session 标识符。
            actor_user_id: 请求用户 ID。
            is_admin: 是否管理员。

        Returns:
            Session 详情文档。
        """
        doc = AlchemistSessionRepository.find_by_id(session_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} 不存在")

        if not is_admin and actor_user_id and doc.get("created_by") != actor_user_id:
            raise HTTPException(status_code=403, detail="无权访问此 Session")

        return doc

    @staticmethod
    def list_sessions(
        *,
        actor_user_id: str | None = None,
        is_admin: bool = False,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 Session 列表。

        Args:
            actor_user_id: 请求用户 ID。
            is_admin: 是否管理员。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total)。
        """
        created_by = None if is_admin else actor_user_id
        items, total = AlchemistSessionRepository.list_by_user(
            created_by=created_by, page=page, page_size=page_size
        )
        return items, total

    @staticmethod
    def delete_session(session_id: str, *, actor_user_id: str | None = None, is_admin: bool = False) -> bool:
        """删除 Session 及其关联数据。

        Args:
            session_id: Session 标识符。
            actor_user_id: 请求用户 ID。
            is_admin: 是否管理员。

        Returns:
            是否成功删除。
        """
        doc = AlchemistSessionRepository.find_by_id(session_id)
        if doc is None:
            raise HTTPException(status_code=404, detail=f"Session {session_id} 不存在")

        if not is_admin and actor_user_id and doc.get("created_by") != actor_user_id:
            raise HTTPException(status_code=403, detail="无权删除此 Session")

        # 删除模型文件
        model_path = _model_state_path(session_id)
        if model_path.exists():
            model_path.unlink()

        # 删除运行时目录
        runtime_dir = _session_runtime_dir(session_id)
        try:
            import shutil
            shutil.rmtree(runtime_dir, ignore_errors=True)
        except Exception:
            pass

        return AlchemistSessionRepository.delete(session_id)

    @staticmethod
    def save_session(session_id: str, session: OptimizationSession) -> None:
        """保存 Session：MongoDB 存储数据 + .runtime 存储模型。

        Args:
            session_id: Session 标识符。
            session: OptimizationSession 实例。
        """
        AlchemistService._persist_session_state(session_id, session)
        AlchemistService._sync_metadata(session_id, session)

    # ============================================================
    # 内部方法
    # ============================================================

    @staticmethod
    def _persist_session_state(session_id: str, session: OptimizationSession) -> None:
        """持久化 session 完整状态（MongoDB 数据 + .runtime 模型）。

        Args:
            session_id: Session 标识符。
            session: OptimizationSession 实例。
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            session.save_session(tmp.name)
            temp_path = tmp.name

        try:
            with open(temp_path, "r") as f:
                full_state = json.load(f)

            # 拆出模型状态 → .runtime
            model_state = full_state.pop(MODEL_STATE_KEY, None)
            if model_state is not None:
                model_path = _model_state_path(session_id)
                with open(model_path, "w") as f:
                    json.dump(model_state, f, indent=2)

            # 提取数据字段 → MongoDB
            experiments_data = full_state.get("experiments", {})
            experiment_rows = experiments_data.get("data", []) if isinstance(experiments_data, dict) else []

            search_space = full_state.get("search_space", {})
            variables = search_space.get("variables", []) if isinstance(search_space, dict) else []

            # 暂存实验
            staged = full_state.get("staged_experiments", [])

            # 审计日志
            audit = full_state.get("audit_log", [])
            audit_entries = audit.get("entries", []) if isinstance(audit, dict) else (audit if isinstance(audit, list) else [])

            fields = {
                "variables": variables,
                "experiments": experiment_rows,
                "staged_experiments": staged,
                "audit_log": audit_entries,
                "variable_count": len(variables),
                "experiment_count": len(experiment_rows),
                "model_trained": model_state is not None,
                "model_backend": model_state.get("backend") if model_state else None,
                "model_kernel": model_state.get("kernel") if model_state else None,
            }
            AlchemistSessionRepository.update_fields(session_id, fields)

        finally:
            Path(temp_path).unlink(missing_ok=True)

    @staticmethod
    def _sync_metadata(session_id: str, session: OptimizationSession) -> None:
        """同步 session 元数据到 MongoDB。

        Args:
            session_id: Session 标识符。
            session: OptimizationSession 实例。
        """
        meta = session.metadata
        AlchemistSessionRepository.update_fields(
            session_id,
            {
                "name": meta.name,
                "description": meta.description,
                "tags": meta.tags,
            },
        )

    @staticmethod
    def _reconstruct_session(session_id: str, doc: dict[str, Any]) -> OptimizationSession:
        """从 MongoDB + .runtime 重建 OptimizationSession。

        Args:
            session_id: Session 标识符。
            doc: MongoDB 文档。

        Returns:
            重建的 OptimizationSession 实例。
        """
        # 构建与 save_session() 兼容的 JSON 结构
        state = {
            "metadata": {
                "session_id": session_id,
                "name": doc.get("name", ""),
                "created_at": doc.get("created_at", utc_now()).isoformat() if isinstance(doc.get("created_at"), datetime) else str(doc.get("created_at", "")),
                "last_modified": doc.get("updated_at", utc_now()).isoformat() if isinstance(doc.get("updated_at"), datetime) else str(doc.get("updated_at", "")),
                "description": doc.get("description", ""),
                "tags": doc.get("tags", []),
            },
            "search_space": {
                "variables": doc.get("variables", []),
            },
            "experiments": {
                "data": doc.get("experiments", []),
            },
            "staged_experiments": doc.get("staged_experiments", []),
            "audit_log": {
                "entries": doc.get("audit_log", []),
            },
        }

        # 加载模型状态
        model_path = _model_state_path(session_id)
        if model_path.exists():
            with open(model_path, "r") as f:
                state[MODEL_STATE_KEY] = json.load(f)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as tmp:
            json.dump(state, tmp, indent=2)
            temp_path = tmp.name

        try:
            session = OptimizationSession.load_session(temp_path, retrain_on_load=False)
            return session
        finally:
            Path(temp_path).unlink(missing_ok=True)


# 服务单例
service = AlchemistService()
