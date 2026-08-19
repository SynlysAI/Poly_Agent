"""Assistant 会话导出与反馈命令测试。"""

from __future__ import annotations

import json
import zipfile
from io import BytesIO

try:
    from ._computation_test_utils import ComputationTestCase
except ImportError:
    from _computation_test_utils import ComputationTestCase

from app.core.auth import get_current_user, get_current_user_with_query_token
from app.infra.assistant_command_repositories import (
    AssistantCommandRunRepository,
    AssistantFeedbackRepository,
)
from app.infra.computation_repositories import ComputationArtifactRepository
from app.infra.computation_repositories import utc_now
from app.infra.research_engine_repositories import (
    AlgorithmRunRepository,
    AssistantChatRepository,
    AssistantRunRepository,
    AssistantRuntimeAssetRepository,
    AssistantToolCallRepository,
)
from app.main import app


class AssistantExportFeedbackTest(ComputationTestCase):
    """验证 /export 与 /feedback 的交付、审计与归属边界。"""

    def setUp(self) -> None:
        super().setUp()
        self.user = {"user_id": "user-1", "username": "user", "role": "user", "status": "active"}
        self.other_user = {
            "user_id": "user-2",
            "username": "other",
            "role": "user",
            "status": "active",
        }
        app.dependency_overrides[get_current_user] = lambda: self.user
        app.dependency_overrides[get_current_user_with_query_token] = lambda: self.user

    def tearDown(self) -> None:
        app.dependency_overrides.pop(get_current_user, None)
        app.dependency_overrides.pop(get_current_user_with_query_token, None)
        super().tearDown()

    def _chat_id(self) -> str:
        """创建带控制状态与消息的会话。"""
        response = self.client.post(
            "/api/v1/assistant/chats",
            json={
                "title": "导出反馈会话",
                "messages": [
                    {"role": "user", "content": "请生成材料实验方案"},
                    {"role": "assistant", "content": "已完成第一轮实验方案。"},
                ],
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        chat_id = response.json()["data"]["chat_id"]
        AssistantChatRepository.update_owned(
            chat_id,
            "user-1",
            {
                "plan_mode": True,
                "permission_mode": "read_only",
                "goal": {
                    "goal_id": "goal-export",
                    "objective": "完成可审计会话交付",
                    "status": "active",
                    "created_by": "user-1",
                    "created_at": utc_now(),
                    "updated_at": utc_now(),
                },
                "model": {"providerId": "provider-a", "modelId": "model-a"},
            },
        )
        return chat_id

    def _create_run(self, chat_id: str) -> str:
        """创建一个真实 assistant run 并写入模型路由。"""
        response = self.client.post(
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json={"content": "请生成材料实验方案", "context": {"plan_mode": True}},
        )
        self.assertEqual(response.status_code, 200, response.text)
        run_id = response.json()["data"]["run_id"]
        AssistantRunRepository.update_fields(
            "run_id",
            run_id,
            {
                "status": "completed",
                "stage": "completed",
                "provider_id": "provider-a",
                "model_id": "model-a",
                "route": {
                    "provider_id": "provider-a",
                    "model_id": "model-a",
                    "route_reason": "test",
                },
            },
        )
        return run_id

    def _tool_snapshot(self, chat_id: str) -> None:
        """写入工具调用、AlgorithmRun 与一成功一缺失的 artifact。"""
        now = utc_now()
        AlgorithmRunRepository.save(
            "run_id",
            {
                "run_id": "alg-run-export",
                "algorithm_id": "vertical-predictor",
                "status": "completed",
                "created_by": "user-1",
                "created_at": now,
                "updated_at": now,
                "artifact_refs": [
                    {"artifact_id": "artifact-missing", "name": "missing.csv"}
                ],
            },
        )
        artifact_path = self.runtime_root / "outputs" / "artifact-ok.csv"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.write_text("feature,value\nsmiles,CCO\n", encoding="utf-8")
        ComputationArtifactRepository.save(
            "artifact_id",
            {
                "artifact_id": "artifact-ok",
                "run_id": "legacy-computation",
                "owner_type": "computation_run",
                "owner_id": "legacy-computation",
                "step_key": "result",
                "artifact_type": "table_csv",
                "name": "预测结果.csv",
                "storage_uri": str(artifact_path),
                "mime_type": "text/csv",
                "size_bytes": artifact_path.stat().st_size,
                "checksum_sha256": "checksum",
                "created_at": now,
            },
        )
        AssistantToolCallRepository.save(
            "call_id",
            {
                "call_id": "call-export",
                "chat_id": chat_id,
                "created_by": "user-1",
                "trace_id": "trace-export",
                "command_id": "command-tool-export",
                "tool_id": "algorithm:vertical-predictor",
                "algorithm_id": "vertical-predictor",
                "tool_name": "Vertical Predictor",
                "phase": "completed",
                "run_id": "alg-run-export",
                "arguments": {"smiles": "CCO"},
                "result_summary": {"confidence": 0.92},
                "artifact_refs": [
                    {"artifact_id": "artifact-ok", "name": "预测结果.csv"},
                    {"artifact_id": "artifact-missing", "name": "missing.csv"},
                ],
                "uploaded_assets": [
                    {
                        "asset_id": "runtime-asset-export",
                        "asset_key": "input",
                        "filename": "实验约束.txt",
                        "content_type": "text/plain",
                        "size_bytes": 18,
                        "status": "active",
                    }
                ],
                "events": [],
                "created_at": now,
                "updated_at": now,
            },
        )
        runtime_path = (
            self.runtime_root
            / "assistant-runtime-assets"
            / "call-export"
            / "input-runtime-asset-export.txt"
        )
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        runtime_path.write_text("温度不超过 120C\n", encoding="utf-8")
        AssistantRuntimeAssetRepository.save(
            "asset_id",
            {
                "asset_id": "runtime-asset-export",
                "call_id": "call-export",
                "chat_id": chat_id,
                "created_by": "user-1",
                "asset_key": "input",
                "filename": "实验约束.txt",
                "content_type": "text/plain",
                "size_bytes": runtime_path.stat().st_size,
                "path": str(runtime_path),
                "status": "active",
                "expires_at": None,
                "created_at": now,
                "updated_at": now,
            },
        )

    def _execute(self, chat_id: str, line: str, payload: dict | None = None) -> dict:
        """执行命令并断言 API 成功。"""
        response = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={
                "chat_id": chat_id,
                "line": line,
                "payload": payload or {},
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def _events(self, chat_id: str, event_type: str) -> list[dict]:
        """读取指定类型的会话事件。"""
        return [
            item
            for item in AssistantCommandRunRepository.events_after(
                chat_id,
                "user-1",
                event_types={event_type},
            )
            if item.get("type") == event_type
        ]

    def test_export_json_markdown_zip_consistency_artifacts_events_and_owner(self) -> None:
        chat_id = self._chat_id()
        run_id = self._create_run(chat_id)
        self._tool_snapshot(chat_id)

        interaction = self._execute(chat_id, "/export")
        self.assertEqual(interaction["status"], "interaction")
        self.assertEqual(
            [choice["value"] for choice in interaction["interaction"]["choices"]],
            ["json", "markdown", "zip"],
        )

        json_export = self._execute(chat_id, "/export json")
        markdown_export = self._execute(chat_id, "/export markdown")
        zip_export = self._execute(chat_id, "/export zip")
        self.assertTrue(all(item["status"] == "success" for item in [json_export, markdown_export, zip_export]))
        self.assertTrue(json_export["download_url"].endswith(f"/commands/{json_export['command_id']}/download"))
        self.assertEqual(json_export["download_filename"].endswith(".json"), True)

        json_response = self.client.get(json_export["download_url"])
        markdown_response = self.client.get(markdown_export["download_url"])
        zip_response = self.client.get(zip_export["download_url"])
        self.assertEqual(json_response.status_code, 200, json_response.text)
        self.assertEqual(markdown_response.status_code, 200, markdown_response.text)
        self.assertEqual(zip_response.status_code, 200, zip_response.text)
        self.assertEqual(json_response.headers["content-type"].split(";")[0], "application/json")
        self.assertIn("text/markdown", markdown_response.headers["content-type"])
        self.assertEqual(zip_response.headers["content-type"], "application/zip")

        json_payload = json_response.json()
        self.assertEqual(json_payload["session"]["chat_id"], chat_id)
        self.assertTrue(json_payload["control_state"]["plan_mode"])
        self.assertEqual(json_payload["control_state"]["permission_mode"], "read_only")
        self.assertGreaterEqual(len(json_payload["messages"]), 2)
        self.assertIn(run_id, {item["run_id"] for item in json_payload["assistant_runs"]})
        self.assertIn("call-export", {item["call_id"] for item in json_payload["tool_calls"]})
        self.assertIn("alg-run-export", {item["run_id"] for item in json_payload["algorithm_runs"]})
        self.assertTrue(json_payload["metadata"]["manifest_digest"].startswith("sha256:"))
        manifest = json_payload["metadata"]["artifact_manifest"]
        self.assertEqual(
            {(item["artifact_id"], item["status"]) for item in manifest},
            {
                ("artifact-ok", "available"),
                ("artifact-missing", "missing"),
                ("runtime-asset-export", "available"),
            },
        )

        markdown_text = markdown_response.text
        self.assertIn("# PolyAgent 会话导出", markdown_text)
        self.assertIn("请生成材料实验方案", markdown_text)
        self.assertIn(run_id, markdown_text)
        self.assertIn("artifact-missing", markdown_text)

        with zipfile.ZipFile(BytesIO(zip_response.content)) as archive:
            names = set(archive.namelist())
            self.assertIn("session.json", names)
            self.assertIn("messages.json", names)
            self.assertIn("commands.jsonl", names)
            self.assertIn("execution_trace.jsonl", names)
            self.assertIn("tool_calls.json", names)
            self.assertIn("metadata.json", names)
            self.assertIn("artifacts/预测结果.csv", names)
            self.assertIn("artifacts/实验约束.txt", names)
            session = json.loads(archive.read("session.json"))
            messages = json.loads(archive.read("messages.json"))
            tool_payload = json.loads(archive.read("tool_calls.json"))
            metadata = json.loads(archive.read("metadata.json"))
            commands = [json.loads(line) for line in archive.read("commands.jsonl").splitlines()]
            trace = [json.loads(line) for line in archive.read("execution_trace.jsonl").splitlines()]
            self.assertEqual(session["session"]["chat_id"], chat_id)
            zip_state = dict(session["control_state"])
            json_state = dict(json_payload["control_state"])
            zip_state.pop("command_event_seq")
            json_state.pop("command_event_seq")
            self.assertEqual(zip_state, json_state)
            self.assertEqual(
                {item["message_id"] for item in messages},
                {item["message_id"] for item in json_payload["messages"]},
            )
            self.assertEqual(
                {item["call_id"] for item in tool_payload["tool_calls"]},
                {item["call_id"] for item in json_payload["tool_calls"]},
            )
            self.assertEqual(
                {item["run_id"] for item in tool_payload["algorithm_runs"]},
                {item["run_id"] for item in json_payload["algorithm_runs"]},
            )
            self.assertGreaterEqual(len(commands), 4)
            self.assertGreaterEqual(len(trace), len(commands) * 2)
            self.assertEqual(
                archive.read("artifacts/预测结果.csv").decode("utf-8"),
                "feature,value\nsmiles,CCO\n",
            )
            self.assertEqual(
                archive.read("artifacts/实验约束.txt").decode("utf-8"),
                "温度不超过 120C\n",
            )
            self.assertEqual(
                {(item["artifact_id"], item["status"]) for item in metadata["artifact_manifest"]},
                {
                    ("artifact-ok", "available"),
                    ("artifact-missing", "missing"),
                    ("runtime-asset-export", "available"),
                },
            )

        export_events = self._events(chat_id, "session.exported")
        self.assertEqual(len(export_events), 6)
        self.assertEqual(
            [item["data"]["status"] for item in export_events[-2:]],
            ["started", "completed"],
        )
        self.assertTrue(export_events[-1]["data"]["manifest_digest"].startswith("sha256:"))

        app.dependency_overrides[get_current_user] = lambda: self.other_user
        app.dependency_overrides[get_current_user_with_query_token] = lambda: self.other_user
        denied = self.client.get(zip_export["download_url"])
        self.assertEqual(denied.status_code, 404, denied.text)

    def test_feedback_records_authoritative_context_without_comment_in_events(self) -> None:
        chat_id = self._chat_id()
        run_id = self._create_run(chat_id)

        opened = self._execute(chat_id, "/feedback")
        self.assertEqual(opened["status"], "interaction")
        self.assertEqual(opened["interaction"]["kind"], "form")
        self.assertEqual(
            [choice["value"] for choice in opened["interaction"]["choices"]],
            ["helpful", "not_helpful"],
        )

        submitted = self._execute(
            chat_id,
            "/feedback",
            {"rating": "not_helpful", "comment": "模型没有保留我的实验约束"},
        )
        self.assertEqual(submitted["status"], "success")
        feedback = AssistantFeedbackRepository.list_for_chat(chat_id, "user-1")[0]
        self.assertEqual(feedback["rating"], "not_helpful")
        self.assertEqual(feedback["comment"], "模型没有保留我的实验约束")
        self.assertEqual(feedback["trace_id"], run_id)
        self.assertEqual(feedback["model_route"]["provider_id"], "provider-a")
        self.assertEqual(feedback["model_route"]["model_id"], "model-a")
        self.assertEqual(feedback["agent_version"], "0.1.0")

        events = self._events(chat_id, "feedback.recorded")
        self.assertEqual(len(events), 1)
        event_data = events[0]["data"]
        self.assertEqual(event_data["feedback_id"], feedback["feedback_id"])
        self.assertEqual(event_data["rating"], "not_helpful")
        self.assertEqual(event_data["trace_id"], run_id)
        self.assertNotIn("模型没有保留我的实验约束", json.dumps(events, ensure_ascii=False))
        command = AssistantCommandRunRepository.find_one(
            {"command_id": submitted["command_id"]}
        )
        self.assertEqual(command["raw_args"], "")
        self.assertNotIn("模型没有保留我的实验约束", json.dumps(command, ensure_ascii=False))

        app.dependency_overrides[get_current_user] = lambda: self.other_user
        denied = self.client.post(
            "/api/v1/assistant/commands/execute",
            json={"chat_id": chat_id, "line": "/feedback", "payload": {"rating": "helpful"}},
        )
        self.assertEqual(denied.status_code, 404, denied.text)
