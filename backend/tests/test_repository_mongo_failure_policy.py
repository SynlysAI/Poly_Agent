"""Mongo 投影与生产存储失败策略回归测试。"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from pymongo import MongoClient
from pymongo.errors import OperationFailure

from app.core.config import settings
from app.infra import computation_repositories
from app.infra.computation_repositories import BaseRepository
from app.infra.research_engine_repositories import AssistantRunRepository


class _ProjectionValidatingCollection:
    """模拟 MongoDB 服务端投影校验的测试集合。"""

    def __init__(self, document: dict) -> None:
        self.document = document
        self.update_payloads: list[dict] = []

    def find_one_and_update(self, _filter, update, projection=None, **_kwargs):
        """校验投影合法性并返回递增前的文档片段。"""
        values = list((projection or {}).values())
        if any(value != 1 for value in values):
            raise RuntimeError("Mongo projection cannot mix inclusion and exclusion")
        previous_event_seq = self.document.get("event_seq", 0)
        if "event_seq" in update.get("$inc", {}):
            self.document["event_seq"] += update["$inc"]["event_seq"]
        return {
            key: previous_event_seq if key == "event_seq" else self.document.get(key)
            for key in (projection or {})
        }

    def update_one(self, _filter, update) -> None:
        """记录 embedded event 更新请求。"""
        self.update_payloads.append(update)


class _OperationFailureRepository(BaseRepository):
    """用于统计 Mongo 访问次数的失败仓储。"""

    collection_name = "users"
    attempts = 0

    @classmethod
    def _collection(cls):
        """每次访问都抛出确定性 Mongo 查询错误。"""
        cls.attempts += 1
        raise OperationFailure("Cannot do inclusion in exclusion projection")


class MongoFailurePolicyTest(unittest.TestCase):
    """覆盖 Assistant 事件投影和生产模式禁止 SQLite 兜底。"""

    def setUp(self) -> None:
        self.original_storage_backend = settings.storage_backend
        self.original_require_mongodb = settings.require_mongodb
        self.original_mongo_unavailable = computation_repositories._mongo_unavailable
        settings.storage_backend = "mongodb"
        settings.require_mongodb = True
        computation_repositories._mongo_unavailable = False
        _OperationFailureRepository.attempts = 0

    def tearDown(self) -> None:
        settings.storage_backend = self.original_storage_backend
        settings.require_mongodb = self.original_require_mongodb
        computation_repositories._mongo_unavailable = self.original_mongo_unavailable

    def test_append_event_uses_pure_inclusion_projection(self) -> None:
        """验证 Assistant 事件投影不能混合 inclusion 与 exclusion。"""
        collection = _ProjectionValidatingCollection(
            {
                "run_id": "asrun_projection",
                "chat_id": "chat_projection",
                "created_by": "user_projection",
                "event_seq": 0,
                "event_id": "legacy_event",
            }
        )

        with (
            patch.object(AssistantRunRepository, "_collection", return_value=collection),
            patch.object(AssistantRunRepository, "_can_use_mongo", return_value=True),
        ):
            payload = AssistantRunRepository.append_event(
                "asrun_projection",
                {"type": "tool_call", "phase": "requested", "at": "2026-08-15T22:00:00Z"},
            )

        self.assertEqual(payload["seq"], 1)
        self.assertEqual(len(collection.update_payloads), 1)

    def test_deterministic_mongo_error_does_not_disable_mongo(self) -> None:
        """生产模式下确定性查询错误不能把后续读取切到 SQLite。"""
        with self.assertRaises(HTTPException) as first_error:
            _OperationFailureRepository.find_one({"username": "admin"})
        with self.assertRaises(HTTPException) as second_error:
            _OperationFailureRepository.find_one({"username": "admin"})

        self.assertEqual(first_error.exception.status_code, 503)
        self.assertEqual(second_error.exception.status_code, 503)
        self.assertEqual(_OperationFailureRepository.attempts, 2)
        self.assertFalse(computation_repositories._mongo_unavailable)

    @unittest.skipUnless(
        os.getenv("POLY_AGENT_TEST_MONGODB_URI"),
        "set POLY_AGENT_TEST_MONGODB_URI to run the real MongoDB projection test",
    )
    def test_append_event_projection_is_accepted_by_mongodb(self) -> None:
        """在真实 MongoDB 上验证 Assistant 事件投影可执行。"""
        client = MongoClient(os.getenv("POLY_AGENT_TEST_MONGODB_URI"))
        database_name = "poly_agent_projection_regression"
        collection = client[database_name]["assistant_runs"]
        collection.delete_many({})
        collection.insert_one(
            {
                "run_id": "asrun_mongo_projection",
                "chat_id": "chat_mongo_projection",
                "created_by": "user_mongo_projection",
                "event_seq": 0,
                "event_id": "legacy_event",
            }
        )

        try:
            with (
                patch.object(AssistantRunRepository, "_collection", return_value=collection),
                patch.object(AssistantRunRepository, "_can_use_mongo", return_value=True),
            ):
                payload = AssistantRunRepository.append_event(
                    "asrun_mongo_projection",
                    {"type": "tool_call", "phase": "requested", "at": "2026-08-15T22:00:00Z"},
                )

            stored = collection.find_one({"run_id": "asrun_mongo_projection"})
            self.assertEqual(payload["seq"], 1)
            self.assertEqual(stored["event_seq"], 1)
            self.assertEqual(len(stored["events"]), 1)
        finally:
            client.drop_database(database_name)
            client.close()


if __name__ == "__main__":
    unittest.main()
