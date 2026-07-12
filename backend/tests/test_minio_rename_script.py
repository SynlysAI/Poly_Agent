"""MinIO rename script tests."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "rename_minio_poly_agent_objects.py"
SPEC = importlib.util.spec_from_file_location("rename_minio_poly_agent_objects", SCRIPT_PATH)
assert SPEC and SPEC.loader
rename_script = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = rename_script
SPEC.loader.exec_module(rename_script)


class FakeRenameClient:
    """In-memory object client for rename tests."""

    def __init__(self) -> None:
        self.objects = {
            "01_RadonPy/01_RadonPy_README(1).md": {"size_bytes": 10, "etag": "a"},
            "poly_agent/datasets/pi1m_v2/raw/pi1m_v2.csv": {"size_bytes": 20, "etag": "b"},
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


class MinioRenameScriptTest(unittest.TestCase):
    """Test dry-run and apply behavior without network I/O."""

    def test_dry_run_does_not_mutate_objects(self) -> None:
        client = FakeRenameClient()

        manifest = rename_script.execute_rename(client, bucket="polymer-data", apply=False)

        self.assertFalse(manifest["applied"])
        self.assertIn("01_RadonPy/01_RadonPy_README(1).md", client.objects)
        self.assertEqual(client.deleted, [])
        self.assertEqual(client.uploads, {})

    def test_apply_copies_verifies_deletes_and_uploads_manifest(self) -> None:
        client = FakeRenameClient()
        with patch.object(rename_script, "LOCAL_MANIFEST_PATH", Path("/tmp/poly-agent-test-manifest.json")):
            manifest = rename_script.execute_rename(client, bucket="polymer-data", apply=True)

        readme_record = next(
            record
            for record in manifest["records"]
            if record["legacy_key"] == "01_RadonPy/01_RadonPy_README(1).md"
        )
        already_record = next(
            record
            for record in manifest["records"]
            if record["canonical_key"] == "poly_agent/datasets/pi1m_v2/raw/pi1m_v2.csv"
        )

        self.assertTrue(manifest["applied"])
        self.assertEqual(readme_record["status"], "renamed")
        self.assertEqual(already_record["status"], "already_migrated")
        self.assertIn("poly_agent/datasets/radonpy_pi1070/docs/readme.md", client.objects)
        self.assertIn("01_RadonPy/01_RadonPy_README(1).md", client.deleted)
        self.assertIn(rename_script.MANIFEST_KEY, client.uploads)
