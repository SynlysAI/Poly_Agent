"""Global task center API tests."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.main import app
from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService
from app.services.research_engine_service import ResearchEngineService
from app.schemas.research_engine import AlgorithmRunCreate

try:
    from .test_remote_interface_service import interface_payload
except ImportError:
    from test_remote_interface_service import interface_payload


class TaskCenterApiTest(ComputationTestCase):
    """覆盖 /tasks/center 的全局分页、搜索和权限过滤。"""

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        super().tearDown()

    @staticmethod
    def _login_as(user_id: str, role: str = "user") -> None:
        app.dependency_overrides[get_current_user] = lambda: {
            "user_id": user_id,
            "username": user_id,
            "role": role,
            "status": "active",
        }

    def test_keyword_search_runs_before_global_pagination(self) -> None:
        service = ComputationService()
        for index in range(25):
            name = "needle-target" if index == 18 else f"regular-{index:02d}"
            service.create_run(
                ComputationCreateRequest(
                    workflow_type="LOCAL_STRUCTURE",
                    engine="LOCAL",
                    molecule={"smiles": "CCO", "name": name},
                ),
                actor_user_id="demo_user",
                request_id=f"req-{index}",
            )

        page_resp = self.client.get("/api/v1/tasks/center", params={"page": 1, "page_size": 5})
        self.assertEqual(page_resp.status_code, 200)
        self.assertEqual(len(page_resp.json()["data"]["items"]), 5)
        self.assertEqual(page_resp.json()["data"]["total"], 25)

        search_resp = self.client.get(
            "/api/v1/tasks/center",
            params={"keyword": "needle-target", "page": 1, "page_size": 5},
        )
        self.assertEqual(search_resp.status_code, 200)
        data = search_resp.json()["data"]
        self.assertEqual(data["total"], 1)
        self.assertEqual(data["items"][0]["title"], "needle-target")

    def test_authenticated_users_only_see_their_tasks(self) -> None:
        service = ComputationService()
        for owner in ("user-a", "user-b"):
            service.create_run(
                ComputationCreateRequest(
                    workflow_type="LOCAL_STRUCTURE",
                    engine="LOCAL",
                    molecule={"smiles": "CCO", "name": f"{owner}-task"},
                ),
                actor_user_id=owner,
                request_id=f"req-{owner}",
            )

        self._login_as("user-a")
        user_resp = self.client.get("/api/v1/tasks/center")
        self.assertEqual(user_resp.status_code, 200)
        user_titles = {item["title"] for item in user_resp.json()["data"]["items"]}
        self.assertEqual(user_titles, {"user-a-task"})

        self._login_as("admin", role="admin")
        admin_resp = self.client.get("/api/v1/tasks/center")
        self.assertEqual(admin_resp.status_code, 200)
        admin_titles = {item["title"] for item in admin_resp.json()["data"]["items"]}
        self.assertEqual(admin_titles, {"user-a-task", "user-b-task"})

    def test_remote_algorithm_run_routes_to_vertical_prediction_detail(self) -> None:
        created = self.client.post(
            "/api/v1/research-engine/algorithm-interfaces",
            json=interface_payload(),
        )
        self.assertEqual(created.status_code, 200, created.text)
        version_id = created.json()["data"]["version"]["version_id"]
        self.client.post(
            f"/api/v1/research-engine/algorithm-interfaces/remote_tg_predictor/versions/{version_id}:activate"
        )
        with patch(
            "app.services.remote_interface_service.RemoteInterfaceService.invoke",
            return_value=({"prediction": 123.4}, {"status_code": 200, "latency_ms": 5}),
        ):
            run = ResearchEngineService().create_algorithm_run(
                AlgorithmRunCreate(
                    algorithm_id="remote_tg_predictor",
                    algorithm_version_id=version_id,
                    input_snapshot={"smiles": "CCO"},
                ),
                actor_user_id="demo_user",
            )

        response = self.client.get("/api/v1/tasks/center")

        self.assertEqual(response.status_code, 200, response.text)
        task = next(item for item in response.json()["data"]["items"] if item["task_id"] == run.run_id)
        self.assertEqual(task["module_id"], "vertical-prediction")
        self.assertEqual(task["module_name"], "垂类预测模型")
        self.assertEqual(task["route"]["path"], "/vertical-prediction")
        self.assertEqual(task["route"]["query"]["algorithm_id"], "remote_tg_predictor")
        self.assertEqual(task["route"]["query"]["run_id"], run.run_id)
