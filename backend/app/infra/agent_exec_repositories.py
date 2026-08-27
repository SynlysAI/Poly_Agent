"""agent_exec 双模存储与审计写入。"""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from pymongo.errors import PyMongoError

from app.core.time import utc_now
from app.infra.computation_repositories import (
    AuditEventRepository,
    BaseRepository,
    _matches,
    clone_document,
)
from app.infra.sqlite_store import demo_store
from app.infra.mongo import (
    get_agent_exec_artifacts_collection,
    get_agent_exec_provider_policies_collection,
    get_agent_exec_runs_collection,
)
from app.infra.research_engine_repositories import AssistantEventRepository
from app.schemas.agent_exec import (
    AgentExecArtifactData,
    AgentExecProviderPolicy,
    AgentExecRunData,
)


SENSITIVE_KEY_PATTERN = re.compile(
    r"(?i)(api[_-]?key|access[_-]?key|token|password|secret|authorization|prompt)"
)


class AgentExecRunRepository(BaseRepository):
    """agent_exec run 权威状态仓储。"""

    collection_name = "agent_exec_runs"

    @classmethod
    def _collection(cls):
        return get_agent_exec_runs_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建 run 查询与回放索引。"""
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index("run_id", unique=True)
            collection.create_index("provider_id")
            collection.create_index("status")
            collection.create_index("chat_id")
            collection.create_index("created_by")
            collection.create_index([("created_at", -1)])
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def save_run(cls, run: AgentExecRunData) -> dict[str, Any]:
        """保存 run 权威状态。

        Args:
            run: run 状态对象。

        Returns:
            持久化后的文档。
        """
        document = run.model_dump(mode="json")
        cls.save("run_id", document)
        return document

    @classmethod
    def get_run(cls, run_id: str) -> AgentExecRunData | None:
        """按 run_id 读取 run。

        Args:
            run_id: 服务端生成的 run ID。

        Returns:
            run 对象；不存在时返回 None。
        """
        document = cls.find_one({"run_id": run_id})
        if document is None:
            return None
        return AgentExecRunData.model_validate(document)

    @classmethod
    def list_runs(
        cls,
        *,
        provider_id: str | None = None,
        status: str | None = None,
        chat_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[AgentExecRunData], int]:
        """分页查询 run。

        Args:
            provider_id: provider 过滤。
            status: 状态过滤。
            chat_id: 会话过滤。
            created_by: 创建者过滤，用于 owner 校验。
            page: 页码。
            page_size: 每页数量。

        Returns:
            (run 列表, 总数) 元组。
        """
        filters: dict[str, Any] = {}
        if provider_id:
            filters["provider_id"] = provider_id
        if status:
            filters["status"] = status
        if chat_id:
            filters["chat_id"] = chat_id
        if created_by:
            filters["created_by"] = created_by
        documents, total = cls.list_all(
            filters, sort_field="created_at", reverse=True, page=page, page_size=page_size
        )
        return [AgentExecRunData.model_validate(item) for item in documents], total


class AgentExecArtifactRepository(BaseRepository):
    """agent_exec artifact 清单仓储。"""

    collection_name = "agent_exec_artifacts"

    @classmethod
    def _collection(cls):
        return get_agent_exec_artifacts_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建 artifact 查询索引。"""
        if not cls._can_use_mongo():
            return
        try:
            collection = cls._collection()
            collection.create_index([("run_id", 1), ("path", 1)], unique=True)
            collection.create_index("run_id")
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def delete_many(cls, filters: dict[str, Any]) -> int:
        """按条件删除文档。

        Args:
            filters: 查询过滤条件。

        Returns:
            删除的文档数量。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_many(filters)
                return int(result.deleted_count)
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            """删除匹配文档并返回数量。"""
            rows = data[cls.collection_name]
            remaining = [item for item in rows if not _matches(item, filters)]
            removed = len(rows) - len(remaining)
            data[cls.collection_name] = remaining
            return removed

        return int(demo_store.mutate_collection(cls.collection_name, mutate))

    @classmethod
    def save_artifacts(cls, run_id: str, artifacts: list[AgentExecArtifactData]) -> None:
        """以 run 为单位替换 artifact 清单。

        Args:
            run_id: run ID。
            artifacts: 通过安全扫描的输出清单。
        """
        cls.delete_many({"run_id": run_id})
        for artifact in artifacts:
            cls.save(
                "artifact_id",
                {
                    "artifact_id": f"aea_{uuid4().hex[:20]}",
                    "run_id": run_id,
                    **artifact.model_dump(mode="json"),
                },
            )

    @classmethod
    def list_artifacts(cls, run_id: str) -> list[dict[str, Any]]:
        """读取 run 的 artifact 清单。

        Args:
            run_id: run ID。

        Returns:
            artifact 文档列表。
        """
        documents, _ = cls.list_all(
            {"run_id": run_id},
            sort_field="path",
            reverse=False,
            page=1,
            page_size=1000,
        )
        return documents


class AgentExecProviderPolicyRepository(BaseRepository):
    """连接器策略仓储，无记录即安全默认。"""

    collection_name = "agent_exec_provider_policies"

    @classmethod
    def _collection(cls):
        return get_agent_exec_provider_policies_collection()

    @classmethod
    def ensure_indexes(cls) -> None:
        """创建策略唯一索引。"""
        if not cls._can_use_mongo():
            return
        try:
            cls._collection().create_index("provider_id", unique=True)
        except PyMongoError as exc:
            cls._handle_mongo_error(exc)

    @classmethod
    def get_policy(cls, provider_id: str) -> AgentExecProviderPolicy | None:
        """读取 provider 策略。

        Args:
            provider_id: provider 唯一标识。

        Returns:
            策略对象；无记录时返回 None（调用方使用安全默认值）。
        """
        document = cls.find_one({"provider_id": provider_id})
        if document is None:
            return None
        return AgentExecProviderPolicy.model_validate(document)

    @classmethod
    def save_policy(cls, policy: AgentExecProviderPolicy) -> None:
        """保存 provider 策略。

        Args:
            policy: 策略对象。
        """
        cls.save("provider_id", policy.model_dump(mode="json"))


class AgentExecAuditWriter:
    """把 agent_exec 生命周期事件写入统一 Audit 与 assistant 事件流。"""

    @staticmethod
    def sanitize_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        """移除敏感键并只保留可审计的摘要字段。

        Args:
            metadata: 原始事件元数据。

        Returns:
            脱敏后的元数据副本。
        """
        cleaned: dict[str, Any] = {}
        for key, value in metadata.items():
            if SENSITIVE_KEY_PATTERN.search(str(key)):
                continue
            cleaned[str(key)] = clone_document(value)
        return cleaned

    @classmethod
    def write_event(cls, event: dict[str, Any]) -> None:
        """写入 agent_exec 生命周期审计与 assistant 事件。

        Args:
            event: 执行服务产出的脱敏事件。
        """
        metadata = cls.sanitize_metadata(dict(event.get("metadata") or {}))
        run_id = str(event.get("run_id") or "")
        chat_id = str(event.get("chat_id") or "")
        actor = str(event.get("actor_user_id") or "")
        event_type = str(event.get("event_type") or "")
        AuditEventRepository.append(
            {
                "event_id": f"audit_{uuid4().hex[:20]}",
                "event_type": event_type,
                "actor_user_id": actor,
                "actor_role": "user",
                "request_id": None,
                "entity_type": "agent_exec_run",
                "entity_id": run_id,
                "related_ids": {"provider_id": event.get("provider_id")},
                "before": {},
                "after": {},
                "metadata": {
                    "provider_id": event.get("provider_id"),
                    "task_type": event.get("task_type"),
                    **metadata,
                },
                "created_at": event.get("created_at") or utc_now(),
            }
        )
        if not chat_id:
            return
        AssistantEventRepository.append(
            {
                "run_id": "",
                "chat_id": chat_id,
                "created_by": actor,
            },
            {
                "type": event_type,
                "call_id": str(event.get("assistant_tool_call_id") or ""),
                "run_id": run_id,
                "provider_id": event.get("provider_id"),
                "task_type": event.get("task_type"),
                "source": "agent_exec",
                **metadata,
                "at": event.get("created_at") or utc_now(),
            },
        )

    @classmethod
    def write_policy_updated(
        cls,
        *,
        provider_id: str,
        before: AgentExecProviderPolicy,
        after: AgentExecProviderPolicy,
        updated_by: str,
    ) -> None:
        """写入策略更新审计事件。

        Args:
            provider_id: provider 唯一标识。
            before: 变更前策略。
            after: 变更后策略。
            updated_by: 操作人用户 ID。
        """
        def summary(policy: AgentExecProviderPolicy) -> dict[str, Any]:
            """生成不含 secret 的策略摘要。"""
            return {
                "enabled": policy.enabled,
                "allowed_roles": policy.allowed_roles,
                "allowed_task_types": policy.allowed_task_types,
                "requires_confirmation": policy.requires_confirmation,
            }

        AuditEventRepository.append(
            {
                "event_id": f"audit_{uuid4().hex[:20]}",
                "event_type": "agent_exec.policy.updated",
                "actor_user_id": updated_by,
                "actor_role": "user",
                "request_id": None,
                "entity_type": "agent_exec_provider",
                "entity_id": provider_id,
                "related_ids": {},
                "before": summary(before),
                "after": summary(after),
                "metadata": {"updated_by": updated_by},
                "created_at": utc_now(),
            }
        )
