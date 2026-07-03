"""Local structure adapter coverage."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
    from ._computation_test_utils import computation_payload
except ImportError:
    from _computation_test_utils import ComputationTestCase
    from _computation_test_utils import computation_payload


class LocalStructureAdapterTest(ComputationTestCase):
    """Cover LOCAL_STRUCTURE success and dependency failure paths."""

    def setUp(self) -> None:
        super().setUp()
        self.service = ComputationService()

    def test_local_structure_fails_with_error_artifact_when_dependencies_missing(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(
                **computation_payload(workflow_type="LOCAL_STRUCTURE", engine="LOCAL")
            ),
            actor_user_id="tester",
            request_id="req-local-structure-missing",
        )

        with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False), patch(
            "app.computation_adapters.local_structure.shutil.which",
            return_value=None,
        ):
            result = ComputationWorker(worker_id="worker-local-test").acquire_and_run_one()

        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        artifact_types = {artifact.artifact_type for artifact in artifacts}

        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "LOCAL_STRUCTURE_DEPENDENCY_MISSING")
        self.assertTrue(detail.error["retryable"])
        self.assertIn("error_json", artifact_types)
        self.assertIn("log_text", artifact_types)

    def test_local_structure_generates_artifacts_with_openbabel_cli(self) -> None:
        fake_bin = self.runtime_root / "bin"
        fake_bin.mkdir()
        fake_obabel = fake_bin / "obabel"
        self._write_fake_obabel(fake_obabel)
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(
                    **computation_payload(workflow_type="LOCAL_STRUCTURE", engine="LOCAL")
                ),
                actor_user_id="tester",
                request_id="req-local-structure-success",
            )
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                result = ComputationWorker(worker_id="worker-local-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        artifact_types = {artifact.artifact_type for artifact in artifacts}
        structure_artifact = next(artifact for artifact in artifacts if artifact.artifact_type == "structure_json")
        structure = self.service.get_artifact_structure(structure_artifact.artifact_id).structure

        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "completed")
        self.assertEqual(detail.status, "completed")
        self.assertIn("input_json", artifact_types)
        self.assertIn("structure_json", artifact_types)
        self.assertIn("xyz", artifact_types)
        self.assertIn("sdf", artifact_types)
        self.assertEqual(structure["source"], "openbabel")
        self.assertGreaterEqual(len(structure["atoms"]), 2)

    def _write_fake_obabel(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
import sys
from pathlib import Path

out = Path(sys.argv[sys.argv.index("-O") + 1])
if out.suffix == ".xyz":
    out.write_text("2\\nfake openbabel\\nC 0.0 0.0 0.0\\nO 1.2 0.0 0.0\\n", encoding="utf-8")
elif out.suffix == ".sdf":
    out.write_text("fake sdf\\n  OpenBabel\\n\\nM  END\\n$$$$\\n", encoding="utf-8")
else:
    out.write_text("", encoding="utf-8")
sys.stdout.write("fake obabel ok\\n")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

