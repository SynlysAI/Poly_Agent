"""Assistant 仓储 MongoDB 索引命名回归测试。"""

from __future__ import annotations

from unittest.mock import MagicMock

from app.infra.research_engine_repositories import AssistantChatRepository


def test_assistant_chat_indexes_use_stable_names(monkeypatch) -> None:
    """会话复合索引必须显式命名，避免与历史索引名冲突。"""

    collection = MagicMock()
    monkeypatch.setattr(AssistantChatRepository, "_collection", classmethod(lambda cls: collection))
    monkeypatch.setattr(AssistantChatRepository, "_can_use_mongo", classmethod(lambda cls: True))

    AssistantChatRepository.ensure_indexes()

    calls = {str(call.kwargs.get("name") or call.args[0]): call for call in collection.create_index.call_args_list}
    assert "chat_id" in calls
    composite_call = collection.create_index.call_args_list[-1]
    assert composite_call.kwargs.get("name") == "owner_archived_updated"
