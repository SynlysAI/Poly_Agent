"""Deterministic mock report provider for tests and local demos."""

from __future__ import annotations

from typing import Any


class MockReportProvider:
    """Return a deterministic structured report without external LLM calls."""

    name = "mock"

    def __init__(self, *, model: str | None = None) -> None:
        self.model = model or "mock-report-model"

    def complete_json(
        self,
        *,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        options: dict[str, Any],
    ) -> dict[str, Any]:
        context = dict(options.get("context") or {})
        subject = dict(context.get("subject") or {})
        subject_type = subject.get("subject_type") or "research_run"
        subject_id = subject.get("subject_id") or "unknown"
        return {
            "title": "研发运行报告",
            "abstract": f"本报告基于 {subject_type} {subject_id} 的追溯上下文自动生成，用于本地演示和测试。",
            "key_findings": [
                {
                    "finding": "报告上下文已成功收集。",
                    "evidence": [subject_id],
                    "confidence": "mock",
                }
            ],
            "methods": [
                "收集运行输入、输出、关联计算和审计事件。",
                "对敏感字段和本地路径进行脱敏。",
            ],
            "results": [
                {
                    "name": "运行摘要",
                    "summary": "mock provider 未调用外部模型，仅返回确定性结构化内容。",
                }
            ],
            "traceability": {
                "subject_type": subject_type,
                "subject_id": subject_id,
                "context_keys": sorted(context.keys()),
            },
            "limitations": [
                "mock provider 只用于开发、测试和前端联调，不代表真实科研写作质量。"
            ],
            "next_steps": [
                "接入真实 provider 后重新生成正式报告。",
            ],
            "tables": [],
            "figure_placeholders": [],
            "appendices": [],
        }
