"""ResearchEngine 领域仓储。

按现有 BaseRepository 模式扩展持久化层，实现 Mongo-first + demo JSON 双模存储。
新增仓储类继承 BaseRepository，遵循 computation_repositories.py 的风格。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pymongo.errors import PyMongoError

from app.infra.computation_repositories import (
    BaseRepository,
    _apply_update_fields,
    _matches,
    _sort_documents,
    _without_mongo_id,
    clone_document,
    demo_store,
)
from app.infra.mongo import (
    get_algorithm_registry_entries_collection,
    get_algorithm_runs_collection,
    get_research_problem_specs_collection,
    get_research_runs_collection,
)


class ResearchProblemSpecRepository(BaseRepository):
    """ProblemSpec 仓储。

    支持 create/get/list/update/freeze，
    按 project_id、campaign_id、created_by 过滤。
    """

    collection_name = "research_problem_specs"

    @classmethod
    def _collection(cls):
        return get_research_problem_specs_collection()

    @classmethod
    def list_problem_specs(
        cls,
        *,
        project_id: str | None = None,
        campaign_id: str | None = None,
        created_by: str | None = None,
        status: str | None = None,
        material_family: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ProblemSpec。

        Args:
            project_id: 按项目 ID 过滤。
            campaign_id: 按 campaign ID 过滤。
            created_by: 按创建者过滤。
            status: 按状态过滤。
            material_family: 按材料体系过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if project_id:
            filters["project_id"] = project_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if created_by:
            filters["created_by"] = created_by
        if status:
            filters["status"] = status
        if material_family:
            filters["material_family"] = material_family

        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, problem_spec_id: str, fields: dict[str, Any]) -> bool:
        """更新 ProblemSpec 字段。

        Args:
            problem_spec_id: ProblemSpec ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"problem_spec_id": problem_spec_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("problem_spec_id") == problem_spec_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def find_by_campaign(cls, campaign_id: str) -> list[dict[str, Any]]:
        """按 campaign_id 查询关联的 ProblemSpec。

        Args:
            campaign_id: Campaign ID。

        Returns:
            ProblemSpec 文档列表。
        """
        items, _ = cls.list_all(
            {"campaign_id": campaign_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=100,
        )
        return items


class AlgorithmRegistryRepository(BaseRepository):
    """AlgorithmRegistry 仓储。

    支持只读清单查询，按 type、material_scope、trigger_mode、status 过滤。
    """

    collection_name = "algorithm_registry_entries"

    @classmethod
    def _collection(cls):
        return get_algorithm_registry_entries_collection()

    @classmethod
    def list_algorithms(
        cls,
        *,
        algorithm_type: str | None = None,
        material_scope: str | None = None,
        trigger_mode: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法能力清单。

        Args:
            algorithm_type: 按算法类型过滤（retriever/predictor/simulator/optimizer）。
            material_scope: 按材料体系过滤。
            trigger_mode: 按触发方式过滤（human/autoresearch/system）。
            status: 按状态过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if algorithm_type:
            filters["type"] = algorithm_type
        if material_scope:
            filters["material_scope"] = {"$in": [material_scope]}
        if trigger_mode:
            filters["trigger_modes"] = {"$in": [trigger_mode]}
        if status:
            filters["status"] = status

        skip = (page - 1) * page_size
        if cls._can_use_mongo():
            try:
                collection = cls._collection()
                total = int(collection.count_documents(filters))
                cursor = (
                    collection.find(filters, {"_id": 0})
                    .sort([("algorithm_id", 1)])
                    .skip(skip)
                    .limit(page_size)
                )
                return [dict(item) for item in cursor], total
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        # Demo store: 先用简单相等条件过滤，再对数组字段做后置过滤
        simple_filters: dict[str, Any] = {}
        if algorithm_type:
            simple_filters["type"] = algorithm_type
        if status:
            simple_filters["status"] = status

        data_demo = demo_store.load()
        rows = [
            clone_document(item)
            for item in data_demo[cls.collection_name]
            if _matches(item, simple_filters)
        ]

        # 后置过滤：material_scope（检查值是否包含在 material_scope 列表中）
        if material_scope:
            rows = [
                row for row in rows
                if material_scope in (row.get("material_scope") or [])
            ]

        # 后置过滤：trigger_modes（检查值是否包含在 trigger_modes 列表中）
        if trigger_mode:
            rows = [
                row for row in rows
                if trigger_mode in (row.get("trigger_modes") or [])
            ]

        rows = _sort_documents(rows, "algorithm_id", reverse=False)
        return rows[skip : skip + page_size], len(rows)

    @classmethod
    def seed_defaults(cls, entries: list[dict[str, Any]]) -> int:
        """写入默认算法能力清单条目（幂等：已存在的跳过）。

        Args:
            entries: 算法条目字典列表。

        Returns:
            实际写入的条目数。
        """
        count = 0
        for entry in entries:
            existing = cls.find_one({"algorithm_id": entry["algorithm_id"]})
            if existing is None:
                cls.save("algorithm_id", entry)
                count += 1
        return count

    @classmethod
    def update_fields(cls, algorithm_id: str, fields: dict[str, Any]) -> bool:
        """更新算法条目字段。

        Args:
            algorithm_id: 算法 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"algorithm_id": algorithm_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("algorithm_id") == algorithm_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class AlgorithmRunRepository(BaseRepository):
    """AlgorithmRun 仓储。

    支持 create/get/list，
    按 problem_spec_id、campaign_id、algorithm_id、status、trigger_source 过滤。
    """

    collection_name = "algorithm_runs"

    @classmethod
    def _collection(cls):
        return get_algorithm_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        algorithm_id: str | None = None,
        status: str | None = None,
        trigger_source: str | None = None,
        research_run_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 AlgorithmRun。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            algorithm_id: 按算法 ID 过滤。
            status: 按运行状态过滤。
            trigger_source: 按触发来源过滤。
            research_run_id: 按 ResearchRun ID 过滤。
            created_by: 按创建者过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if trigger_source:
            filters["trigger_source"] = trigger_source
        if research_run_id:
            filters["research_run_id"] = research_run_id
        if created_by:
            filters["created_by"] = created_by

        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, run_id: str, fields: dict[str, Any]) -> bool:
        """更新 AlgorithmRun 字段。

        Args:
            run_id: 运行 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"run_id": run_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_by_research_run(cls, research_run_id: str) -> list[dict[str, Any]]:
        """查询 ResearchRun 关联的所有 AlgorithmRun。

        Args:
            research_run_id: ResearchRun ID。

        Returns:
            AlgorithmRun 文档列表。
        """
        items, _ = cls.list_all(
            {"research_run_id": research_run_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=500,
        )
        return items


class ResearchRunRepository(BaseRepository):
    """ResearchRun 仓储。

    支持 create/get/list/update，
    按 problem_spec_id、campaign_id、status 过滤。
    """

    collection_name = "research_runs"

    @classmethod
    def _collection(cls):
        return get_research_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        problem_spec_id: str | None = None,
        campaign_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        project_id: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ResearchRun。

        Args:
            problem_spec_id: 按 ProblemSpec ID 过滤。
            campaign_id: 按 Campaign ID 过滤。
            status: 按状态过滤。
            created_by: 按创建者过滤。
            project_id: 按项目 ID 过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if campaign_id:
            filters["campaign_id"] = campaign_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        if project_id:
            filters["project_id"] = project_id

        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, run_id: str, fields: dict[str, Any]) -> bool:
        """更新 ResearchRun 字段。

        Args:
            run_id: 运行 ID。
            fields: 要更新的字段字典。

        Returns:
            是否更新成功。
        """
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"run_id": run_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("run_id") == run_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_by_problem_spec(cls, problem_spec_id: str) -> list[dict[str, Any]]:
        """查询 ProblemSpec 关联的所有 ResearchRun。

        Args:
            problem_spec_id: ProblemSpec ID。

        Returns:
            ResearchRun 文档列表。
        """
        items, _ = cls.list_all(
            {"problem_spec_id": problem_spec_id},
            sort_field="created_at",
            reverse=False,
            page=1,
            page_size=100,
        )
        return items
