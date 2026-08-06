"""平台串通仿真：把 PI mock 接口注册为远程接口型垂类模型并跑通
登录 → 注册 → 测试 → 激活 → AlgorithmRun → 实验转发预览 → 下发配置评估。

用法：
    conda run -n poly_agent python platform_e2e.py

前置条件：
    1. 后端已启动（默认 http://127.0.0.1:5100），且 backend/.env 已配置
       REMOTE_INTERFACE_ALLOW_PRIVATE_NETWORK=true；
    2. mock 服务已启动（默认 http://127.0.0.1:8300）。
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import httpx

BASE_URL = os.getenv("POLY_AGENT_BASE_URL", "http://127.0.0.1:5100").rstrip("/")
API = f"{BASE_URL}/api/v1"
USERNAME = os.getenv("POLY_AGENT_USERNAME", "admin")
PASSWORD = os.getenv("POLY_AGENT_PASSWORD", "admin123456")

ROOT = Path(__file__).resolve().parent
INTERFACE_PAYLOAD_PATH = ROOT / "payloads" / "pi_interface.json"
SAMPLE_INPUT_PATH = ROOT / "sample_input.json"


class E2EError(RuntimeError):
    pass


def api(client: httpx.Client, method: str, path: str, payload=None, *, expect_ok: bool = True):
    response = client.request(method, f"{API}{path}", json=payload)
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text}
    if expect_ok and (response.status_code >= 400 or body.get("code") not in (0, None)):
        raise E2EError(f"{method} {path} 失败: HTTP {response.status_code} {json.dumps(body, ensure_ascii=False)[:500]}")
    return body


def main() -> int:
    interface_payload = json.loads(INTERFACE_PAYLOAD_PATH.read_text(encoding="utf-8"))
    sample_input = json.loads(SAMPLE_INPUT_PATH.read_text(encoding="utf-8"))
    algorithm_id = interface_payload["algorithm_id"]

    with httpx.Client(timeout=60.0) as client:
        # 1. 登录
        login = api(client, "POST", "/auth/login", {"username": USERNAME, "password": PASSWORD})
        token = login["data"]["access_token"]
        client.headers["Authorization"] = f"Bearer {token}"
        print("[1/7] 登录成功:", login["data"]["username"])

        # 2. 注册远程接口（已存在则直接复用）
        created = api(client, "POST", "/research-engine/algorithm-interfaces", interface_payload, expect_ok=False)
        if created.get("code") == 0:
            version_id = created["data"]["version"]["version_id"]
            print("[2/7] 注册远程接口成功:", algorithm_id, version_id)
        elif "已存在" in json.dumps(created, ensure_ascii=False):
            existing = api(client, "GET", f"/research-engine/algorithm-interfaces/{algorithm_id}")
            version_id = existing["data"]["version"]["version_id"]
            print("[2/7] 接口已存在，复用版本:", version_id)
        else:
            raise E2EError(f"注册远程接口失败: {json.dumps(created, ensure_ascii=False)[:500]}")

        # 3. 真实调用测试
        tested = api(
            client,
            "POST",
            f"/research-engine/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
            {"input_snapshot": sample_input},
        )
        test_data = tested["data"]
        if not test_data["ok"]:
            raise E2EError(f"接口测试失败: {json.dumps(test_data, ensure_ascii=False)[:500]}")
        print(f"[3/7] 接口真实调用成功: HTTP {test_data['status_code']}, 延迟 {test_data['latency_ms']}ms")

        # 4. 激活版本
        activated = api(
            client,
            "POST",
            f"/research-engine/algorithms/{algorithm_id}/versions/{version_id}:activate",
        )
        print("[4/7] 激活成功:", activated["data"]["status"])

        # 5. 创建 AlgorithmRun
        run = api(
            client,
            "POST",
            "/research-engine/algorithm-runs",
            {
                "algorithm_id": algorithm_id,
                "algorithm_version_id": version_id,
                "trigger_source": "human_workflow",
                "input_snapshot": sample_input,
            },
        )
        run_data = run["data"]
        if run_data["status"] != "completed":
            raise E2EError(f"AlgorithmRun 未完成: {json.dumps(run_data, ensure_ascii=False)[:500]}")
        run_id = run_data["run_id"]
        output_summary = run_data["output_summary"]
        print(f"[5/7] AlgorithmRun 完成: {run_id}, D={output_summary.get('difficulty_score')}, "
              f"process={output_summary.get('selected_process', {}).get('process_id')}")

        # 6. 实验转发预览（模板 pi_synthesis → chasm/graphml 路径）
        preview = api(
            client,
            "POST",
            f"/algorithm-runs/{run_id}/experiment-dispatches/preview",
            {"template_id": "pi_synthesis", "experiment_name": "PI mock 仿真实验", "parameter_overrides": {}},
        )
        execution_inputs = preview["data"]["execution_inputs"]
        instruction_set_path = execution_inputs["instruction_set_path"]
        hardware_graph_path = execution_inputs["hardware_graph_path"]
        if not instruction_set_path.startswith("ChASM/PI-P") or not instruction_set_path.endswith(".chasm"):
            raise E2EError(f"指令集路径不符合预期: {instruction_set_path}")
        if hardware_graph_path != "graph/test_ClosedLoop_PI_1024.graphml":
            raise E2EError(f"硬件图路径不符合预期: {hardware_graph_path}")
        print(f"[6/7] 实验转发预览: variant={preview['data']['template']['variant_id']}")
        print(f"      instruction_set_path = {instruction_set_path}")
        print(f"      hardware_graph_path  = {hardware_graph_path}")

        # 7. 下发配置评估（pi_synthesis_dispatch → SpecLabOS 请求 payload）
        evaluation = api(
            client,
            "POST",
            "/experiment-dispatch-profile-evaluations",
            {
                "run_id": run_id,
                "profile_id": "pi_synthesis_dispatch",
                "profile_version": "1.0.0",
                "manual_values": {},
            },
        )
        result = evaluation["data"]["result"]
        if not result["is_valid"]:
            raise E2EError(f"下发配置评估无效: {json.dumps(result['errors'], ensure_ascii=False)[:500]}")
        payload = result["payload"]
        extra_metadata = payload.get("extra_metadata", {})
        profile_instruction = extra_metadata.get("instruction_set_path", "")
        conditions = payload.get("conditions", [])
        if not profile_instruction.startswith("ChASM/PI-P"):
            raise E2EError(f"下发 payload 指令集路径不符合预期: {profile_instruction}")
        if not conditions or not conditions[0].get("process_id"):
            raise E2EError(f"下发 payload conditions 缺少 selected_process: {json.dumps(conditions, ensure_ascii=False)[:300]}")
        print(f"[7/7] 下发配置评估成功: experiment_name={payload.get('experiment_name')}")
        print(f"      conditions={json.dumps(conditions, ensure_ascii=False)}")
        print(f"      instruction_set_path = {profile_instruction}")
        print(f"      hardware_graph_path  = {extra_metadata.get('hardware_graph_path')}")

    print("\n平台串通全链路 PASS")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except E2EError as exc:
        print(f"平台串通失败: {exc}")
        sys.exit(1)
