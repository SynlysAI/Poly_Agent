"""实验下发配置与目标契约仓储。"""

from app.infra.computation_repositories import BaseRepository
from app.infra.mongo import (
    get_experiment_dispatch_profiles_collection,
    get_experiment_dispatch_targets_collection,
)


class ExperimentDispatchProfileRepository(BaseRepository):
    collection_name = "experiment_dispatch_profiles"

    @classmethod
    def _collection(cls):
        return get_experiment_dispatch_profiles_collection()


class ExperimentDispatchTargetRepository(BaseRepository):
    collection_name = "experiment_dispatch_targets"

    @classmethod
    def _collection(cls):
        return get_experiment_dispatch_targets_collection()
