"""本地仿真：不经过平台，直接调用 PI mock 服务 /predict 证明接口可调用。

用法：
    conda run -n poly_agent python client_simulate.py
    conda run -n poly_agent python client_simulate.py --input other_input.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx


def main() -> int:
    parser = argparse.ArgumentParser(description="PI mock 接口本地仿真")
    parser.add_argument("--url", default="http://127.0.0.1:8300", help="mock 服务地址")
    parser.add_argument("--input", default=None, help="请求 JSON 文件路径（默认 sample_input.json）")
    args = parser.parse_args()

    base_url = args.url.rstrip("/")
    input_path = Path(args.input) if args.input else Path(__file__).resolve().parent / "sample_input.json"
    if not input_path.exists():
        print(f"请求文件不存在: {input_path}")
        return 2

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        health = client.get("/healthz")
        health.raise_for_status()
        print("healthz:", json.dumps(health.json(), ensure_ascii=False))

        payload = json.loads(input_path.read_text(encoding="utf-8"))
        response = client.post("/predict", json=payload)
        response.raise_for_status()
        output = response.json()

    print("\n/predict 响应：")
    print(json.dumps(output, ensure_ascii=False, indent=2))

    # 结构校验
    checks = []
    details = output["score_details"]
    r = details["R"]["R_total"]
    h = details["H"]["H_total"]
    s = details["S"]["S_total"]
    u = details["U"]["U_total"]
    d = output["calculation"]["total_difficulty_D"]
    checks.append(("D == R+H+S+U", d == r + h + s + u, f"D={d}, R+H+S+U={r + h + s + u}"))
    checks.append(("difficulty_score == D", output["difficulty_score"] == d, str(output["difficulty_score"])))

    process_id = output["selected_process"]["process_id"]
    rules_path = Path(__file__).resolve().parent / "PI_synthesis_difficulty_scoring_rules_v1.0.json"
    rules = json.loads(rules_path.read_text(encoding="utf-8"))
    expected = None
    for item in rules["selection_algorithm"]["initial_mapping"]:
        if item["D_min"] <= d <= item["D_max"]:
            expected = item["process_id"]
            break
    checks.append(("selected_process 与 D 区间一致", process_id == expected, f"{process_id} vs {expected}"))
    checks.append(("recommended_parameters 回显输入", output["recommended_parameters"]["diamine"] == payload["diamine"], ""))

    failed = 0
    for name, ok, detail in checks:
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        print(f"[{status}] {name}  ({detail})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
