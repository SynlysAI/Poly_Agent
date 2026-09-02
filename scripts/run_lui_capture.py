#!/usr/bin/env python
"""LUI Agent 录制事实驱动器。

把 Golden Set 任务经真实产品链路执行（HTTP API + assistant run worker），
再按 evaluation_id 抓取原始事实，写入离线评测可消费的 fixtures 目录。

用法示例：

```bash
PYTHONPATH=backend conda run -n poly_agent python scripts/run_lui_capture.py \
  --evaluation-id lui-eval-full-2026.09.01 \
  --categories tool_selection,knowledge_retrieval,project_fact \
  --provider-id deepseek --model-id deepseek-chat
```
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx


REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_PATH = REPO_ROOT / "backend"
if str(BACKEND_PATH) not in sys.path:
    sys.path.insert(0, str(BACKEND_PATH))

from evaluation.lui.capture import capture_facts_by_evaluation  # noqa: E402
from evaluation.lui.runner import load_dataset  # noqa: E402
from evaluation.lui.schemas import DATASET_VERSION, GoldenTask  # noqa: E402


RUN_TERMINAL_STATUSES = frozenset({"completed", "failed", "canceled"})
CONTINUATION_TERMINAL_STATES = frozenset({"completed", "failed", "dead_letter"})
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_POLL_INTERVAL_SECONDS = 2.0


def load_backend_env(path: Path = BACKEND_PATH / ".env") -> None:
    """加载后端环境文件，保证 capture 能连接与后端一致的存储。

    Args:
        path: 后端 .env 文件路径。
    """
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def select_tasks(
    tasks: list[GoldenTask],
    *,
    categories: list[str] | None,
    only_task: str | None,
    limit: int | None,
) -> list[GoldenTask]:
    """按分类、任务 ID 和数量筛选待录制任务。

    Args:
        tasks: Golden Set 全量任务。
        categories: 允许的 category 白名单；None 表示全部分类。
        only_task: 只执行该任务 ID；None 表示不限定。
        limit: 最多返回的任务数；None 表示不限制。

    Returns:
        筛选后的任务列表。

    Raises:
        ValueError: 筛选条件无匹配任务或任务 ID 不存在时抛出。
    """
    selected = tasks
    if only_task:
        selected = [task for task in selected if task.id == only_task]
        if not selected:
            raise ValueError(f"task not found: {only_task}")
    if categories:
        allowed = {item.strip() for item in categories if item.strip()}
        selected = [task for task in selected if task.category in allowed]
    if limit is not None and limit >= 0:
        selected = selected[:limit]
    if not selected:
        raise ValueError("no golden tasks matched the capture filters")
    return selected


def build_run_context(
    task: GoldenTask,
    *,
    evaluation_id: str,
    evaluation_version: str,
    provider_id: str | None,
    model_id: str | None,
) -> dict[str, Any]:
    """构造评测 run 的请求上下文。

    Args:
        task: Golden 任务。
        evaluation_id: 评测批次 ID。
        evaluation_version: 数据集版本。
        provider_id: 固定的模型 provider ID；None 表示沿用运行时路由。
        model_id: 固定的模型 ID；None 表示沿用运行时路由。

    Returns:
        合并评测字段后的请求上下文。
    """
    context: dict[str, Any] = dict(task.context.model_dump(exclude_none=True))
    context.update(
        {
            "evaluation_id": evaluation_id,
            "task_id": task.id,
            "evaluation_version": evaluation_version,
            "mode": context.get("mode") or task.mode,
        }
    )
    model = dict(context.get("model") or {})
    if provider_id:
        model["providerId"] = provider_id
    if model_id:
        model["modelId"] = model_id
    if model:
        context["model"] = model
    return context


def final_tool_call_ids(run: dict[str, Any]) -> list[str]:
    """从 run 持久化事件中提取最终返回的工具调用 ID。

    Args:
        run: GET /assistant/runs/{run_id} 返回的 run 文档。

    Returns:
        按出现顺序去重后的 call_id 列表。
    """
    call_ids: list[str] = []
    for event in reversed(run.get("events") or []):
        if str(event.get("type") or "") != "final":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        for call in data.get("tool_calls") or []:
            call_id = str(call.get("call_id") or "")
            if call_id and call_id not in call_ids:
                call_ids.append(call_id)
        break
    return call_ids


def should_auto_confirm(call: dict[str, Any]) -> bool:
    """判断驱动器是否应自动确认该工具调用。

    Args:
        call: GET /assistant/tool-calls/{call_id} 返回的调用文档。

    Returns:
        仅参数齐全且等待确认的提案返回 True；缺参提案保持原样留给评测器计分。
    """
    return str(call.get("phase") or "") == "awaiting_confirmation"


class LuiCaptureClient:
    """驱动真实 LUI 产品链路的 HTTP 客户端。"""

    def __init__(self, base_url: str, token: str | None = None, timeout: float = 30.0) -> None:
        """初始化 HTTP 客户端。

        Args:
            base_url: 后端根地址。
            token: 可选访问令牌；login 后自动更新。
            timeout: 单请求超时秒数。
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        self.token = token

    def _headers(self) -> dict[str, str]:
        """构造带认证的请求头。"""
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request(self, method: str, path: str, *, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
        """调用后端 API 并解包 ApiResponse 数据域。

        Args:
            method: HTTP 方法。
            path: API 路径。
            json_body: 可选 JSON 请求体。

        Returns:
            ApiResponse 中的 data 字段。
        """
        response = self.client.request(
            method,
            path,
            headers=self._headers(),
            json=json_body,
        )
        payload = response.json()
        if response.status_code >= 400:
            detail = payload.get("detail") or payload.get("message") or response.text
            raise RuntimeError(f"API {method} {path} -> HTTP {response.status_code}: {detail}")
        if int(payload.get("code", 0)) != 0:
            raise RuntimeError(f"API {path} failed: {payload.get('message')}")
        return dict(payload.get("data") or {})

    def login(self, username: str, password: str) -> None:
        """登录并缓存访问令牌。

        Args:
            username: 用户名。
            password: 密码。
        """
        data = self._request(
            "POST",
            "/api/v1/auth/login",
            json_body={"username": username, "password": password},
        )
        token = str(data.get("access_token") or "")
        if not token:
            raise RuntimeError("login response missing access_token")
        self.token = token

    def create_chat(self, task: GoldenTask, evaluation_id: str) -> dict[str, Any]:
        """为单条任务创建独立会话。

        Args:
            task: Golden 任务。
            evaluation_id: 评测批次 ID。

        Returns:
            创建后的 chat 文档。
        """
        context = task.context
        payload = {
            "title": f"[LUI-EVAL] {evaluation_id} {task.id}",
            "mode": task.mode,
            "knowledge_base_ids": list(context.knowledge_base_ids or []),
            "use_web_search": bool(context.use_web_search),
            "selected_tool_ids": list(context.selected_tool_ids or []),
        }
        if context.preset_id:
            payload["preset_id"] = context.preset_id
        return self._request("POST", "/api/v1/assistant/chats", json_body=payload)

    def create_run(
        self,
        chat_id: str,
        task: GoldenTask,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """创建任务 run 并写入评测上下文。

        Args:
            chat_id: 会话 ID。
            task: Golden 任务。
            context: 已合并评测字段的请求上下文。

        Returns:
            创建后的 run 文档。
        """
        last_message = task.messages[-1]
        history = [
            {"role": item.role, "content": item.content}
            for item in task.messages[:-1]
        ]
        return self._request(
            "POST",
            f"/api/v1/assistant/chats/{chat_id}/runs",
            json_body={
                "content": last_message.content,
                "messages": history,
                "context": context,
            },
        )

    def get_run(self, run_id: str) -> dict[str, Any]:
        """读取 run 详情（含持久化事件）。"""
        return self._request("GET", f"/api/v1/assistant/runs/{run_id}")

    def get_tool_call(self, call_id: str) -> dict[str, Any]:
        """读取工具调用详情。"""
        return self._request("GET", f"/api/v1/assistant/tool-calls/{call_id}")

    def confirm_tool_call(self, call_id: str) -> dict[str, Any]:
        """确认参数齐全的工具提案。"""
        return self._request(
            "POST",
            f"/api/v1/assistant/tool-calls/{call_id}/confirm",
            json_body={},
        )

    def delete_chat(self, chat_id: str) -> None:
        """删除会话；失败时不阻断录制结果。"""
        try:
            self._request("DELETE", f"/api/v1/assistant/chats/{chat_id}")
        except Exception:
            pass


def wait_for_terminal_run(
    client: LuiCaptureClient,
    run_id: str,
    *,
    deadline: float,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """轮询 run 直到终态。

    Args:
        client: LUI HTTP 客户端。
        run_id: run ID。
        deadline: 截止时间戳（time.monotonic）。
        poll_interval: 轮询间隔秒数。

    Returns:
        终态 run 文档。

    Raises:
        TimeoutError: 超过截止时间仍未终态时抛出。
    """
    while True:
        run = client.get_run(run_id)
        if str(run.get("status") or "") in RUN_TERMINAL_STATUSES:
            return run
        if time.monotonic() >= deadline:
            raise TimeoutError(f"run {run_id} not terminal after timeout, status={run.get('status')}")
        time.sleep(poll_interval)


def wait_for_continuation(
    client: LuiCaptureClient,
    call_id: str,
    *,
    deadline: float,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """确认工具提案后等待服务端续答完成。

    Args:
        client: LUI HTTP 客户端。
        call_id: 已确认的工具调用 ID。
        deadline: 截止时间戳。
        poll_interval: 轮询间隔秒数。

    Raises:
        TimeoutError: 续答 run 超时或未终态时抛出。
    """
    continuation_run_id = ""
    while True:
        call = client.get_tool_call(call_id)
        if continuation_run_id:
            run = client.get_run(continuation_run_id)
            if str(run.get("status") or "") in RUN_TERMINAL_STATUSES:
                if str(run.get("status") or "") != "completed":
                    raise RuntimeError(
                        f"continuation run {continuation_run_id} failed: {run.get('error')}"
                    )
                return
        elif str(call.get("continuation_run_id") or ""):
            continuation_run_id = str(call["continuation_run_id"])
            continue
        elif str(call.get("continuation_state") or "") in CONTINUATION_TERMINAL_STATES:
            return
        if time.monotonic() >= deadline:
            raise TimeoutError(
                f"continuation for call {call_id} not finished, "
                f"phase={call.get('phase')} state={call.get('continuation_state')}"
            )
        time.sleep(poll_interval)


def execute_task(
    client: LuiCaptureClient,
    task: GoldenTask,
    *,
    evaluation_id: str,
    evaluation_version: str,
    provider_id: str | None,
    model_id: str | None,
    timeout_seconds: float,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, Any]:
    """执行单条 Golden 任务并返回录制记录。

    Args:
        client: LUI HTTP 客户端。
        task: Golden 任务。
        evaluation_id: 评测批次 ID。
        evaluation_version: 数据集版本。
        provider_id: 固定 provider ID。
        model_id: 固定模型 ID。
        timeout_seconds: 单任务超时秒数。
        poll_interval: 轮询间隔秒数。

    Returns:
        包含 task_id / chat_id / run_id / ok / error 的执行记录。
    """
    record: dict[str, Any] = {
        "task_id": task.id,
        "chat_id": "",
        "run_id": "",
        "ok": False,
        "confirmed_calls": [],
        "error": "",
    }
    try:
        chat = client.create_chat(task, evaluation_id)
        record["chat_id"] = str(chat.get("chat_id") or "")
        context = build_run_context(
            task,
            evaluation_id=evaluation_id,
            evaluation_version=evaluation_version,
            provider_id=provider_id,
            model_id=model_id,
        )
        run = client.create_run(record["chat_id"], task, context)
        record["run_id"] = str(run.get("run_id") or "")
        deadline = time.monotonic() + timeout_seconds
        run = wait_for_terminal_run(
            client,
            record["run_id"],
            deadline=deadline,
            poll_interval=poll_interval,
        )
        if str(run.get("status") or "") != "completed":
            raise RuntimeError(f"run failed: {run.get('error') or run.get('status')}")
        for call_id in final_tool_call_ids(run):
            call = client.get_tool_call(call_id)
            if not should_auto_confirm(call):
                continue
            client.confirm_tool_call(call_id)
            record["confirmed_calls"].append(call_id)
            wait_for_continuation(
                client,
                call_id,
                deadline=deadline,
                poll_interval=poll_interval,
            )
        record["ok"] = True
    except Exception as exc:  # noqa: BLE001
        record["error"] = str(exc)
    return record


def write_facts(
    facts_dir: Path,
    records: list[dict[str, Any]],
    captured: dict[str, Any],
) -> list[str]:
    """把录制事实写入 fixtures 目录。

    Args:
        facts_dir: facts 输出目录。
        records: 任务执行记录；仅成功任务会写盘。
        captured: capture_facts_by_evaluation 返回的 task_id -> facts 映射。

    Returns:
        成功写盘的任务 ID 列表。
    """
    ok_tasks = {str(item["task_id"]) for item in records if item.get("ok")}
    facts_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for task_id in sorted(ok_tasks):
        facts = captured.get(task_id)
        if facts is None:
            continue
        path = facts_dir / f"{task_id}.json"
        path.write_text(facts.model_dump_json(indent=2), encoding="utf-8")
        written.append(task_id)
    return written


def build_parser() -> argparse.ArgumentParser:
    """构建命令行参数解析器。"""
    parser = argparse.ArgumentParser(description="Run recorded LUI golden tasks through the product chain")
    parser.add_argument("--evaluation-id", required=True, help="评测批次 ID，写入 run 上下文")
    parser.add_argument(
        "--dataset",
        default="backend/evaluation/lui/dataset",
        help="Golden Set 目录（默认 backend/evaluation/lui/dataset）",
    )
    parser.add_argument(
        "--facts-dir",
        default=None,
        help="录制事实输出目录（默认 backend/evaluation/lui/fixtures/<evaluation_id>）",
    )
    parser.add_argument("--categories", default=None, help="逗号分隔的 category 白名单")
    parser.add_argument("--only-task", default=None, help="只执行指定任务 ID，用于重跑失败任务")
    parser.add_argument("--limit", type=int, default=None, help="最多执行的任务数")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS, help="单任务超时秒数")
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL_SECONDS, help="轮询间隔秒数")
    parser.add_argument("--base-url", default="http://127.0.0.1:5201", help="后端地址")
    parser.add_argument("--username", default=None, help="登录用户名；缺省读 LUI_EVAL_USERNAME")
    parser.add_argument("--password", default=None, help="登录密码；缺省读 LUI_EVAL_PASSWORD")
    parser.add_argument("--provider-id", default=None, help="固定 provider ID，保证同一批次模型可比")
    parser.add_argument("--model-id", default=None, help="固定模型 ID，保证同一批次模型可比")
    parser.add_argument("--cleanup-chats", action="store_true", help="录制完成后删除任务会话")
    return parser


def main(argv: list[str] | None = None) -> int:
    """执行录制并输出任务级结果。

    Args:
        argv: 命令行参数；None 时读取 sys.argv。

    Returns:
        进程退出码；存在失败任务时返回 1。
    """
    args = build_parser().parse_args(argv)
    username = args.username or os.getenv("LUI_EVAL_USERNAME")
    password = args.password or os.getenv("LUI_EVAL_PASSWORD")
    if not username or not password:
        print("缺少登录信息：请传 --username/--password 或设置 LUI_EVAL_USERNAME/LUI_EVAL_PASSWORD", file=sys.stderr)
        return 2
    load_backend_env()
    dataset_dir = Path(args.dataset)
    if not dataset_dir.is_absolute():
        dataset_dir = REPO_ROOT / dataset_dir
    tasks = select_tasks(
        load_dataset(dataset_dir),
        categories=args.categories.split(",") if args.categories else None,
        only_task=args.only_task,
        limit=args.limit,
    )
    facts_dir = (
        Path(args.facts_dir)
        if args.facts_dir
        else BACKEND_PATH / "evaluation" / "lui" / "fixtures" / args.evaluation_id
    )
    client = LuiCaptureClient(args.base_url)
    client.login(username, password)
    records: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        print(f"[{index}/{len(tasks)}] capturing {task.id} ({task.category}) ...", flush=True)
        record = execute_task(
            client,
            task,
            evaluation_id=args.evaluation_id,
            evaluation_version=DATASET_VERSION,
            provider_id=args.provider_id,
            model_id=args.model_id,
            timeout_seconds=args.timeout,
            poll_interval=args.poll_interval,
        )
        records.append(record)
        status = "PASS" if record["ok"] else f"FAIL: {record['error']}"
        print(f"[{index}/{len(tasks)}] {task.id} {status}", flush=True)
    captured = capture_facts_by_evaluation(args.evaluation_id)
    written = write_facts(facts_dir, records, captured)
    if args.cleanup_chats:
        for record in records:
            if record.get("chat_id"):
                client.delete_chat(str(record["chat_id"]))
    failures = [record for record in records if not record.get("ok")]
    print(f"evaluation_id: {args.evaluation_id}")
    print(f"tasks: {len(records)}; passed: {len(records) - len(failures)}; failed: {len(failures)}")
    print(f"facts_written: {len(written)}")
    print(f"facts_dir: {facts_dir}")
    for record in failures:
        print(f"failed_task: {record['task_id']} error={record['error']}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
