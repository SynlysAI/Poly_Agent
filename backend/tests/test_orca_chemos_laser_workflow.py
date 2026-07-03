"""Local ORCA workflow coverage."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from app.core.config import settings
from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService
from app.workers.computation_worker import ComputationWorker

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase


class OrcaChemosLaserWorkflowTest(ComputationTestCase):
    """Validate real local ORCA workflow boundaries."""

    def setUp(self) -> None:
        super().setUp()
        self.original_orca_mode = settings.orca_execution_mode
        self.original_orca_license = settings.orca_license_available
        self.service = ComputationService()

    def tearDown(self) -> None:
        settings.orca_execution_mode = self.original_orca_mode
        settings.orca_chemos_execution_mode = self.original_orca_mode
        settings.orca_license_available = self.original_orca_license
        super().tearDown()

    def test_orca_request_rejects_shell_command_and_local_path_parameters(self) -> None:
        with self.assertRaises(ValidationError):
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "/tmp/run_orca.sh"},
            )

        with self.assertRaises(ValidationError):
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP", "shell_command": "orca input.inp"},
            )

    def test_orca_unconfigured_failure_is_explicit(self) -> None:
        settings.orca_execution_mode = "disabled"
        settings.orca_chemos_execution_mode = "disabled"
        created = self._create_orca_run("req-orca-disabled")

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "ORCA_WORKFLOW_NOT_CONFIGURED")
        self.assertIn("ORCA workflow 未配置", detail.error["message"])
        self.assertEqual(detail.steps[0].status, "failed")

    def test_orca_license_missing_fails_closed(self) -> None:
        settings.orca_execution_mode = "local"
        settings.orca_chemos_execution_mode = "local"
        settings.orca_license_available = False
        created = self._create_orca_run("req-orca-license")

        result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        detail = self.service.get_run(created.run_id)

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "ORCA_LICENSE_UNAVAILABLE")
        self.assertTrue(detail.error["retryable"])

    def test_orca_local_success_registers_inputs_logs_and_result(self) -> None:
        settings.orca_execution_mode = "local"
        settings.orca_chemos_execution_mode = "local"
        settings.orca_license_available = True
        fake_bin = self._prepare_fake_toolchain()
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self._create_orca_run("req-orca-local-success")
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                result = ComputationWorker(worker_id="worker-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        artifact_names = {artifact.name for artifact in artifacts}

        self.assertEqual(result.status, "completed")
        self.assertEqual(detail.result_summary["energy_hartree"], -76.123456)
        self.assertTrue(detail.result_summary["normal_termination"])
        self.assertTrue(detail.result_summary["crest_used"])
        self.assertIn("workflow_config.json", artifact_names)
        self.assertIn("crest_best.xyz", artifact_names)
        self.assertIn("orca.inp", artifact_names)
        self.assertIn("orca.stdout.log", artifact_names)
        self.assertIn("result.json", artifact_names)

    def _create_orca_run(self, request_id: str):
        return self.service.create_run(
            ComputationCreateRequest(
                workflow_type="ORCA_CHEMOS_LASER",
                engine="ORCA",
                molecule={"smiles": "CCO", "name": "orca-test"},
                parameters={"method": "ORCA_B3LYP_DEF2_SVP"},
            ),
            actor_user_id="tester",
            request_id=request_id,
        )

    def _prepare_fake_toolchain(self) -> Path:
        fake_bin = self.runtime_root / "orca-bin"
        fake_bin.mkdir()
        self._write_fake_obabel(fake_bin / "obabel")
        self._write_fake_xtb(fake_bin / "xtb")
        self._write_fake_crest(fake_bin / "crest")
        self._write_fake_orca(fake_bin / "orca")
        return fake_bin

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
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_fake_crest(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
from pathlib import Path
Path("crest_best.xyz").write_text("2\\nfake crest best\\nC 0.0 0.0 0.0\\nO 1.1 0.0 0.0\\n", encoding="utf-8")
print("crest ok")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_fake_xtb(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
print("xtb version 6.6.1")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_fake_orca(self, path: Path) -> None:
        path.write_text(
            """#!/usr/bin/env python3
print("FINAL SINGLE POINT ENERGY     -76.123456")
print("ORCA TERMINATED NORMALLY")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)
