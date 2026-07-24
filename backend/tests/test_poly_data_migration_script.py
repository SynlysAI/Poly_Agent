"""Poly Data migration script tests."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from io import BytesIO
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
            "datasets/pi1m_v2/raw/pi1m_v2.csv": {"size_bytes": 20, "etag": "b"},
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
        return [dict(row) for row in self.rows]

    def update_one(self, filters: dict, update: dict, upsert: bool = False) -> None:
        payload = dict(update.get("$set", {}))
        for row in self.rows:
            if all(row.get(key) == value for key, value in filters.items()):
                row.update(payload)
                return
        if upsert:
            self.rows.append({**filters, **payload})

    def bulk_write(self, operations, ordered: bool = False):
        self.bulk_batches.append(len(operations))
        for operation in operations:
            self.update_one(operation._filter, operation._doc, upsert=operation._upsert)

        class Result:
            upserted_count = 0
            modified_count = len(operations)
            matched_count = len(operations)

        return Result()

    def create_index(self, keys, name: str, unique: bool = False) -> None:
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


class FakeDatabase:
    """Collection factory fake."""

    def __init__(self, collections: dict[str, FakeCollection] | None = None) -> None:
        self.collections = collections or {}

    def __getitem__(self, name: str) -> FakeCollection:
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


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
        self.assertEqual(target_db["datasets"].count_documents({}), 6)
        self.assertIn(migration_script.MANIFEST_KEY, client.uploads)

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

        self.assertEqual(len(records), 6)
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

        self.assertEqual(len(records), 6)
        self.assertTrue(all(record["status"] == "uploaded" for record in records))
        self.assertIn("datasets/smipoly/raw/202207_smip_monset.csv", client.uploads)
        self.assertIn("datasets/polyuniverse/raw/epoxy_diE.csv", client.uploads)
        self.assertEqual(manifest["sftp"]["failed_count"], 0)

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

        target_db = FakeDatabase()
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
        self.assertEqual(target_db["pi1m_samples"].bulk_batches, [2, 1, 2, 1])
        self.assertEqual(target_db["pi1m_samples"].rows[0]["pi1m_record_id"], "PI1M_V2-000001")
        self.assertEqual(target_db["pi1m_samples"].rows[0]["sa_score"], 3.1)
        self.assertEqual(target_db["pi1m_samples"].rows[0]["row_index"], 1)
        self.assertNotIn("raw", target_db["pi1m_samples"].rows[0])
        dataset = target_db["datasets"].rows[0]
        self.assertEqual(dataset["dataset_id"], "pi1m_v2")
        self.assertEqual(dataset["record_count"], 3)
        self.assertEqual(dataset["record_mode"], "full")
        self.assertEqual(target_db["dataset_stats"].rows[0]["dataset_id"], "pi1m_v2")
        self.assertEqual(target_db["import_checkpoints"].rows[-1]["status"], "completed")

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
        self.assertEqual(row["smipoly_record_id"], "SMIPOLY-CID174")
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

    def test_md_allatom_structured_import_uploads_csvs_and_preserves_duplicate_natural_keys(self) -> None:
        target_db = FakeDatabase()
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
        self.assertEqual(
            [row["md_allatom_carbon_result_id"] for row in target_db["md_allatom_carbon_results"].rows],
            ["MDALLATOM-C-000001", "MDALLATOM-C-000002"],
        )
        self.assertIn("datasets/md_allatom/structured/diamine.csv", client.uploads)
        stats = target_db["dataset_stats"].rows[0]
        self.assertEqual(stats["dataset_id"], "md_allatom")
        self.assertEqual(stats["category_counts"]["temperature"]["250"], 2)

    def test_load_md_allatom_file_documents_uses_find_for_pymongo_like_collection(self) -> None:
        collection = PyMongoLikeCollection()
        target_db = FakeDatabase({"md_allatom_files": collection})

        rows = migration_script.load_md_allatom_file_documents(target_db)

        self.assertTrue(collection.find_called)
        self.assertEqual(rows[0]["md_allatom_file_id"], "MDALLATOM-FILE-C-000001")
