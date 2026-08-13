"""poly data SQLite 抽样脚本的只读与写目标测试。"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from app.infra.sqlite_store import SqliteDocumentStore


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "seed_poly_data_sqlite.py"
SPEC = importlib.util.spec_from_file_location("seed_poly_data_sqlite", SCRIPT_PATH)
assert SPEC and SPEC.loader
seed_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = seed_script
SPEC.loader.exec_module(seed_script)


class FakeCursor:
    """模拟 Mongo 只读游标。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def sort(self, *_args, **_kwargs):
        return self

    def limit(self, count: int):
        return FakeCursor(self.rows[:count])

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    """模拟 Mongo collection，只暴露读接口。"""

    def __init__(self, rows: list[dict]):
        self.rows = rows

    def estimated_document_count(self) -> int:
        return len(self.rows)

    def find(self, *_args, **_kwargs) -> FakeCursor:
        return FakeCursor(self.rows)


class FakeDatabase:
    """模拟 Mongo database。"""

    def __init__(self, collections: dict[str, list[dict]]):
        self.collections = collections

    def list_collection_names(self) -> list[str]:
        return list(self.collections)

    def __getitem__(self, name: str) -> FakeCollection:
        return FakeCollection(self.collections[name])


class FakeClient:
    """模拟只读 MongoClient。"""

    def __init__(self, uri: str, **_kwargs):
        self.uri = uri
        self.closed = False
        self.admin = self

    def command(self, *_args, **_kwargs):
        return {"ok": 1}

    def __getitem__(self, name: str) -> FakeDatabase:
        return FakeDatabase(
            {
                "material_records": [{"polymer_record_id": "M1"}],
                "dataset_stats": [
                    {"dataset_id": "openpoly"},
                    {"dataset_id": "radonpy_pi1070"},
                ],
            }
        )

    def close(self) -> None:
        self.closed = True


class SeedPolyDataSqliteTest(unittest.TestCase):
    """覆盖抽样上限、dataset_stats 全量与只读目标写入。"""

    def test_parser_requires_source_uri(self) -> None:
        with patch.dict("os.environ", {}, clear=True), patch.object(
            sys, "argv", ["seed_poly_data_sqlite.py"]
        ):
            with self.assertRaises(SystemExit):
                seed_script.main()

    def test_sample_collection_limits_normal_collections(self) -> None:
        database = FakeDatabase(
            {
                "material_records": [{"polymer_record_id": f"M{i}"} for i in range(5)],
                "dataset_stats": [{"dataset_id": f"D{i}"} for i in range(4)],
            }
        )
        total, rows = seed_script.sample_collection(
            database,
            "material_records",
            sample_size=2,
        )
        self.assertEqual(total, 5)
        self.assertEqual(len(rows), 2)

        _, stats = seed_script.sample_collection(
            database,
            "dataset_stats",
            sample_size=2,
        )
        self.assertEqual(len(stats), 4)

    def test_write_target_reset_rebuilds_poly_data_and_preserves_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-seed-test-") as tmp_dir:
            store = SqliteDocumentStore(Path(tmp_dir) / "store.sqlite3")
            store.save(
                {
                    "users": [{"user_id": "u_admin"}],
                    "invite_codes": [{"invite_id": "i1"}],
                    "computation_runs": [{"run_id": "old"}],
                    "poly_data.dataset_stats": [{"dataset_id": "old-dataset"}],
                }
            )
            seed_script.write_target(
                store,
                {"material_records": [{"polymer_record_id": "M1"}]},
                reset=True,
            )
            data = store.load()
            self.assertEqual(
                data["poly_data.material_records"],
                [{"polymer_record_id": "M1"}],
            )
            self.assertEqual(data["users"], [{"user_id": "u_admin"}])
            self.assertEqual(data["invite_codes"], [{"invite_id": "i1"}])
            self.assertEqual(data["computation_runs"], [{"run_id": "old"}])
            self.assertEqual(data["poly_data.dataset_stats"], [])

    def test_write_target_merge_preserves_existing_collections(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-seed-test-") as tmp_dir:
            store = SqliteDocumentStore(Path(tmp_dir) / "store.sqlite3")
            store.save(
                {
                    "users": [{"user_id": "u_admin"}],
                    "poly_data.dataset_stats": [{"dataset_id": "kept"}],
                }
            )
            seed_script.write_target(
                store,
                {"material_records": [{"polymer_record_id": "M1"}]},
                reset=False,
            )
            data = store.load()
            self.assertEqual(data["users"], [{"user_id": "u_admin"}])
            self.assertEqual(
                data["poly_data.dataset_stats"],
                [{"dataset_id": "kept"}],
            )
            self.assertEqual(
                data["poly_data.material_records"],
                [{"polymer_record_id": "M1"}],
            )

    def test_parser_defaults_to_merge_and_reset_is_opt_in(self) -> None:
        parser = seed_script.build_parser()
        self.assertFalse(parser.parse_args([]).reset)
        self.assertTrue(parser.parse_args(["--reset"]).reset)
        self.assertFalse(parser.parse_args(["--no-reset"]).reset)

    def test_main_dry_run_is_read_only_and_emits_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="poly-agent-seed-dryrun-") as tmp_dir:
            output_path = Path(tmp_dir) / "store.sqlite3"
            argv = [
                "seed_poly_data_sqlite.py",
                "--dry-run",
                "--mongodb-uri",
                "mongodb://fake",
                "--collections",
                "material_records,dataset_stats",
                "--sample-size",
                "1",
                "--output-path",
                str(output_path),
            ]
            with patch.object(sys, "argv", argv), patch.object(
                seed_script, "MongoClient", FakeClient
            ), redirect_stdout(StringIO()) as stdout:
                exit_code = seed_script.main()

            self.assertEqual(exit_code, 0)
            self.assertFalse(output_path.exists())
            manifest = json.loads(stdout.getvalue())
            self.assertEqual(manifest["dry_run"], True)
            self.assertEqual(len(manifest["collections"]), 2)
            self.assertTrue(
                all(item["sample_count"] <= 1 for item in manifest["collections"][:1])
            )

    def test_poly_data_collection_names_are_registered(self) -> None:
        names = seed_script.poly_data_collection_names()
        self.assertIn("material_records", names)
        self.assertIn("dataset_stats", names)
        self.assertGreaterEqual(len(names), 20)
