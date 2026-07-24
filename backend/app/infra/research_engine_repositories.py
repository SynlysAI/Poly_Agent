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
    get_algorithm_packages_collection,
    get_algorithm_registry_entries_collection,
    get_algorithm_handoffs_collection,
    get_algorithm_resources_collection,
    get_algorithm_runs_collection,
    get_algorithm_versions_collection,
    get_execution_decisions_collection,
    get_manual_algorithm_workflows_collection,
    get_research_problem_specs_collection,
    get_research_runs_collection,
    get_workflow_runs_collection,
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
        include_archived: bool = False,
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
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if material_family:
            filters["material_family"] = material_family

        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

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
        algorithm_family: str | None = None,
        material_scope: str | None = None,
        trigger_mode: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法能力清单。

        Args:
            algorithm_type: 按算法类型过滤（retriever/predictor/simulator/optimizer）。
            algorithm_family: 按产品算法族过滤。
            material_scope: 按材料体系过滤。
            trigger_mode: 按触发方式过滤（human_workflow/autoresearch/system）。
            status: 按状态过滤。
            page: 页码。
            page_size: 每页条数。

        Returns:
            (items, total) 元组。
        """
        filters: dict[str, Any] = {}
        if algorithm_type:
            filters["type"] = algorithm_type
        if algorithm_family:
            filters["algorithm_family"] = algorithm_family
        if material_scope:
            filters["material_scope"] = {"$in": [material_scope]}
        if trigger_mode:
            # 兼容旧数据：查询 "human_workflow" 时也匹配旧值 "human"
            if trigger_mode == "human_workflow":
                filters["trigger_modes"] = {"$in": ["human_workflow", "human"]}
            else:
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
        if algorithm_family:
            simple_filters["algorithm_family"] = algorithm_family
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
        # 兼容旧数据：查询 "human_workflow" 时也匹配旧值 "human"
        if trigger_mode:
            if trigger_mode == "human_workflow":
                rows = [
                    row for row in rows
                    if "human_workflow" in (row.get("trigger_modes") or [])
                    or "human" in (row.get("trigger_modes") or [])
                ]
            else:
                rows = [
                    row for row in rows
                    if trigger_mode in (row.get("trigger_modes") or [])
                ]

        rows = _sort_documents(rows, "algorithm_id", reverse=False)
        return rows[skip : skip + page_size], len(rows)

    @classmethod
    def seed_defaults(cls, entries: list[dict[str, Any]]) -> int:
        """写入默认算法能力清单条目（幂等：已存在的跳过）。

        同时修复已存在条目中的旧 trigger_modes 值（如 "human" -> "human_workflow"）。

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
            else:
                patch_fields = {
                    key: entry[key]
                    for key in (
                        "name",
                        "type",
                        "algorithm_family",
                        "material_scope",
                        "task_scope",
                        "input_schema",
                        "output_schema",
                        "call_method",
                        "trigger_modes",
                        "runtime_dependency",
                        "version",
                        "validation_metric",
                        "owner",
                        "status",
                        "description",
                        "active_version_id",
                        "source",
                        "deployment_status",
                        "integration_kind",
                        "capability_group",
                        "developer_attribution",
                        "framework_attributions",
                        "method_attributions",
                        "implementation_notes",
                    )
                    if key in entry and entry.get(key) != existing.get(key)
                }
                if patch_fields:
                    cls.update_fields(entry["algorithm_id"], patch_fields)
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

    @classmethod
    def delete(cls, algorithm_id: str) -> bool:
        """删除算法注册表条目。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"algorithm_id": algorithm_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("algorithm_id") != algorithm_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))


class AlgorithmManagedResourceRepository(BaseRepository):
    """算法大资源登记仓储。"""

    collection_name = "algorithm_resources"

    @classmethod
    def _collection(cls):
        return get_algorithm_resources_collection()

    @classmethod
    def update_fields(cls, resource_id: str, fields: dict[str, Any]) -> bool:
        """更新算法大资源字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"resource_id": resource_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("resource_id") == resource_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_resources(
        cls,
        *,
        algorithm_id: str | None = None,
        asset_key: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法大资源。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if asset_key:
            filters["asset_key"] = asset_key
        if status:
            filters["status"] = status
        return cls.list_all(filters, sort_field="updated_at", reverse=True, page=page, page_size=page_size)


class AlgorithmPackageRepository(BaseRepository):
    """上传算法包仓储。"""

    collection_name = "algorithm_packages"

    @classmethod
    def _collection(cls):
        return get_algorithm_packages_collection()

    @classmethod
    def update_fields(cls, package_id: str, fields: dict[str, Any]) -> bool:
        """更新算法包字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"package_id": package_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("package_id") == package_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete(cls, package_id: str) -> bool:
        """删除算法包记录。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"package_id": package_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("package_id") != package_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_packages(
        cls,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法上传包。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class AlgorithmVersionRepository(BaseRepository):
    """上传算法版本仓储。"""

    collection_name = "algorithm_versions"

    @classmethod
    def _collection(cls):
        return get_algorithm_versions_collection()

    @classmethod
    def update_fields(cls, version_id: str, fields: dict[str, Any]) -> bool:
        """更新算法版本字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"version_id": version_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("version_id") == version_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def delete(cls, version_id: str) -> bool:
        """删除算法版本记录。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().delete_one({"version_id": version_id})
                return result.deleted_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            before = len(data[cls.collection_name])
            data[cls.collection_name] = [
                item for item in data[cls.collection_name] if item.get("version_id") != version_id
            ]
            return len(data[cls.collection_name]) != before

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_versions(
        cls,
        *,
        algorithm_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法版本。"""
        filters: dict[str, Any] = {}
        if algorithm_id:
            filters["algorithm_id"] = algorithm_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class AlgorithmHandoffRepository(BaseRepository):
    """算法对接任务仓储。"""

    collection_name = "algorithm_handoffs"

    @classmethod
    def _collection(cls):
        return get_algorithm_handoffs_collection()

    @classmethod
    def update_fields(cls, handoff_id: str, fields: dict[str, Any]) -> bool:
        """更新算法对接任务字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one({"handoff_id": handoff_id}, {"$set": fields})
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("handoff_id") == handoff_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))

    @classmethod
    def list_handoffs(
        cls,
        *,
        status: str | None = None,
        example_id: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询算法对接任务。"""
        filters: dict[str, Any] = {}
        if status:
            filters["status"] = status
        if example_id:
            filters["example_id"] = example_id
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)


class ExecutionDecisionRepository(BaseRepository):
    """ExecutionDecision 仓储。"""

    collection_name = "execution_decisions"

    @classmethod
    def _collection(cls):
        return get_execution_decisions_collection()

    @classmethod
    def list_decisions(
        cls,
        *,
        problem_spec_id: str | None = None,
        mode: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 ExecutionDecision。"""
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if mode:
            filters["mode"] = mode
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def find_active(cls, problem_spec_id: str) -> dict[str, Any] | None:
        """查询 ProblemSpec 当前 active decision。"""
        return cls.find_one({"problem_spec_id": problem_spec_id, "status": "active"})

    @classmethod
    def update_fields(cls, decision_id: str, fields: dict[str, Any]) -> bool:
        """更新 ExecutionDecision 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"decision_id": decision_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("decision_id") == decision_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class ManualAlgorithmWorkflowRepository(BaseRepository):
    """ManualAlgorithmWorkflow 仓储。"""

    collection_name = "manual_algorithm_workflows"

    @classmethod
    def _collection(cls):
        return get_manual_algorithm_workflows_collection()

    @classmethod
    def list_workflows(
        cls,
        *,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        include_archived: bool = False,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询人工 Workflow。"""
        filters: dict[str, Any] = {}
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if execution_decision_id:
            filters["execution_decision_id"] = execution_decision_id
        if created_by:
            filters["created_by"] = created_by
        if status:
            filters["status"] = status
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

    @classmethod
    def update_fields(cls, workflow_id: str, fields: dict[str, Any]) -> bool:
        """更新人工 Workflow 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"workflow_id": workflow_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("workflow_id") == workflow_id:
                    _apply_update_fields(item, fields)
                    return True
            return False

        return bool(demo_store.mutate(mutate))


class WorkflowRunRepository(BaseRepository):
    """WorkflowRun 仓储。"""

    collection_name = "workflow_runs"

    @classmethod
    def _collection(cls):
        return get_workflow_runs_collection()

    @classmethod
    def list_runs(
        cls,
        *,
        workflow_id: str | None = None,
        problem_spec_id: str | None = None,
        execution_decision_id: str | None = None,
        status: str | None = None,
        created_by: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        """分页查询 WorkflowRun。"""
        filters: dict[str, Any] = {}
        if workflow_id:
            filters["workflow_id"] = workflow_id
        if problem_spec_id:
            filters["problem_spec_id"] = problem_spec_id
        if execution_decision_id:
            filters["execution_decision_id"] = execution_decision_id
        if status:
            filters["status"] = status
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

    @classmethod
    def update_fields(cls, workflow_run_id: str, fields: dict[str, Any]) -> bool:
        """更新 WorkflowRun 字段。"""
        if cls._can_use_mongo():
            try:
                result = cls._collection().update_one(
                    {"workflow_run_id": workflow_run_id}, {"$set": fields}
                )
                return result.matched_count > 0
            except PyMongoError as exc:
                cls._handle_mongo_error(exc)

        def mutate(data):
            for item in data[cls.collection_name]:
                if item.get("workflow_run_id") == workflow_run_id:
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
        workflow_run_id: str | None = None,
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
            workflow_run_id: 按 WorkflowRun ID 过滤。
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
        if workflow_run_id:
            filters["workflow_run_id"] = workflow_run_id
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
        include_archived: bool = False,
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
        elif not include_archived:
            filters["status"] = {"$ne": "archived"}
        if created_by:
            filters["created_by"] = created_by
        if project_id:
            filters["project_id"] = project_id

        if cls._can_use_mongo():
            return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)

        demo_filters = dict(filters)
        exclude_archived = demo_filters.get("status") == {"$ne": "archived"}
        if exclude_archived:
            demo_filters.pop("status", None)
        items, total = cls.list_all(demo_filters, sort_field="created_at", reverse=True, page=1, page_size=10000)
        if exclude_archived:
            items = [item for item in items if item.get("status") != "archived"]
            total = len(items)
        start = (page - 1) * page_size
        return items[start:start + page_size], total

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
