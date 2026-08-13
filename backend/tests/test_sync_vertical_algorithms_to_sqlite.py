"""垂类算法/模型配置从 Mongo 同步到 SQLite 的脚本测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from bson import ObjectId

from app.infra.sqlite_store import SqliteDocumentStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "sync_vertical_algorithms_to_sqlite.py"
SPEC = importlib.util.spec_from_file_location("sync_vertical_algorithms_to_sqlite", SCRIPT_PATH)
assert SPEC and SPEC.loader
sync_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = sync_script
SPEC.loader.exec_module(sync_script)


class FakeCursor:
    """模拟 Mongo 只读游标。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    """模拟 Mongo collection，支持本脚本用到的查询与投影。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def find(self, query=None, projection=None) -> FakeCursor:
        rows = list(self.rows)
        if query:
            for key, value in query.items():
                if isinstance(value, dict) and "$in" in value:
                    allowed = set(value["$in"])
                    rows = [row for row in rows if row.get(key) in allowed]
                elif key == "_id":
                    continue
                else:
                    rows = [row for row in rows if row.get(key) == value]
        if projection is not None:
            rows = [
                {key: value for key, value in row.items() if projection.get(key, 1)}
                for row in rows
            ]
        return FakeCursor(rows)


class FakeDatabase:
    """模拟 Mongo database。"""

    def __init__(self, collections: dict[str, list[dict]]):
        self.collections = collections

    def list_collection_names(self) -> list[str]:
        return list(self.collections)

    def __getitem__(self, name: str) -> FakeCollection:
        return FakeCollection(self.collections.get(name, []))


class FakeClient:
    """模拟只读 MongoClient。"""

    def __init__(self, database: FakeDatabase, *_args, **_kwargs):
        self.closed = False
        self.admin = self
        self.database = database

    def command(self, *_args, **_kwargs):
        return {"ok": 1}

    def close(self):
        self.closed = True

    def __getitem__(self, name: str) -> FakeDatabase:
        if name == "poly_agent":
            return self.database
        return FakeDatabase({})


class SelectRegistryDocumentsTest(unittest.TestCase):
    def test_keeps_vertical_prediction_and_remote_interface_only(self) -> None:
        database = FakeDatabase(
            {
                "algorithm_registry_entries": [
                    {"_id": ObjectId(), "algorithm_id": "vertical_uploaded", "algorithm_family": "vertical_prediction", "source": "uploaded_package"},
                    {"_id": ObjectId(), "algorithm_id": "remote_predictor", "algorithm_family": "vertical_prediction", "source": "remote_interface"},
                    {"_id": ObjectId(), "algorithm_id": "knowledge_mock", "algorithm_family": "knowledge", "source": "builtin"},
                ]
            }
        )

        documents = sync_script.select_registry_documents(database)

        self.assertEqual(
            {document["algorithm_id"] for document in documents},
            {"vertical_uploaded", "remote_predictor"},
        )
        self.assertTrue(all("_id" not in document for document in documents))


class LoadSourceDocumentsTest(unittest.TestCase):
    def test_selects_related_rows_and_all_handoffs_and_model_configs(self) -> None:
        database = FakeDatabase(
            {
                "algorithm_registry_entries": [
                    {"_id": ObjectId(), "algorithm_id": "vertical_a", "algorithm_family": "vertical_prediction", "source": "uploaded_package"},
                    {"_id": ObjectId(), "algorithm_id": "other_builtin", "algorithm_family": "knowledge", "source": "builtin"},
                ],
                "algorithm_packages": [
                    {"_id": ObjectId(), "package_id": "pkg_a", "algorithm_id": "vertical_a"},
                    {"_id": ObjectId(), "package_id": "pkg_other", "algorithm_id": "other_builtin"},
                ],
                "algorithm_versions": [
                    {"_id": ObjectId(), "version_id": "ver_a", "algorithm_id": "vertical_a"},
                    {"_id": ObjectId(), "version_id": "ver_other", "algorithm_id": "other_builtin"},
                ],
                "algorithm_runs": [
                    {"_id": ObjectId(), "run_id": "run_a", "algorithm_id": "vertical_a"},
                    {"_id": ObjectId(), "run_id": "run_other", "algorithm_id": "other_builtin"},
                ],
                "algorithm_handoffs": [
                    {"_id": ObjectId(), "handoff_id": "handoff_a", "algorithm_id": "vertical_a"},
                    {"_id": ObjectId(), "handoff_id": "handoff_raman", "algorithm_id": "raman_structure_analyzer"},
                ],
                "llm_routing_configs": [
                    {"_id": ObjectId(), "config_id": "global", "routing": {}}
                ],
                "service_integrations": [
                    {"_id": ObjectId(), "service_key": "computation-worker", "service_type": "worker"}
                ],
            }
        )

        documents = sync_script.load_source_documents(database)

        self.assertEqual(
            [document["package_id"] for document in documents["algorithm_packages"]],
            ["pkg_a"],
        )
        self.assertEqual(
            [document["version_id"] for document in documents["algorithm_versions"]],
            ["ver_a"],
        )
        self.assertEqual(
            [document["run_id"] for document in documents["algorithm_runs"]],
            ["run_a"],
        )
        self.assertEqual(
            [document["handoff_id"] for document in documents["algorithm_handoffs"]],
            ["handoff_a", "handoff_raman"],
        )
        self.assertEqual(
            [document["service_key"] for document in documents["service_integrations"]],
            ["computation-worker"],
        )
        self.assertEqual(documents["algorithm_resources"], [])


class SanitizeDocumentTest(unittest.TestCase):
    def test_converts_nested_object_ids_and_datetimes(self) -> None:
        document = {
            "created_at": datetime(2026, 8, 13, 10, 30),
            "nested": {"object_id": ObjectId(), "values": [ObjectId()]},
        }

        sanitized = sync_script.sanitize_document(document)

        self.assertEqual(sanitized["created_at"], "2026-08-13T10:30:00")
        self.assertIsInstance(sanitized["nested"]["object_id"], str)
        self.assertIsInstance(sanitized["nested"]["values"][0], str)


class MergeDocumentsTest(unittest.TestCase):
    def test_keeps_unmatched_replaces_matching_and_appends_new(self) -> None:
        existing = [
            {"algorithm_id": "keep_me", "name": "old keep"},
            {"algorithm_id": "replace_me", "name": "old replace"},
        ]
        incoming = [
            {"algorithm_id": "replace_me", "name": "new replace"},
            {"algorithm_id": "add_me", "name": "new add"},
        ]

        merged = sync_script.merge_documents(existing, incoming, "algorithm_id")

        self.assertEqual(len(merged), 3)
        self.assertEqual(merged[0], {"algorithm_id": "keep_me", "name": "old keep"})
        self.assertEqual(merged[1], {"algorithm_id": "replace_me", "name": "new replace"})
        self.assertEqual(merged[2], {"algorithm_id": "add_me", "name": "new add"})


class MainBehaviorTest(unittest.TestCase):
    def _database(self) -> FakeDatabase:
        return FakeDatabase(
            {
                "algorithm_registry_entries": [
                    {"_id": ObjectId(), "algorithm_id": "vertical_a", "algorithm_family": "vertical_prediction", "source": "uploaded_package"},
                    {"_id": ObjectId(), "algorithm_id": "knowledge_mock", "algorithm_family": "knowledge", "source": "builtin"},
                ],
                "algorithm_packages": [
                    {"_id": ObjectId(), "package_id": "pkg_a", "algorithm_id": "vertical_a"}
                ],
                "algorithm_versions": [
                    {"_id": ObjectId(), "version_id": "ver_a", "algorithm_id": "vertical_a"}
                ],
                "algorithm_resources": [],
                "algorithm_runs": [],
                "algorithm_handoffs": [],
                "llm_routing_configs": [
                    {"_id": ObjectId(), "config_id": "global", "routing": {}}
                ],
                "service_integrations": [
                    {"_id": ObjectId(), "service_key": "computation-worker", "service_type": "worker"}
                ],
            }
        )

    def test_dry_run_does_not_write_target(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-sync-dryrun-") as tmp_dir:
            output_path = Path(tmp_dir) / "store.sqlite3"
            argv = [
                "sync_vertical_algorithms_to_sqlite.py",
                "--mongodb-uri",
                "mongodb://fake",
                "--output-path",
                str(output_path),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                sync_script,
                "MongoClient",
                lambda *args, **kwargs: FakeClient(self._database()),
            ), redirect_stdout(StringIO()) as stdout:
                exit_code = sync_script.main()

            self.assertEqual(exit_code, 0)
            self.assertFalse(output_path.exists())
            summary = json.loads(stdout.getvalue())
            self.assertTrue(summary["dry_run"])
            self.assertEqual(summary["target_path"], str(output_path.resolve()))
            registry = next(
                item
                for item in summary["collections"]
                if item["collection"] == "algorithm_registry_entries"
            )
            self.assertEqual(registry["existing_count"], 0)
            self.assertEqual(registry["added"], 1)
            self.assertEqual(registry["replaced"], 0)

    def test_apply_backs_up_merges_and_writes_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-sync-apply-") as tmp_dir:
            output_path = Path(tmp_dir) / "store.sqlite3"
            store = SqliteDocumentStore(output_path)
            store.save(
                {
                    "users": [{"user_id": "u1", "username": "alice"}],
                    "algorithm_registry_entries": [
                        {"algorithm_id": "knowledge_mock", "algorithm_family": "knowledge"}
                    ],
                    "poly_data.material_records": [{"record_id": "m1"}],
                }
            )
            argv = [
                "sync_vertical_algorithms_to_sqlite.py",
                "--apply",
                "--mongodb-uri",
                "mongodb://fake",
                "--output-path",
                str(output_path),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                sync_script,
                "MongoClient",
                lambda *args, **kwargs: FakeClient(self._database()),
            ), redirect_stdout(StringIO()):
                exit_code = sync_script.main()

            self.assertEqual(exit_code, 0)
            data = store.load()
            self.assertEqual(data["users"], [{"user_id": "u1", "username": "alice"}])
            self.assertEqual(
                data["poly_data.material_records"], [{"record_id": "m1"}]
            )
            self.assertEqual(
                {row["algorithm_id"] for row in data["algorithm_registry_entries"]},
                {"knowledge_mock", "vertical_a"},
            )
            self.assertEqual(
                [row["package_id"] for row in data["algorithm_packages"]], ["pkg_a"]
            )
            self.assertEqual(
                [row["service_key"] for row in data["service_integrations"]],
                ["computation-worker"],
            )

            manifest_path = output_path.with_name(
                f"{output_path.name}.vertical-algorithms.manifest.json"
            )
            self.assertTrue(manifest_path.exists())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertFalse(manifest["dry_run"])
            backup_dir = Path(manifest["backup_path"])
            self.assertTrue((backup_dir / output_path.name).exists())


if __name__ == "__main__":
    unittest.main()
