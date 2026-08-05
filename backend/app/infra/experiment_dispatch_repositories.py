"""实验方案转发记录仓储。"""

from app.infra.computation_repositories import BaseRepository
from app.infra.mongo import get_experiment_dispatches_collection


class ExperimentDispatchRepository(BaseRepository):
    """Mongo-first、demo-store fallback 的实验方案仓储。"""

    collection_name = "experiment_dispatches"

    @classmethod
    def _collection(cls):
        return get_experiment_dispatches_collection()

    @classmethod
    def list_dispatches(cls, *, run_id=None, template_id=None, profile_id=None, created_by=None, page=1, page_size=20):
        filters = {}
        if run_id:
            filters["source.run_id"] = run_id
        if template_id:
            filters["template.template_id"] = template_id
        if profile_id:
            filters["profile.profile_id"] = profile_id
        if created_by:
            filters["created_by"] = created_by
        return cls.list_all(filters, sort_field="created_at", reverse=True, page=page, page_size=page_size)
