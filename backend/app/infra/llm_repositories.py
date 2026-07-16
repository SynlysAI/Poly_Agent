"""Repositories for LLM model management state."""

from __future__ import annotations

from app.infra.computation_repositories import BaseRepository
from app.infra.mongo import get_llm_routing_configs_collection


class LLMRoutingRepository(BaseRepository):
    """Persist global LLM route selections."""

    collection_name = "llm_routing_configs"

    @classmethod
    def _collection(cls):
        return get_llm_routing_configs_collection()
