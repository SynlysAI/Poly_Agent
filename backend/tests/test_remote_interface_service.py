"""远程接口型垂类模型配置与调用测试。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch
import sys

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.schemas.research_engine import RemoteInterfaceConfig
from app.core.auth import get_current_user


def interface_payload(**overrides: object) -> dict:
    """构造最小远程接口模型请求。"""
    payload = {
        "algorithm_id": "remote_tg_predictor",
        "name": "Remote Tg Predictor",
        "version": "0.1.0",
        "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
        "output_schema": {"fields": {"prediction": "number"}, "required": ["prediction"]},
        "interface_config": {
            "protocol": "fastapi",
            "endpoint_url": "https://model.example.test/predict",
            "http_method": "POST",
            "response_selector": "data",
            "secret_refs": {"Authorization": "REMOTE_TG_API_TOKEN"},
        },
        "sample_input": {"smiles": "CCO"},
        "developer": "Model Team",
        "developer_organization": "Example Lab",
        "developer_contact": "model-team@example.test",
        "source_url": "https://example.test/model",
        "citation": "Example model citation",
        "visibility": "private",
    }
    payload.update(overrides)
    return payload


class RemoteInterfaceSchemaTest(ComputationTestCase):
    """覆盖远程接口边界校验。"""

    def test_accepts_fastapi_config_and_normalizes_method(self) -> None:
        config = RemoteInterfaceConfig(
            protocol="fastapi",
            endpoint_url="https://example.test/predict",
            http_method="post",
            secret_refs={"Authorization": "MODEL_API_TOKEN"},
        )
        self.assertEqual(config.http_method, "POST")
        self.assertEqual(config.secret_refs["Authorization"], "MODEL_API_TOKEN")

    def test_rejects_credentials_in_url(self) -> None:
        with self.assertRaises(ValidationError):
            RemoteInterfaceConfig(endpoint_url="https://user:password@example.test/predict")

    def test_rejects_sensitive_static_header(self) -> None:
        with self.assertRaises(ValidationError):
            RemoteInterfaceConfig(
                endpoint_url="https://example.test/predict",
                static_headers={"Authorization": "Bearer plaintext"},
            )

    def test_rejects_conflicting_secret_and_static_header(self) -> None:
        with self.assertRaises(ValidationError):
            RemoteInterfaceConfig(
                endpoint_url="https://example.test/predict",
                static_headers={"Authorization": "static"},
                secret_refs={"Authorization": "MODEL_API_TOKEN"},
            )

    def test_rejects_credentials_mapped_from_runtime_input(self) -> None:
        with self.assertRaises(ValidationError):
            RemoteInterfaceConfig(
                endpoint_url="https://example.test/predict",
                header_bindings={"Authorization": "api_token"},
            )
        with self.assertRaises(ValidationError):
            RemoteInterfaceConfig(
                endpoint_url="https://example.test/predict",
                query_bindings={"api_key": "api_token"},
            )

    def test_accepts_multipart_and_artifact_manifest_config(self) -> None:
        config = RemoteInterfaceConfig(
            endpoint_url="https://example.test/predict",
            body_mode="multipart",
            multipart_json_field="payload",
            file_bindings={"spectrum": "spectrum_file"},
            result_mode="artifact_manifest",
            artifact_allowed_hosts=["downloads.example.test"],
        )

        self.assertEqual(config.body_mode, "multipart")
        self.assertEqual(config.file_bindings["spectrum"], "spectrum_file")
        self.assertEqual(config.result_mode, "artifact_manifest")


class RemoteInterfaceApiTest(ComputationTestCase):
    """覆盖接口模型 API 和统一 AlgorithmRun 调用。"""

    base_url = "/api/v1/research-engine"

    def test_interface_contract_accepts_input_and_output_assets(self) -> None:
        payload = interface_payload(
            input_assets=[{
                "key": "spectrum",
                "label": "光谱文件",
                "required": True,
                "extensions": [".csv"],
                "mime_types": ["text/csv"],
                "max_size_bytes": 1024,
            }],
            output_assets=[{
                "key": "report",
                "label": "预测报告",
                "required": True,
                "artifact_type": "report_pdf",
                "mime_type": "application/pdf",
                "extensions": [".pdf"],
            }],
            interface_config={
                "protocol": "fastapi",
                "endpoint_url": "https://model.example.test/predict",
                "http_method": "POST",
                "body_mode": "multipart",
                "multipart_json_field": "payload",
                "file_bindings": {"spectrum": "spectrum_file"},
                "result_mode": "artifact_manifest",
            },
        )

        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=payload)

        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        self.assertEqual(data["version"]["input_assets"][0]["key"], "spectrum")
        self.assertEqual(data["algorithm"]["output_assets"][0]["key"], "report")

    def test_multipart_sample_test_accepts_declared_file_and_returns_previews(self) -> None:
        payload = interface_payload(
            input_assets=[{
                "key": "spectrum",
                "required": True,
                "extensions": [".csv"],
                "mime_types": ["text/csv"],
            }],
            output_assets=[{
                "key": "report",
                "required": True,
                "artifact_type": "report_pdf",
                "mime_type": "application/pdf",
            }],
            interface_config={
                "protocol": "fastapi",
                "endpoint_url": "https://model.example.test/predict",
                "http_method": "POST",
                "body_mode": "multipart",
                "file_bindings": {"spectrum": "spectrum_file"},
                "result_mode": "artifact_manifest",
            },
        )
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        version_id = created.json()["data"]["version"]["version_id"]

        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=(
                {"prediction": 123.4},
                {
                    "status_code": 200,
                    "latency_ms": 12,
                    "protocol": "fastapi",
                    "artifact_previews": [{
                        "key": "report",
                        "name": "report.pdf",
                        "mime_type": "application/pdf",
                        "size_bytes": 128,
                        "sha256": "a" * 64,
                    }],
                },
            ),
        ):
            tested = self.client.post(
                f"{self.base_url}/algorithm-interfaces/{payload['algorithm_id']}/versions/{version_id}:test-multipart",
                data={"input_snapshot": '{"smiles":"CCO"}'},
                files={"spectrum": ("sample.csv", b"x,y\n1,2\n", "text/csv")},
            )

        self.assertEqual(tested.status_code, 200, tested.text)
        result = tested.json()["data"]
        self.assertEqual(result["output_preview"]["prediction"], 123.4)
        self.assertEqual(result["artifact_previews"][0]["key"], "report")

    def test_algorithm_id_availability_guides_owner_to_new_interface_version(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)

        response = self.client.get(
            f"{self.base_url}/algorithms/id-availability",
            params={"algorithm_id": "remote_tg_predictor"},
        )

        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertFalse(data["available"])
        self.assertEqual(data["recommended_action"], "create_interface_version")
        self.assertTrue(data["can_create_version"])
        self.assertEqual(len(data["suggestions"]), 3)

    def test_model_delete_removes_registry_and_versions_but_reports_preserved_runs(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)

        deleted = self.client.delete(
            f"{self.base_url}/algorithms/remote_tg_predictor",
            params={"confirm_algorithm_id": "remote_tg_predictor"},
        )

        self.assertEqual(deleted.status_code, 200, deleted.text)
        data = deleted.json()["data"]
        self.assertEqual(data["deleted_versions"], 1)
        self.assertEqual(data["preserved_runs"], 0)
        self.assertTrue(data["registry_deleted"])
        self.assertEqual(
            self.client.get(f"{self.base_url}/algorithms/remote_tg_predictor").status_code,
            404,
        )

    def test_mcp_config_is_saved_but_cannot_be_activated(self) -> None:
        payload = interface_payload(
            interface_config={
                "protocol": "mcp",
                "endpoint_url": "https://mcp.example.test/rpc",
                "http_method": "POST",
            }
        )
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=payload)
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        self.assertEqual(data["algorithm"]["source"], "remote_interface")
        self.assertEqual(data["version"]["source_kind"], "remote_interface")
        self.assertEqual(data["algorithm"]["developer_contact"], "model-team@example.test")

        version_id = data["version"]["version_id"]
        activated = self.client.post(
            f"{self.base_url}/algorithm-interfaces/{payload['algorithm_id']}/versions/{version_id}:activate"
        )
        self.assertEqual(activated.status_code, 409)

    def test_http_interface_can_be_tested_activated_and_called(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        version_id = data["version"]["version_id"]
        self.assertNotIn("Bearer", created.text)

        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 123.4}, {"status_code": 200, "latency_ms": 12, "protocol": "fastapi"}),
        ):
            tested = self.client.post(
                f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
                json={"input_snapshot": {"smiles": "CCO"}},
            )
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertTrue(tested.json()["data"]["ok"])

        activated = self.client.post(
            f"{self.base_url}/algorithms/{algorithm_id}/versions/{version_id}:activate"
        )
        self.assertEqual(activated.status_code, 200, activated.text)
        self.assertEqual(activated.json()["data"]["status"], "active")

        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 126.1}, {"status_code": 200, "latency_ms": 9, "protocol": "fastapi"}),
        ):
            run = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": algorithm_id,
                    "algorithm_version_id": version_id,
                    "trigger_source": "human_workflow",
                    "input_snapshot": {"smiles": "CCN"},
                },
            )
        self.assertEqual(run.status_code, 200, run.text)
        run_data = run.json()["data"]
        self.assertEqual(run_data["status"], "completed")
        self.assertEqual(run_data["source_kind"], "remote_interface")
        self.assertEqual(run_data["output_summary"]["prediction"], 126.1)
        self.assertNotIn("REMOTE_TG_API_TOKEN", run.text)

        listed = self.client.get(f"{self.base_url}/algorithms?source=remote_interface")
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertEqual(listed.json()["data"]["total"], 1)

    def test_testing_active_version_keeps_it_callable(self) -> None:
        created = self.client.post(
            f"{self.base_url}/algorithm-interfaces",
            json=interface_payload(
                interface_config={
                    "protocol": "fastapi",
                    "endpoint_url": "https://model.example.test/predict",
                    "http_method": "POST",
                },
            ),
        )
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        version_id = data["version"]["version_id"]

        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 123.4}, {"status_code": 200, "latency_ms": 12, "protocol": "fastapi"}),
        ):
            self.assertEqual(
                self.client.post(
                    f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
                    json={"input_snapshot": {"smiles": "CCO"}},
                ).status_code,
                200,
            )
            self.assertEqual(
                self.client.post(
                    f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:activate"
                ).status_code,
                200,
            )
            tested = self.client.post(
                f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
                json={"input_snapshot": {"smiles": "CCN"}},
            )
        self.assertEqual(tested.status_code, 200, tested.text)
        self.assertEqual(tested.json()["data"]["ok"], True)

        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 123.4}, {"status_code": 200, "latency_ms": 12, "protocol": "fastapi"}),
        ):
            run = self.client.post(
                f"{self.base_url}/algorithm-runs",
                json={
                    "algorithm_id": algorithm_id,
                    "algorithm_version_id": version_id,
                    "trigger_source": "human_workflow",
                    "input_snapshot": {"smiles": "CCN"},
                },
            )
        self.assertEqual(run.status_code, 200, run.text)

    def test_rejects_mapping_to_unknown_input_field(self) -> None:
        payload = interface_payload(
            interface_config={
                "protocol": "http",
                "endpoint_url": "https://model.example.test/predict",
                "header_bindings": {"X-Smiles": "unknown_field"},
            }
        )
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=payload)
        self.assertEqual(created.status_code, 422, created.text)

    def test_rejects_sample_input_that_breaks_the_input_contract(self) -> None:
        created = self.client.post(
            f"{self.base_url}/algorithm-interfaces",
            json=interface_payload(sample_input={"smiles": 123}),
        )
        self.assertEqual(created.status_code, 422, created.text)

    def test_new_draft_version_does_not_disable_the_active_version(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        version_id = data["version"]["version_id"]
        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 123.4}, {"status_code": 200, "latency_ms": 12, "protocol": "fastapi"}),
        ):
            self.client.post(
                f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
                json={"input_snapshot": {"smiles": "CCO"}},
            )
        activated = self.client.post(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}:activate"
        )
        self.assertEqual(activated.status_code, 200, activated.text)

        new_version = self.client.post(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions",
            json={
                "version": "0.1.1",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"prediction": "number"}, "required": ["prediction"]},
                "interface_config": {
                    "protocol": "fastapi",
                    "endpoint_url": "https://model.example.test/v2/predict",
                    "http_method": "POST",
                },
                "sample_input": {"smiles": "CCN"},
            },
        )
        self.assertEqual(new_version.status_code, 200, new_version.text)
        draft_version_id = new_version.json()["data"]["version_id"]
        draft_run = self.client.post(
            f"{self.base_url}/algorithm-runs",
            json={
                "algorithm_id": algorithm_id,
                "algorithm_version_id": draft_version_id,
                "trigger_source": "human_workflow",
                "input_snapshot": {"smiles": "CCN"},
            },
        )
        self.assertEqual(draft_run.status_code, 409, draft_run.text)

        registry = self.client.get(f"{self.base_url}/algorithms/{algorithm_id}")
        self.assertEqual(registry.status_code, 200, registry.text)
        registry_data = registry.json()["data"]
        self.assertEqual(registry_data["active_version_id"], version_id)
        self.assertEqual(registry_data["status"], "active")

    def test_unpublished_interface_version_can_be_updated_in_place(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        version_id = data["version"]["version_id"]

        updated = self.client.patch(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}",
            json={
                "interface_config": {
                    "protocol": "fastapi",
                    "endpoint_url": "https://model.example.test/v2/predict",
                    "http_method": "POST",
                    "response_selector": "result",
                },
                "input_schema": {"fields": {"smiles": "string", "temperature": "number"}, "required": ["smiles"]},
                "sample_input": {"smiles": "CCN", "temperature": 25},
                "description": "Updated draft",
            },
        )
        self.assertEqual(updated.status_code, 200, updated.text)
        version = updated.json()["data"]
        self.assertEqual(version["version_id"], version_id)
        self.assertEqual(version["version"], "0.1.0")
        self.assertEqual(version["status"], "validated")
        self.assertEqual(version["interface_config"]["endpoint_url"], "https://model.example.test/v2/predict")
        self.assertEqual(version["input_schema"]["fields"]["temperature"], "number")
        self.assertEqual(version["contract"]["sample_input"]["smiles"], "CCN")
        self.assertEqual(version["deployment"], {})

        registry = self.client.get(f"{self.base_url}/algorithms/{algorithm_id}")
        self.assertEqual(registry.status_code, 200, registry.text)
        self.assertEqual(registry.json()["data"]["deployment_status"], "testing")

    def test_active_interface_version_cannot_be_updated(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        version_id = data["version"]["version_id"]
        activated = self.client.post(
            f"{self.base_url}/algorithms/{algorithm_id}/versions/{version_id}:activate"
        )
        self.assertEqual(activated.status_code, 200, activated.text)

        updated = self.client.patch(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}",
            json={"description": "Should fail"},
        )
        self.assertEqual(updated.status_code, 409, updated.text)

    def test_draft_update_does_not_change_active_registry_summary(self) -> None:
        created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
        self.assertEqual(created.status_code, 200, created.text)
        data = created.json()["data"]
        algorithm_id = data["algorithm"]["algorithm_id"]
        active_version_id = data["version"]["version_id"]
        activated = self.client.post(
            f"{self.base_url}/algorithms/{algorithm_id}/versions/{active_version_id}:activate"
        )
        self.assertEqual(activated.status_code, 200, activated.text)

        draft = self.client.post(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions",
            json={
                "version": "0.1.1",
                "input_schema": {"fields": {"smiles": "string"}, "required": ["smiles"]},
                "output_schema": {"fields": {"prediction": "number"}, "required": ["prediction"]},
                "interface_config": {
                    "protocol": "fastapi",
                    "endpoint_url": "https://model.example.test/v2/predict",
                    "http_method": "POST",
                },
                "sample_input": {"smiles": "CCN"},
            },
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        draft_version_id = draft.json()["data"]["version_id"]

        updated = self.client.patch(
            f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{draft_version_id}",
            json={"interface_config": {
                "protocol": "fastapi",
                "endpoint_url": "https://model.example.test/v3/predict",
                "http_method": "POST",
            }},
        )
        self.assertEqual(updated.status_code, 200, updated.text)

        registry = self.client.get(f"{self.base_url}/algorithms/{algorithm_id}")
        self.assertEqual(registry.status_code, 200, registry.text)
        registry_data = registry.json()["data"]
        self.assertEqual(registry_data["active_version_id"], active_version_id)
        self.assertEqual(registry_data["interface_config"]["endpoint_url"], "https://model.example.test/predict")

    def test_non_owner_cannot_update_interface_draft(self) -> None:
        self.client.app.dependency_overrides[get_current_user] = lambda: {
            "user_id": "interface-owner",
            "role": "user",
        }
        try:
            created = self.client.post(f"{self.base_url}/algorithm-interfaces", json=interface_payload())
            self.assertEqual(created.status_code, 200, created.text)
            data = created.json()["data"]
            algorithm_id = data["algorithm"]["algorithm_id"]
            version_id = data["version"]["version_id"]

            self.client.app.dependency_overrides[get_current_user] = lambda: {
                "user_id": "different-user",
                "role": "user",
            }
            updated = self.client.patch(
                f"{self.base_url}/algorithm-interfaces/{algorithm_id}/versions/{version_id}",
                json={"description": "Should fail"},
            )
            self.assertEqual(updated.status_code, 403, updated.text)
        finally:
            self.client.app.dependency_overrides.pop(get_current_user, None)
