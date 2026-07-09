"""Global task center API tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user
from app.main import app
from app.schemas.computation import ComputationCreateRequest
from app.services.computation_service import ComputationService


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
