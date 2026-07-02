"""Local xTB adapter coverage."""

from __future__ import annotations

import os
import subprocess
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


class LocalXtbAdapterTest(ComputationTestCase):
    """Cover LOCAL_XTB success, missing dependency, failure, and timeout paths."""

    def setUp(self) -> None:
        super().setUp()
        self.service = ComputationService()

    def test_local_xtb_missing_dependency_fails_with_retryable_error(self) -> None:
        created = self.service.create_run(
            ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
            actor_user_id="tester",
            request_id="req-xtb-missing",
        )

        with patch("app.computation_adapters.local_xtb.shutil.which", return_value=None):
            result = ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()

        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "XTB_NOT_AVAILABLE")
        self.assertTrue(detail.error["retryable"])
        self.assertIn("error_json", {artifact.artifact_type for artifact in artifacts})

    def test_local_xtb_success_registers_inputs_logs_outputs_and_result(self) -> None:
        fake_bin = self._prepare_fake_toolchain(xtb_mode="success")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
                actor_user_id="tester",
                request_id="req-xtb-success",
            )
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                result = ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)
        artifacts = self.service.list_artifacts(created.run_id)
        artifact_names = {artifact.name for artifact in artifacts}
        artifact_types = {artifact.artifact_type for artifact in artifacts}

        self.assertTrue(result.claimed)
        self.assertEqual(result.status, "completed")
        self.assertEqual(detail.status, "completed")
        self.assertEqual(detail.result_summary["energy_hartree"], -5.4321)
        self.assertEqual(detail.result_summary["xtb_version"], "6.6.1")
        self.assertEqual(detail.result_summary["runtime_seconds"], 12.34)
        self.assertTrue(detail.result_summary["normal_termination"])
        self.assertIn("input.xyz", artifact_names)
        self.assertIn("xtb.stdout.log", artifact_names)
        self.assertIn("xtb.stderr.log", artifact_names)
        self.assertIn("xtbopt.xyz", artifact_names)
        self.assertIn("result_json", artifact_types)

    def test_local_xtb_large_log_preview_is_truncated(self) -> None:
        fake_bin = self._prepare_fake_toolchain(xtb_mode="large-log")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
                actor_user_id="tester",
                request_id="req-xtb-large-log",
            )
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        stdout_artifact = next(
            artifact for artifact in self.service.list_artifacts(created.run_id) if artifact.name == "xtb.stdout.log"
        )
        preview = self.service.preview_artifact(stdout_artifact.artifact_id)

        self.assertLessEqual(len(preview.preview), 8000)
        self.assertIn("preview truncated", preview.preview)

    def test_local_xtb_reads_summary_fields_from_xtb_out(self) -> None:
        fake_bin = self._prepare_fake_toolchain(xtb_mode="xtb-out-summary")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
                actor_user_id="tester",
                request_id="req-xtb-out-summary",
            )
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)

        self.assertEqual(detail.result_summary["xtb_version"], "6.7.0")
        self.assertEqual(detail.result_summary["runtime_seconds"], 3.21)
        self.assertTrue(detail.result_summary["normal_termination"])

    def test_local_xtb_nonzero_exit_fails_and_keeps_logs(self) -> None:
        fake_bin = self._prepare_fake_toolchain(xtb_mode="fail")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
                actor_user_id="tester",
                request_id="req-xtb-fail",
            )
            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False):
                result = ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)
        artifact_names = {artifact.name for artifact in self.service.list_artifacts(created.run_id)}

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "XTB_FAILED")
        self.assertIn("xtb.stdout.log", artifact_names)
        self.assertIn("xtb.stderr.log", artifact_names)
        self.assertIn("xtb-error.json", artifact_names)

    def test_local_xtb_timeout_fails_and_can_retry(self) -> None:
        fake_bin = self._prepare_fake_toolchain(xtb_mode="success")
        original_path = os.environ.get("PATH", "")
        os.environ["PATH"] = f"{fake_bin}{os.pathsep}{original_path}"
        try:
            created = self.service.create_run(
                ComputationCreateRequest(**computation_payload(workflow_type="LOCAL_XTB", engine="XTB")),
                actor_user_id="tester",
                request_id="req-xtb-timeout",
            )

            with patch("app.computation_adapters.local_structure._rdkit_available", return_value=False), patch(
                "app.computation_adapters.local_xtb.LocalXtbAdapter._run_subprocess_with_heartbeat",
                side_effect=subprocess.TimeoutExpired(cmd=["xtb"], timeout=60),
            ):
                result = ComputationWorker(worker_id="worker-xtb-test").acquire_and_run_one()
        finally:
            os.environ["PATH"] = original_path

        detail = self.service.get_run(created.run_id)
        retry = self.service.retry_run(created.run_id, actor_user_id="tester", request_id="req-xtb-retry")

        self.assertEqual(result.status, "failed")
        self.assertEqual(detail.error["error_code"], "XTB_TIMEOUT")
        self.assertTrue(detail.error["retryable"])
        self.assertNotEqual(retry.run_id, created.run_id)
        self.assertEqual(retry.status, "queued")

    def _prepare_fake_toolchain(self, *, xtb_mode: str) -> Path:
        fake_bin = self.runtime_root / f"bin-{xtb_mode}"
        fake_bin.mkdir()
        self._write_fake_obabel(fake_bin / "obabel")
        self._write_fake_xtb(fake_bin / "xtb", mode=xtb_mode)
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
sys.stdout.write("fake obabel ok\\n")
""",
            encoding="utf-8",
        )
        path.chmod(0o755)

    def _write_fake_xtb(self, path: Path, *, mode: str) -> None:
        if mode == "success":
            body = """#!/usr/bin/env python3
from pathlib import Path
Path("xtbopt.xyz").write_text("2\\nfake xtb opt\\nC 0.0 0.0 0.0\\nO 1.1 0.0 0.0\\n", encoding="utf-8")
print("xtb version 6.6.1")
print("TOTAL ENERGY     -5.4321")
print("normal termination of xtb")
print("runtime_seconds: 12.34")
"""
        elif mode == "large-log":
            body = """#!/usr/bin/env python3
from pathlib import Path
Path("xtbopt.xyz").write_text("2\\nfake xtb opt\\nC 0.0 0.0 0.0\\nO 1.1 0.0 0.0\\n", encoding="utf-8")
print("xtb version 6.6.1")
print("TOTAL ENERGY     -5.4321")
print("normal termination of xtb")
print("runtime_seconds: 12.34")
print("x" * 20000)
"""
        elif mode == "xtb-out-summary":
            body = """#!/usr/bin/env python3
from pathlib import Path
Path("xtbopt.xyz").write_text("2\\nfake xtb opt\\nC 0.0 0.0 0.0\\nO 1.1 0.0 0.0\\n", encoding="utf-8")
Path("xtb.out").write_text("xtb version 6.7.0\\nnormal termination of xtb\\nruntime_seconds: 3.21\\n", encoding="utf-8")
print("TOTAL ENERGY     -5.4321")
"""
        else:
            body = """#!/usr/bin/env python3
import sys
print("xTB started")
print("xTB failed", file=sys.stderr)
sys.exit(2)
"""
        path.write_text(body, encoding="utf-8")
        path.chmod(0o755)
