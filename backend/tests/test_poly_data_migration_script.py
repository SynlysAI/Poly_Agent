"""Poly Data migration script tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from io import BytesIO
from io import StringIO
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "migrate_poly_data_assets.py"
SPEC = importlib.util.spec_from_file_location("migrate_poly_data_assets", SCRIPT_PATH)
assert SPEC and SPEC.loader
migration_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = migration_script
SPEC.loader.exec_module(migration_script)


class FakeS3Client:
    """In-memory object client for migration tests."""

    def __init__(self) -> None:
        self.objects = {
            "poly_agent/datasets/radonpy_pi1070/docs/readme.md": {"size_bytes": 10, "etag": "a"},
            "datasets/radonpy_pi1070/raw/pi1070.xlsx": {"size_bytes": 15, "etag": "radonpy"},
            "datasets/pi1m_v2/raw/pi1m_v2.csv": {"size_bytes": 20, "etag": "b"},
            "datasets/smipoly/raw/202207_smip_monset.csv": {"size_bytes": 25, "etag": "smipoly"},
            "datasets/polyuniverse/raw/diCOOH.csv": {"size_bytes": 30, "etag": "dicooh"},
            "datasets/polyuniverse/raw/epoxy_diE.csv": {"size_bytes": 31, "etag": "die"},
            "datasets/polyuniverse/raw/epoxy_diN.csv": {"size_bytes": 32, "etag": "din"},
        }
        self.deleted: list[str] = []
        self.uploads: dict[str, bytes] = {}

    def head_object(self, bucket: str, object_key: str):
        return self.objects.get(object_key)

    def copy_object(self, bucket: str, source_key: str, target_key: str) -> None:
        self.objects[target_key] = dict(self.objects[source_key])

    def delete_object(self, bucket: str, object_key: str) -> None:
        self.deleted.append(object_key)
        self.objects.pop(object_key, None)

    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        self.uploads[object_key] = content
        self.objects[object_key] = {"size_bytes": len(content), "etag": f"uploaded-{len(content)}"}

    def get_object(self, bucket: str, object_key: str) -> bytes:
        return self.uploads.get(object_key, b"fake-object")

    def list_objects(self, bucket: str, prefix: str):
        return {
            key: dict(metadata)
            for key, metadata in self.objects.items()
            if key.startswith(prefix)
        }


class ChangingHeadS3Client(FakeS3Client):
    def __init__(self, object_key: str) -> None:
        super().__init__()
        self.object_key = object_key
        self.calls = 0

    def head_object(self, bucket: str, object_key: str):
        metadata = super().head_object(bucket, object_key)
        if object_key == self.object_key and metadata:
            self.calls += 1
            return {**metadata, "etag": f"version-{self.calls}"}
        return metadata


class FakeSftpClient:
    """In-memory SFTP source client for migration tests."""

    def __init__(self) -> None:
        self.files = {
            "/remote/03_SMiPoly/03_SMiPoly_README(3).md": b"# SMiPoly\n",
            "/remote/03_SMiPoly/202207_smip_monset.csv": b"comID,SMILES\nCID174,C(CO)O\n",
            "/remote/04_PolyUniverse/04_PolyUniverse_README(4).md": b"# PolyUniverse\n",
            "/remote/04_PolyUniverse/diCOOH.csv": b"Smiles\nCC(O)=O\n",
            "/remote/04_PolyUniverse/epoxy_diE.csv": b"Smiles\nC1OC1\n",
            "/remote/04_PolyUniverse/epoxy_diN.csv": b"Smiles\nCN\n",
            "/remote-md/C/polymer_1_1_32npt.data": b"LAMMPS data\n",
            "/remote-md/C/results/250_1_1_32_.out": b"250 K output\n",
            "/remote-md/F/polymer_2_1_32npt.data": b"F data\n",
            "/remote-md/Si/polymer_3_1_32npt.data": b"Si data\n",
        }

    def stat_file(self, remote_path: str):
        content = self.files.get(remote_path)
        if content is None:
            return None
        return {"size_bytes": len(content), "mtime": "2026-07-21T00:00:00+00:00"}

    def read_file(self, remote_path: str) -> bytes:
        return self.files[remote_path]

    def read_file_chunks(self, remote_path: str, *, chunk_size: int = 8 * 1024 * 1024):
        content = self.files[remote_path]
        for start in range(0, len(content), chunk_size):
            yield content[start : start + chunk_size]

    def close(self) -> None:
        pass

    def list_files_recursive(self, remote_root: str):
        prefix = remote_root.rstrip("/") + "/"
        return [
            {
                "remote_path": path,
                "relative_path": path.removeprefix(prefix),
                "size_bytes": len(content),
                "mtime": "2026-07-21T00:00:00+00:00",
            }
            for path, content in sorted(self.files.items())
            if path.startswith(prefix)
        ]


class MissingAndEmptySftpClient(FakeSftpClient):
    def list_files_recursive(self, remote_root: str):
        if remote_root.endswith("/F"):
            return []
        if remote_root.endswith("/Si"):
            raise FileNotFoundError(remote_root)
        return super().list_files_recursive(remote_root)


class PartiallyFailingS3Client(FakeS3Client):
    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        if object_key.endswith("polymer_2_1_32npt.data"):
            raise OSError("simulated upload failure")
        super().put_object(bucket, object_key, content, content_type)


class SelectivelyFailingS3Client(FakeS3Client):
    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        if object_key.endswith("polymer_1_1_32npt.data"):
            raise OSError("permanent upload failure")
        super().put_object(bucket, object_key, content, content_type)


class ConcurrentReadState:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.active = 0
        self.max_active = 0
        self.created = 0
        self.closed = 0


class ConcurrentSftpClient(FakeSftpClient):
    def __init__(self, state: ConcurrentReadState) -> None:
        super().__init__()
        self.state = state
        with self.state.lock:
            self.state.created += 1

    def read_file(self, remote_path: str) -> bytes:
        with self.state.lock:
            self.state.active += 1
            self.state.max_active = max(self.state.max_active, self.state.active)
        try:
            time.sleep(0.03)
            return super().read_file(remote_path)
        finally:
            with self.state.lock:
                self.state.active -= 1

    def close(self) -> None:
        with self.state.lock:
            self.state.closed += 1


class TransientS3Client(FakeS3Client):
    def __init__(self, failures: int) -> None:
        super().__init__()
        self.failures = failures
        self.attempts = 0

    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        if object_key.startswith("datasets/md_allatom/raw/"):
            self.attempts += 1
        if object_key.startswith("datasets/md_allatom/raw/") and self.attempts <= self.failures:
            raise OSError(f"transient failure {self.attempts}")
        super().put_object(bucket, object_key, content, content_type)


class InventoryOnlyS3Client(FakeS3Client):
    def __init__(self, object_key: str, size_bytes: int) -> None:
        super().__init__()
        self.objects[object_key] = {"size_bytes": size_bytes, "etag": "existing"}
        self.head_calls = 0

    def head_object(self, bucket: str, object_key: str):
        self.head_calls += 1
        return super().head_object(bucket, object_key)


class BlockingSecondUploadS3Client(FakeS3Client):
    def __init__(self) -> None:
        super().__init__()
        self.second_started = threading.Event()
        self.release_second = threading.Event()

    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        if object_key.endswith("250_1_1_32_.out"):
            self.second_started.set()
            self.release_second.wait(timeout=5)
        super().put_object(bucket, object_key, content, content_type)


class MultipartProbeClient(migration_script.S3Client):
    def __init__(self) -> None:
        super().__init__(endpoint="http://minio.test", access_key="access", secret_key="secret", secure=False)
        self.aborted = False

    def _create_multipart_upload(self, bucket: str, object_key: str, *, content_type: str) -> str:
        return "upload-1"

    def _upload_part(self, bucket: str, object_key: str, upload_id: str, part_number: int, payload: bytes) -> str:
        return f"etag-{part_number}"

    def _complete_multipart_upload(self, bucket: str, object_key: str, upload_id: str, parts: list[dict]) -> None:
        raise AssertionError("cancelled upload must not complete")

    def _abort_multipart_upload(self, bucket: str, object_key: str, upload_id: str) -> None:
        self.aborted = True


class FakeCollection:
    """Small Mongo collection fake for state-based migration tests."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = list(rows or [])
        self.indexes: list[tuple] = []
        self.bulk_batches: list[int] = []
        self.dropped = False

    def estimated_document_count(self) -> int:
        return len(self.rows)

    def count_documents(self, filters: dict) -> int:
        if not filters:
            return len(self.rows)
        return sum(1 for row in self.rows if all(self._nested_value(row, key) == value for key, value in filters.items()))

    def find(self, filters: dict, projection: dict | None = None):
        return [
            dict(row)
            for row in self.rows
            if all(self._nested_value(row, key) == value for key, value in filters.items())
        ]

    def find_one(self, filters: dict, projection: dict | None = None, **kwargs):
        for row in self.rows:
            if all(self._nested_value(row, key) == value for key, value in filters.items()):
                return dict(row)
        return None

    def update_one(self, filters: dict, update: dict, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for row in self.rows:
            if all(row.get(key) == value for key, value in filters.items()):
                row.update(payload)
                for key, value in update.get("$inc", {}).items():
                    row[key] = row.get(key, 0) + value
                return
        if upsert:
            row = {**filters, **payload}
            for key, value in update.get("$inc", {}).items():
                row[key] = row.get(key, 0) + value
            self.rows.append(row)

    def bulk_write(self, operations, ordered: bool = False):
        self.bulk_batches.append(len(operations))
        for operation in operations:
            self.update_one(operation._filter, operation._doc, upsert=operation._upsert)

        class Result:
            upserted_count = 0
            modified_count = len(operations)
            matched_count = len(operations)

        return Result()

    def create_index(self, keys, name: str, unique: bool = False, **kwargs) -> None:
        self.indexes.append((keys, name, unique))

    def insert_one(self, document: dict) -> None:
        self.rows.append(dict(document))

    def drop(self) -> None:
        self.dropped = True
        self.rows = []

    def _nested_value(self, row: dict, dotted_key: str):
        value = row
        for part in dotted_key.split("."):
            if not isinstance(value, dict):
                return None
            value = value.get(part)
        return value


class SizeLimitedCollection(FakeCollection):
    """Fake Mongo collection that rejects oversized inserted documents."""

    def __init__(self, rows: list[dict] | None = None, *, max_json_bytes: int = 4096) -> None:
        super().__init__(rows)
        self.max_json_bytes = max_json_bytes

    def insert_one(self, document: dict) -> None:
        payload = migration_script.json.dumps(document, default=str).encode("utf-8")
        if len(payload) > self.max_json_bytes:
            raise RuntimeError(f"document too large: {len(payload)} bytes")
        super().insert_one(document)


class FakeDatabase:
    """Collection factory fake."""

    def __init__(self, collections: dict[str, FakeCollection] | None = None) -> None:
        self.collections = collections or {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]

    def replace_collection(self, staging_name: str, target_name: str) -> None:
        self.collections[target_name] = self.collections.pop(staging_name)


class DynamicAttributeDatabase:
    """Mimic PyMongo Database's dynamic collection attribute lookup."""

    def __init__(self, collections: dict[str, FakeCollection] | None = None) -> None:
        self.collections = collections or {}

    def __getitem__(self, name: str) -> FakeCollection:
        collection = self.collections.setdefault(name, RenameableCollection(self, name))
        if not isinstance(collection, RenameableCollection):
            replacement = RenameableCollection(self, name, collection.rows)
            self.collections[name] = replacement
            collection = replacement

        return self.collections[name]

    def __getattr__(self, name: str) -> FakeCollection:
        return self[name]


class RenameableCollection(FakeCollection):
    """Collection fake with the PyMongo rename operation used by the fallback."""

    def __init__(self, database: DynamicAttributeDatabase, name: str, rows: list[dict] | None = None) -> None:
        super().__init__(rows)
        self.database = database
        self.name = name

    def rename(self, target_name: str, dropTarget: bool = False) -> None:
        if dropTarget:
            self.database.collections.pop(target_name, None)
        self.database.collections[target_name] = self
        self.database.collections.pop(self.name, None)
        self.name = target_name


class ExistingSourceRowIndexCollection(FakeCollection):
    """Reject a conflicting reuse of an existing Mongo index name."""

    def __init__(self) -> None:
        super().__init__()
        self.indexes.append(([('source_file', 1), ('source_row_index', 1)], 'source_row', False))

    def create_index(self, keys, name: str, unique: bool = False, **kwargs) -> None:
        for existing_keys, existing_name, _ in self.indexes:
            if existing_name == name and existing_keys != keys:
                raise AssertionError(f"conflicting index definition for {name}")
        super().create_index(keys, name, unique, **kwargs)


class PyMongoLikeCollection:
    """Mimic PyMongo's dynamic collection attribute lookup."""

    def __init__(self) -> None:
        self.find_called = False

    def __getattr__(self, name: str):
        return PyMongoLikeCollection()

    def find(self, filters: dict, projection: dict | None = None):
        self.find_called = True
        return [{"md_allatom_file_id": "MDALLATOM-FILE-C-000001", "family": "C"}]


class PolyDataMigrationScriptTest(unittest.TestCase):
    def test_create_indexes_matches_existing_extra_source_row_schema(self) -> None:
        target_db = FakeDatabase({'omg_polymers': ExistingSourceRowIndexCollection()})

        migration_script.create_indexes(target_db)

        self.assertIn(([('source_file', 1), ('source_row_index', 1)], 'source_row', False), target_db['omg_polymers'].indexes)

    def test_atomic_replace_uses_collection_rename_for_dynamic_database_attributes(self) -> None:
        target_db = DynamicAttributeDatabase(
            {"__staging_dataset_job": FakeCollection([{"record_id": "1"}])}
        )

        migration_script.atomic_replace_collection(
            target_db,
            "__staging_dataset_job",
            "dataset_records",
        )

        self.assertEqual(target_db["dataset_records"].count_documents({}), 1)
        self.assertNotIn("__staging_dataset_job", target_db.collections)

    """Test dry-run and apply behavior without network or MongoDB I/O."""

    def test_dry_run_does_not_mutate_minio_objects(self) -> None:
        client = FakeS3Client()

        records = migration_script.migrate_minio_objects(client, bucket="polymer-data", apply=False, delete_legacy=True)

        self.assertEqual(records[0]["status"], "planned")
        self.assertIn("poly_agent/datasets/radonpy_pi1070/docs/readme.md", client.objects)
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.uploads, {})

    def test_apply_copies_verifies_deletes_and_uploads_manifest(self) -> None:
        client = FakeS3Client()
        source_db = FakeDatabase(
            {
                "Poly_Agent": FakeCollection(
                    [
                        {
                            "polymer_record_id": "OPENPOLY-1",
                            "dataset": {"dataset_code": "openpoly"},
                            "polymer": {"psmiles": "[*]CC[*]"},
                        }
                    ]
                )
            }
        )
        target_db = FakeDatabase()

        records = migration_script.migrate_minio_objects(client, bucket="polymer-data", apply=True, delete_legacy=True)
        mongo_summary = migration_script.migrate_mongo_assets(
            source_db=source_db,
            target_db=target_db,
            object_records=records,
            apply=True,
            drop_source_after_verify=False,
        )
        manifest = migration_script.build_manifest(
            bucket="polymer-data",
            apply=True,
            minio_records=records,
            mongo_summary=mongo_summary,
            import_summaries=[],
        )
        with patch.object(migration_script, "LOCAL_MANIFEST_PATH", Path("/tmp/poly-data-test-manifest.json")):
            migration_script.persist_manifest(target_db=target_db, client=client, bucket="polymer-data", manifest=manifest)

        readme_record = next(
            record
            for record in records
            if record["legacy_key"] == "poly_agent/datasets/radonpy_pi1070/docs/readme.md"
        )
        already_record = next(
            record
            for record in records
            if record["object_key"] == "datasets/pi1m_v2/raw/pi1m_v2.csv"
        )

        self.assertEqual(readme_record["status"], "renamed")
        self.assertEqual(already_record["status"], "already_migrated")
        self.assertIn("datasets/radonpy_pi1070/docs/readme.md", client.objects)
        self.assertIn("poly_agent/datasets/radonpy_pi1070/docs/readme.md", client.deleted)
        self.assertEqual(mongo_summary["status"], "verified")
        self.assertEqual(mongo_summary["records_upserted"], 1)
        self.assertEqual(target_db["material_records"].count_documents({}), 1)
        self.assertEqual(target_db["datasets"].count_documents({}), 16)
        self.assertIn(migration_script.MANIFEST_KEY, client.uploads)

    def test_persist_manifest_chunks_large_record_lists_for_mongo(self) -> None:
        client = FakeS3Client()
        target_db = FakeDatabase(
            {
                migration_script.TARGET_MIGRATION_MANIFESTS_COLLECTION: SizeLimitedCollection(max_json_bytes=4096),
                migration_script.TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION: SizeLimitedCollection(max_json_bytes=4096),
            }
        )
        sftp_records = [
            {
                "dataset_id": "md_allatom",
                "role": "raw_file",
                "status": "uploaded",
                "object_key": f"datasets/md_allatom/raw/C/{index:06d}/large-output-file-with-long-name.out",
                "remote": {"size_bytes": 1024 + index, "mtime": "2026-07-27T00:00:00+00:00"},
            }
            for index in range(200)
        ]
        manifest = migration_script.build_manifest(
            bucket="polymer-data",
            apply=True,
            minio_records=[],
            sftp_records=sftp_records,
            mongo_summary={"status": "skipped"},
            import_summaries=[],
        )

        with (
            patch.object(migration_script, "LOCAL_MANIFEST_PATH", Path("/tmp/poly-data-large-manifest-test.json")),
            patch.object(migration_script, "MONGO_MANIFEST_RECORD_CHUNK_BYTES", 1000),
        ):
            migration_script.persist_manifest(target_db=target_db, client=client, bucket="polymer-data", manifest=manifest)

        mongo_manifest = target_db[migration_script.TARGET_MIGRATION_MANIFESTS_COLLECTION].rows[0]
        self.assertNotIn("records", mongo_manifest["sftp"])
        self.assertEqual(mongo_manifest["sftp"]["record_count"], 200)
        self.assertEqual(mongo_manifest["sftp"]["status_counts"], {"uploaded": 200})
        self.assertGreater(mongo_manifest["sftp"]["record_chunk_count"], 1)
        self.assertGreater(target_db[migration_script.TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION].count_documents({}), 1)
        uploaded_manifest = migration_script.json.loads(client.uploads[migration_script.MANIFEST_KEY].decode("utf-8"))
        self.assertEqual(len(uploaded_manifest["sftp"]["records"]), 200)

    def test_sftp_dry_run_does_not_upload_objects(self) -> None:
        client = FakeS3Client()

        records = migration_script.migrate_sftp_open_database_objects(
            FakeSftpClient(),
            client,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            sftp_root="/remote",
            apply=False,
        )

        self.assertEqual(len(records), 32)
        self.assertTrue(all(record["status"] == "planned" for record in records))
        self.assertNotIn("datasets/smipoly/raw/202207_smip_monset.csv", client.uploads)

    def test_sftp_apply_uploads_and_verifies_canonical_objects(self) -> None:
        client = FakeS3Client()

        records = migration_script.migrate_sftp_open_database_objects(
            FakeSftpClient(),
            client,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            sftp_root="/remote",
            apply=True,
        )
        manifest = migration_script.build_manifest(
            bucket="polymer-data",
            apply=True,
            minio_records=[],
            sftp_records=records,
            mongo_summary={"status": "skipped"},
            import_summaries=[],
        )

        self.assertEqual(len(records), 32)
        self.assertEqual(
            sum(1 for record in records if record["status"] == "uploaded"),
            6,
        )
        self.assertEqual(
            sum(1 for record in records if record["status"] == "missing_source"),
            26,
        )
        self.assertIn("datasets/smipoly/raw/202207_smip_monset.csv", client.uploads)
        self.assertIn("datasets/polyuniverse/raw/epoxy_diE.csv", client.uploads)
        self.assertEqual(manifest["sftp"]["failed_count"], 26)

    def test_open_database_uploads_run_concurrently(self) -> None:
        state = ConcurrentReadState()
        records = migration_script.migrate_sftp_open_database_objects(
            FakeSftpClient(),
            FakeS3Client(),
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            sftp_root="/remote",
            dataset_ids=["smipoly", "polyuniverse"],
            apply=True,
            target_db=FakeDatabase(),
            upload_workers=4,
            upload_retries=0,
            sftp_client_factory=lambda: ConcurrentSftpClient(state),
        )

        self.assertEqual(len(records), 6)
        self.assertTrue(all(record["status"] == "uploaded" for record in records))
        self.assertGreater(state.max_active, 1)
        self.assertLessEqual(state.max_active, 4)

    def test_permanent_file_failure_does_not_block_other_uploads(self) -> None:
        target_db = FakeDatabase()
        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            SelectivelyFailingS3Client(),
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["C"],
            apply=True,
            upload_workers=2,
            upload_retries=0,
            sftp_client_factory=FakeSftpClient,
        )

        self.assertEqual({record["status"] for record in records}, {"failed", "uploaded"})
        self.assertEqual(target_db["md_allatom_files"].count_documents({}), 1)
        self.assertEqual(target_db["upload_checkpoints"].count_documents({"status": "failed"}), 1)
        job = target_db["upload_jobs"].rows[0]
        self.assertEqual(job["failed_files"], 1)
        self.assertEqual(job["completed_files"], 1)

    def test_worker_connection_failure_isolated_and_job_finishes(self) -> None:
        target_db = FakeDatabase()
        state = {"calls": 0}
        lock = threading.Lock()

        def factory():
            with lock:
                state["calls"] += 1
                if state["calls"] == 1:
                    raise OSError("simulated SFTP connection failure")
            return FakeSftpClient()

        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            FakeS3Client(),
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["C"],
            apply=True,
            upload_workers=2,
            upload_retries=0,
            sftp_client_factory=factory,
        )

        self.assertEqual(len(records), 2)
        self.assertEqual(sum(record["status"] == "failed" for record in records), 1)
        self.assertEqual(sum(record["status"] == "uploaded" for record in records), 1)
        self.assertEqual(target_db["upload_jobs"].rows[0]["status"], "failed")
        self.assertIn(
            ([('job_id', 1)], "job_id", True),
            target_db["upload_jobs"].indexes,
        )
        self.assertIn(
            ([('bucket', 1), ('object_key', 1)], "bucket_object_key", True),
            target_db["upload_checkpoints"].indexes,
        )

    def test_upload_failure_is_logged_immediately(self) -> None:
        output = StringIO()

        with redirect_stdout(output):
            migration_script.migrate_sftp_md_allatom_objects(
                FakeSftpClient(),
                SelectivelyFailingS3Client(),
                target_db=FakeDatabase(),
                bucket="polymer-data",
                sftp_host="10.26.15.53",
                md_root="/remote-md",
                families=["C"],
                apply=True,
                upload_workers=1,
                upload_retries=0,
            )

        self.assertIn("failed=1", output.getvalue())
        self.assertIn("polymer_1_1_32npt.data", output.getvalue())

    def test_md_allatom_upload_uses_bounded_parallel_workers_with_independent_sftp_clients(self) -> None:
        state = ConcurrentReadState()
        client = FakeS3Client()
        target_db = FakeDatabase()

        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            client,
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["C", "F", "Si"],
            apply=True,
            upload_workers=4,
            upload_retries=0,
            sftp_client_factory=lambda: ConcurrentSftpClient(state),
        )

        self.assertTrue(all(record["status"] == "uploaded" for record in records))
        self.assertGreater(state.max_active, 1)
        self.assertLessEqual(state.max_active, 4)
        self.assertLessEqual(state.created, 4)
        self.assertEqual(state.closed, state.created)

    def test_upload_retries_three_times_and_persists_checkpoint(self) -> None:
        client = TransientS3Client(failures=3)
        target_db = FakeDatabase()

        with patch.object(migration_script.time, "sleep", return_value=None):
            records = migration_script.migrate_sftp_md_allatom_objects(
                FakeSftpClient(),
                client,
                target_db=target_db,
                bucket="polymer-data",
                sftp_host="10.26.15.53",
                md_root="/remote-md",
                families=["F"],
                apply=True,
                upload_workers=1,
                upload_retries=3,
            )

        self.assertEqual(records[0]["status"], "uploaded")
        self.assertEqual(records[0]["attempts"], 4)
        self.assertEqual(client.attempts, 4)
        checkpoint = target_db["upload_checkpoints"].rows[0]
        self.assertEqual(checkpoint["status"], "uploaded")
        self.assertEqual(checkpoint["attempts"], 4)

    def test_existing_inventory_skips_upload_without_per_object_head(self) -> None:
        source = FakeSftpClient()
        key = "datasets/md_allatom/raw/F/polymer_2_1_32npt.data"
        client = InventoryOnlyS3Client(key, len(source.files["/remote-md/F/polymer_2_1_32npt.data"]))

        records = migration_script.migrate_sftp_md_allatom_objects(
            source,
            client,
            target_db=FakeDatabase(),
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["F"],
            apply=True,
            upload_workers=1,
            upload_retries=0,
        )

        self.assertEqual(records[0]["status"], "already_migrated")
        self.assertEqual(client.head_calls, 0)
        self.assertNotIn(key, client.uploads)

    def test_inventory_size_mismatch_is_reuploaded_and_verified(self) -> None:
        source = FakeSftpClient()
        key = "datasets/md_allatom/raw/F/polymer_2_1_32npt.data"
        client = InventoryOnlyS3Client(key, size_bytes=1)

        records = migration_script.migrate_sftp_md_allatom_objects(
            source,
            client,
            target_db=FakeDatabase(),
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["F"],
            apply=True,
            upload_workers=1,
            upload_retries=0,
        )

        self.assertEqual(records[0]["status"], "uploaded")
        self.assertEqual(client.head_calls, 1)
        self.assertIn(key, client.uploads)

    def test_md_allatom_indexes_each_file_before_the_batch_finishes(self) -> None:
        client = BlockingSecondUploadS3Client()
        target_db = FakeDatabase()
        outcome: list[dict] = []

        def run() -> None:
            outcome.extend(
                migration_script.migrate_sftp_md_allatom_objects(
                    FakeSftpClient(),
                    client,
                    target_db=target_db,
                    bucket="polymer-data",
                    sftp_host="10.26.15.53",
                    md_root="/remote-md",
                    families=["C"],
                    apply=True,
                    upload_workers=1,
                    upload_retries=0,
                )
            )

        thread = threading.Thread(target=run)
        thread.start()
        self.assertTrue(client.second_started.wait(timeout=2))
        self.assertEqual(target_db["md_allatom_files"].count_documents({}), 1)
        client.release_second.set()
        thread.join(timeout=5)

        self.assertFalse(thread.is_alive())
        self.assertEqual(len(outcome), 2)
        self.assertEqual(target_db["md_allatom_files"].count_documents({}), 2)

    def test_multipart_upload_aborts_when_chunk_stream_is_cancelled(self) -> None:
        client = MultipartProbeClient()

        def chunks():
            yield b"first"
            raise migration_script.MigrationCancelled("cancelled")

        with self.assertRaises(migration_script.MigrationCancelled):
            client.put_object_multipart(
                "polymer-data",
                "datasets/md_allatom/raw/C/large.data",
                chunks(),
                content_type="application/octet-stream",
                part_size=4,
            )

        self.assertTrue(client.aborted)

    def test_cancelled_upload_skips_checkpoint_and_job_persistence(self) -> None:
        target_db = FakeDatabase()
        record = {
            "dataset_id": "md_allatom",
            "role": "raw_file",
            "family": "C",
            "remote_path": "/remote-md/C/polymer_1_1_32npt.data",
            "object_key": "datasets/md_allatom/raw/C/polymer_1_1_32npt.data",
            "bucket": "polymer-data",
            "remote": {"size_bytes": 11},
            "target": None,
            "target_exists": False,
            "status": "planned",
            "error": None,
            "content_type": "application/octet-stream",
        }

        with (
            patch.object(migration_script, "_upload_one_record", side_effect=migration_script.MigrationCancelled("cancelled")),
            patch.object(migration_script, "_persist_upload_checkpoint", side_effect=AssertionError("checkpoint write must be skipped")),
            patch.object(migration_script, "_persist_dataset_object", side_effect=AssertionError("dataset write must be skipped")),
            patch.object(migration_script, "_update_upload_job", side_effect=AssertionError("job write must be skipped")),
            patch.object(migration_script, "_finish_upload_job", side_effect=AssertionError("finish write must be skipped")),
        ):
            records = migration_script.upload_records_concurrently(
                [record],
                sftp_client=FakeSftpClient(),
                sftp_client_factory=None,
                s3_client=FakeS3Client(),
                target_db=target_db,
                bucket="polymer-data",
                job_type="md-allatom",
                upload_workers=1,
                upload_retries=0,
                target_inventory=None,
                cancel_event=threading.Event(),
            )

        self.assertEqual(records[0]["status"], "cancelled")
        self.assertEqual(target_db["upload_checkpoints"].count_documents({}), 0)

    def test_apply_sftp_migration_requires_credentials_before_connecting(self) -> None:
        args = migration_script.parse_args(["--apply", "--migrate-sftp-md-allatom"])

        with self.assertRaises(migration_script.MigrationConfigurationError):
            migration_script.validate_runtime_configuration(args, sftp_password="")

    def test_row_import_defaults_to_full_mode(self) -> None:
        args = migration_script.parse_args([])

        self.assertIsNone(args.pi1m_sample_size)
        self.assertIsNone(args.extra_sample_size)

    def test_apply_can_drop_source_after_count_verification(self) -> None:
        source_collection = FakeCollection([{"polymer_record_id": "OPENPOLY-1"}])
        source_db = FakeDatabase({"Poly_Agent": source_collection})
        target_db = FakeDatabase()

        summary = migration_script.migrate_mongo_assets(
            source_db=source_db,
            target_db=target_db,
            object_records=[],
            apply=True,
            drop_source_after_verify=True,
        )

        self.assertEqual(summary["status"], "verified")
        self.assertTrue(summary["source_dropped"])
        self.assertTrue(source_collection.dropped)

    def test_radonpy_import_maps_excel_rows_and_is_idempotent(self) -> None:
        import pandas as pd

        target_db = FakeDatabase()
        dataframe = pd.DataFrame(
            [
                {
                    "smiles": "*CC*",
                    "density": 0.837971504,
                    "static_dielectric_const": 2.2102,
                    "thermal_conductivity": 0.2361,
                }
            ]
        )

        with patch("pandas.read_excel", return_value=dataframe):
            first = migration_script.import_radonpy_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )
            second = migration_script.import_radonpy_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )

        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["records_upserted"], 1)
        self.assertEqual(target_db["radonpy_records"].count_documents({}), 1)
        row = target_db["radonpy_records"].rows[0]
        self.assertEqual(row["radonpy_record_id"], "RADONPY_PI1070-000001")
        self.assertEqual(row["smiles"], "*CC*")
        self.assertEqual(row["properties"]["thermal_conductivity"], 0.2361)
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "radonpy_pi1070")
        self.assertEqual(dataset["record_collection_key"], "poly_data.radonpy_records")
        self.assertEqual(dataset["record_mode"], "full")

    def test_pi1m_import_streams_chunks_and_marks_full_import(self) -> None:
        import pandas as pd

        target_db = FakeDatabase(
            {"pi1m_samples": FakeCollection([{"pi1m_record_id": "PI1M-STALE", "row_index": 99}])}
        )
        chunks = [
            pd.DataFrame([{"SMILES": "*CC*", "SA Score": 3.1}, {"SMILES": "*CCC*", "SA Score": 4.2}]),
            pd.DataFrame([{"SMILES": "*CCCC*", "SA Score": 5.3}]),
        ]

        with patch("pandas.read_csv", return_value=iter(chunks)):
            first = migration_script.import_pi1m_samples(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                sample_size=None,
                chunk_size=2,
                apply=True,
            )
        with patch("pandas.read_csv", return_value=iter(chunks)):
            second = migration_script.import_pi1m_samples(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                sample_size=None,
                chunk_size=2,
                apply=True,
            )

        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["records_upserted"], 3)
        self.assertEqual(target_db["pi1m_samples"].count_documents({}), 3)
        self.assertEqual(target_db["pi1m_samples"].bulk_batches, [2, 1])
        self.assertNotIn("PI1M-STALE", {row["pi1m_record_id"] for row in target_db["pi1m_samples"].rows})
        self.assertEqual(target_db["pi1m_samples"].rows[0]["pi1m_record_id"], "PI1M_V2-000001")
        self.assertEqual(target_db["pi1m_samples"].rows[0]["sa_score"], 3.1)
        self.assertEqual(target_db["pi1m_samples"].rows[0]["row_index"], 1)
        self.assertNotIn("raw", target_db["pi1m_samples"].rows[0])
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "pi1m_v2")
        self.assertEqual(dataset["record_count"], 3)
        self.assertEqual(dataset["record_mode"], "full")
        self.assertEqual(dataset["verification_status"], "verified")
        self.assertEqual(dataset["row_count"], 3)
        self.assertEqual(target_db["dataset_stats"].rows[0]["dataset_id"], "pi1m_v2")
        self.assertEqual(target_db["import_checkpoints"].rows[-1]["status"], "completed")
        self.assertFalse(any(name.startswith("__staging_") for name in target_db.collections))

    def test_pi1m_source_change_keeps_canonical_collection_untouched(self) -> None:
        import pandas as pd

        client = ChangingHeadS3Client("datasets/pi1m_v2/raw/pi1m_v2.csv")
        target_db = FakeDatabase(
            {"pi1m_samples": FakeCollection([{"pi1m_record_id": "PI1M-CANONICAL", "row_index": 1}])}
        )
        chunks = [pd.DataFrame([{"SMILES": "*CC*", "SA Score": 3.1}])]

        with patch("pandas.read_csv", return_value=iter(chunks)):
            summary = migration_script.import_pi1m_samples(
                target_db,
                s3_client=client,
                bucket="polymer-data",
                sample_size=None,
                chunk_size=2,
                apply=True,
            )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(target_db["pi1m_samples"].count_documents({}), 1)
        self.assertEqual(target_db["pi1m_samples"].rows[0]["pi1m_record_id"], "PI1M-CANONICAL")
        self.assertTrue(any(name.startswith("__staging_pi1m_v2_") for name in target_db.collections))

    def test_smipoly_import_maps_csv_rows_and_is_idempotent(self) -> None:
        import pandas as pd

        target_db = FakeDatabase()
        dataframe = pd.DataFrame(
            [
                {
                    "comID": "CID174",
                    "MolecularFormula": "C2H6O2",
                    "MolecularWeight": 62.07,
                    "SMILES": "C(CO)O",
                    "IUPACName": "ethane-1,2-diol",
                }
            ]
        )

        with patch("pandas.read_csv", return_value=dataframe):
            first = migration_script.import_smipoly_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )
            second = migration_script.import_smipoly_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )

        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["records_upserted"], 1)
        self.assertEqual(target_db["smipoly_monomers"].count_documents({}), 1)
        row = target_db["smipoly_monomers"].rows[0]
        self.assertEqual(row["smipoly_record_id"], "SMIPOLY-000001")
        self.assertEqual(row["molecular_formula"], "C2H6O2")
        self.assertEqual(row["smiles"], "C(CO)O")
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "smipoly")
        self.assertEqual(dataset["record_collection_key"], "poly_data.smipoly_monomers")
        self.assertEqual(dataset["record_mode"], "full")

    def test_polyuniverse_import_maps_all_csv_rows_and_keeps_duplicates(self) -> None:
        import pandas as pd

        target_db = FakeDatabase()
        frames = [
            pd.DataFrame([{"Smiles": "CC(O)=O"}]),
            pd.DataFrame([{"Smiles": "C1OC1"}, {"Smiles": "C1OC1"}]),
            pd.DataFrame([{"Smiles": "CN"}]),
        ]

        with patch("pandas.read_csv", side_effect=[*frames, *frames]):
            first = migration_script.import_polyuniverse_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )
            second = migration_script.import_polyuniverse_records(
                target_db,
                s3_client=FakeS3Client(),
                bucket="polymer-data",
                apply=True,
            )

        self.assertEqual(first["status"], "imported")
        self.assertEqual(second["records_upserted"], 4)
        self.assertEqual(target_db["polyuniverse_monomers"].count_documents({}), 4)
        rows = target_db["polyuniverse_monomers"].rows
        self.assertEqual(rows[0]["polyuniverse_record_id"], "POLYUNIVERSE-diCOOH-000001")
        self.assertEqual(rows[0]["monomer_class"], "dicarboxylic_acid")
        self.assertEqual(rows[1]["polyuniverse_record_id"], "POLYUNIVERSE-epoxy_diE-000001")
        self.assertEqual(rows[2]["polyuniverse_record_id"], "POLYUNIVERSE-epoxy_diE-000002")
        self.assertEqual(rows[1]["smiles"], rows[2]["smiles"])
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "polyuniverse")
        self.assertEqual(dataset["record_collection_key"], "poly_data.polyuniverse_monomers")
        self.assertEqual(dataset["record_mode"], "full")

    def test_extra_open_database_import_maps_generic_table_rows_and_stats(self) -> None:
        client = FakeS3Client()
        client.put_object(
            "polymer-data",
            "datasets/nanomine/raw/data.tsv",
            b"date\tNew York\tSan Francisco\tAustin\n2026-01-01\t1\t2\t3\n2026-01-02\t4\t5\t6\n",
            "text/tab-separated-values; charset=utf-8",
        )
        target_db = FakeDatabase(
            {
                "nanomine_records": FakeCollection(
                    [{"record_id": "NANOMINE-STALE", "title": "stale row"}]
                )
            }
        )

        summaries = migration_script.import_extra_open_database_records(
            target_db,
            s3_client=client,
            bucket="polymer-data",
            dataset_ids=["nanomine"],
            sample_size=None,
            apply=True,
        )

        self.assertEqual(summaries[0]["status"], "imported")
        self.assertEqual(summaries[0]["records_upserted"], 2)
        self.assertEqual(target_db["nanomine_records"].count_documents({}), 2)
        self.assertNotIn("NANOMINE-STALE", {item["record_id"] for item in target_db["nanomine_records"].rows})
        row = target_db["nanomine_records"].rows[0]
        self.assertEqual(row["record_id"], "NANOMINE-00000001")
        self.assertEqual(row["title"], "2026-01-01")
        self.assertEqual(row["source_file"], "data.tsv")
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "nanomine")
        self.assertEqual(dataset["record_collection_key"], "poly_data.nanomine_records")
        self.assertEqual(dataset["row_count"], 2)
        self.assertEqual(dataset["record_count"], 2)
        self.assertEqual(dataset["record_mode"], "full")
        self.assertEqual(dataset["verification_status"], "verified")
        self.assertEqual(dataset["source_objects"][0]["object_key"], "datasets/nanomine/raw/data.tsv")
        stats = target_db["dataset_stats"].rows[0]
        self.assertEqual(stats["dataset_id"], "nanomine")
        self.assertEqual(stats["record_count"], 2)
        self.assertEqual(stats["category_counts"]["source_file"]["data.tsv"], 2)
        self.assertEqual(stats["sampling"]["analysis_sample_count"], 2)
        self.assertFalse(any(name.startswith("__staging_") for name in target_db.collections))

    def test_extra_open_database_import_resumes_completed_staging_chunks(self) -> None:
        import pandas as pd

        client = FakeS3Client()
        object_key = "datasets/nanomine/raw/data.tsv"
        client.put_object(
            "polymer-data",
            object_key,
            b"date\tNew York\tSan Francisco\tAustin\n2026-01-01\t1\t2\t3\n2026-01-02\t4\t5\t6\n",
            "text/tab-separated-values; charset=utf-8",
        )
        job_id = "nanomine-resume-job"
        staging_name = migration_script.staging_collection_name("nanomine", job_id)
        first_document = migration_script.build_extra_dataset_documents(
            pd.DataFrame([{"date": "2026-01-01", "New York": 1, "San Francisco": 2, "Austin": 3}]),
            dataset_spec=next(spec for spec in migration_script.EXTRA_DATASET_SPECS if spec.dataset_id == "nanomine"),
            file_spec=next(
                file_spec
                for spec in migration_script.EXTRA_DATASET_SPECS
                if spec.dataset_id == "nanomine"
                for file_spec in spec.files
                if file_spec.importable
            ),
        )[0]
        source_objects = migration_script.source_object_snapshots(client, "polymer-data", [object_key])
        target_db = FakeDatabase(
            {
                staging_name: FakeCollection([first_document]),
                "import_jobs": FakeCollection(
                    [{"job_id": job_id, "dataset_id": "nanomine", "source_objects": source_objects, "status": "failed"}]
                ),
                "import_checkpoints": FakeCollection(
                    [
                        {
                            "job_id": job_id,
                            "dataset_id": "nanomine",
                            "source_file": "data.tsv",
                            "chunk_index": 1,
                            "row_start": 1,
                            "row_end": 1,
                            "records": 1,
                            "status": "completed",
                        }
                    ]
                ),
            }
        )
        frames = [
            pd.DataFrame([{"date": "2026-01-01", "New York": 1, "San Francisco": 2, "Austin": 3}]),
            pd.DataFrame([{"date": "2026-01-02", "New York": 4, "San Francisco": 5, "Austin": 6}]),
        ]

        with patch.object(migration_script, "iter_extra_dataset_frames", return_value=iter(frames)):
            summaries = migration_script.import_extra_open_database_records(
                target_db,
                s3_client=client,
                bucket="polymer-data",
                dataset_ids=["nanomine"],
                sample_size=None,
                apply=True,
                resume_job_id=job_id,
            )

        self.assertEqual(summaries[0]["status"], "imported")
        self.assertEqual(target_db["nanomine_records"].count_documents({}), 2)
        self.assertEqual(target_db["nanomine_records"].bulk_batches, [1])

    def test_md_allatom_sftp_apply_uploads_recursive_files_and_indexes_mongo(self) -> None:
        client = FakeS3Client()
        target_db = FakeDatabase()

        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            client,
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["C", "F", "Si"],
            apply=True,
        )

        self.assertEqual(len(records), 4)
        self.assertTrue(all(record["status"] == "uploaded" for record in records))
        self.assertIn("datasets/md_allatom/raw/C/polymer_1_1_32npt.data", client.uploads)
        self.assertIn("datasets/md_allatom/raw/C/results/250_1_1_32_.out", client.uploads)
        self.assertIn("datasets/md_allatom/manifests/C.json", client.uploads)
        self.assertEqual(target_db["md_allatom_files"].count_documents({}), 4)
        row = target_db["md_allatom_files"].rows[0]
        self.assertEqual(row["family"], "C")
        self.assertEqual(row["object_key"], "datasets/md_allatom/raw/C/polymer_1_1_32npt.data")
        manifest = migration_script.json.loads(
            client.uploads["datasets/md_allatom/manifests/C.json"].decode("utf-8")
        )
        self.assertEqual(manifest["sync_status"], "verified")
        self.assertTrue(manifest["counts_consistent"])
        self.assertEqual(manifest["file_count"], 2)
        self.assertEqual(manifest["remote_file_count"], 2)
        self.assertEqual(manifest["minio_object_count"], 2)
        self.assertEqual(manifest["mongo_index_count"], 2)

        repeated = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            client,
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["C", "F", "Si"],
            apply=True,
        )
        self.assertTrue(all(record["status"] == "already_migrated" for record in repeated))
        self.assertEqual(target_db["md_allatom_files"].count_documents({}), 4)

    def test_md_allatom_missing_and_empty_families_do_not_create_success_manifests(self) -> None:
        client = FakeS3Client()

        records = migration_script.migrate_sftp_md_allatom_objects(
            MissingAndEmptySftpClient(),
            client,
            target_db=FakeDatabase(),
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["F", "Si"],
            apply=True,
        )

        by_family = {record["family"]: record for record in records}
        self.assertEqual(by_family["F"]["status"], "empty_source")
        self.assertEqual(by_family["Si"]["status"], "missing_source")
        self.assertNotIn("datasets/md_allatom/manifests/F.json", client.uploads)
        self.assertNotIn("datasets/md_allatom/manifests/Si.json", client.uploads)

    def test_md_allatom_partial_failure_is_recorded_in_family_manifest(self) -> None:
        client = PartiallyFailingS3Client()
        target_db = FakeDatabase()

        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            client,
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["F"],
            apply=True,
            upload_retries=0,
        )

        self.assertEqual(records[0]["status"], "failed")
        manifest = migration_script.json.loads(
            client.uploads["datasets/md_allatom/manifests/F.json"].decode("utf-8")
        )
        self.assertEqual(manifest["sync_status"], "partial_failure")
        self.assertEqual(manifest["remote_file_count"], 1)
        self.assertEqual(manifest["minio_object_count"], 0)
        self.assertEqual(manifest["mongo_index_count"], 0)
        self.assertFalse(manifest["counts_consistent"])

    def test_md_allatom_stale_mongo_index_prevents_verified_manifest(self) -> None:
        client = FakeS3Client()
        target_db = FakeDatabase(
            {
                "md_allatom_files": FakeCollection(
                    [{"md_allatom_file_id": "stale", "family": "F"}]
                )
            }
        )

        records = migration_script.migrate_sftp_md_allatom_objects(
            FakeSftpClient(),
            client,
            target_db=target_db,
            bucket="polymer-data",
            sftp_host="10.26.15.53",
            md_root="/remote-md",
            families=["F"],
            apply=True,
        )

        self.assertEqual(records[0]["status"], "uploaded")
        manifest = migration_script.json.loads(
            client.uploads["datasets/md_allatom/manifests/F.json"].decode("utf-8")
        )
        self.assertEqual(manifest["sync_status"], "partial_failure")
        self.assertFalse(manifest["counts_consistent"])
        self.assertEqual(manifest["remote_file_count"], 1)
        self.assertEqual(manifest["minio_object_count"], 1)
        self.assertEqual(manifest["mongo_index_count"], 2)

    def test_md_allatom_structured_import_uploads_csvs_and_preserves_duplicate_natural_keys(self) -> None:
        target_db = FakeDatabase(
            {
                "md_allatom_diamines": FakeCollection([{"md_allatom_diamine_id": "STALE-DIAMINE"}]),
                "md_allatom_dianhydrides": FakeCollection([{"md_allatom_dianhydride_id": "STALE-DIANHYDRIDE"}]),
                "md_allatom_carbon_results": FakeCollection([{"md_allatom_carbon_result_id": "STALE-CARBON"}]),
            }
        )
        client = FakeS3Client()

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "二胺.csv").write_text(
                "\ufeffdiamine_id,diamine_cas,diamine_name,diamine_name_cn,diamine_abbr,diamine_SMILES\n"
                "1,341-58-2,TFDB,二胺,TFDB,CN\n",
                encoding="utf-8",
            )
            (root / "二酐.csv").write_text(
                "\ufeffdianhydride_id,dianhydride_cas,dianhydride_name,dianhydride_name_cn,dianhydride_abbr,dianhydride_SMILES\n"
                "1,1107-00-2,6FDA,六氟二酐,6FDA,O=C1OC(=O)c2ccccc12\n",
                encoding="utf-8",
            )
            (root / "碳基.csv").write_text(
                "diamine_id,dianhydride_id,dp,temperature,monomer_len,contour_len,e2e_mean,e2e_std,rg_mean,rg_std,persist_len_mean,persist_len_std,data_file,out_file\n"
                "1,1,32,250,21.452,689.06,369.37,0.9674,143.78,0.3926,114.87,4.7822,polymer_1_1_32npt.data,250_1_1_32_.out\n"
                "1,1,32,250,21.452,689.06,370.00,0.9000,144.00,0.4000,115.00,4.7000,polymer_1_1_32npt.data,250_1_1_32_.out\n",
                encoding="utf-8",
            )
            doc = root / "requirements.docx"
            doc.write_bytes(b"docx")

            summary = migration_script.import_md_allatom_structured_records(
                target_db,
                s3_client=client,
                bucket="polymer-data",
                structured_data_root=root,
                requirements_doc=doc,
                apply=True,
            )

        self.assertEqual(summary["status"], "imported")
        self.assertEqual(summary["diamine_records_upserted"], 1)
        self.assertEqual(summary["dianhydride_records_upserted"], 1)
        self.assertEqual(summary["carbon_records_upserted"], 2)
        self.assertEqual(target_db["md_allatom_carbon_results"].count_documents({}), 2)
        self.assertEqual(target_db["md_allatom_diamines"].count_documents({}), 1)
        self.assertEqual(target_db["md_allatom_dianhydrides"].count_documents({}), 1)
        self.assertEqual(
            [row["md_allatom_carbon_result_id"] for row in target_db["md_allatom_carbon_results"].rows],
            ["MDALLATOM-C-000001", "MDALLATOM-C-000002"],
        )
        self.assertIn("datasets/md_allatom/structured/diamine.csv", client.uploads)
        stats = target_db["dataset_stats"].rows[0]
        self.assertEqual(stats["dataset_id"], "md_allatom")
        self.assertEqual(stats["category_counts"]["temperature"]["250"], 2)
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["row_count"], 2)
        self.assertEqual(dataset["record_count"], 2)
        self.assertEqual(dataset["verification_status"], "verified")
        self.assertFalse(any(name.startswith("__staging_md_allatom_") for name in target_db.collections))

    def test_load_md_allatom_file_documents_uses_find_for_pymongo_like_collection(self) -> None:
        collection = PyMongoLikeCollection()
        target_db = FakeDatabase({"md_allatom_files": collection})

        rows = migration_script.load_md_allatom_file_documents(target_db)

        self.assertTrue(collection.find_called)
        self.assertEqual(rows[0]["md_allatom_file_id"], "MDALLATOM-FILE-C-000001")
