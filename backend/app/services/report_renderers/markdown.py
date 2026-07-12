"""Markdown report renderer."""

from __future__ import annotations

from typing import Any


class MarkdownReportRenderer:
    """Render structured report JSON to Markdown."""

    def render(self, report: dict[str, Any]) -> str:
        lines: list[str] = [f"# {report.get('title') or '研发运行报告'}", ""]
        self._section(lines, "摘要", report.get("abstract") or "")
        self._section(lines, "研发任务与目标", self._traceability_text(report.get("traceability") or {}))
        self._section(lines, "方法与数据来源", self._list_text(report.get("methods") or []))
        self._section(lines, "阶段过程与追溯", self._traceability_text(report.get("traceability") or {}))
        self._section(lines, "结果汇总", self._results_text(report.get("results") or []))
        self._section(lines, "关键发现", self._findings_text(report.get("key_findings") or []))
        self._section(lines, "局限性与风险", self._list_text(report.get("limitations") or []))
        self._section(lines, "下一步建议", self._list_text(report.get("next_steps") or []))
        appendices = []
        if report.get("data_availability"):
            appendices.append(f"数据可用性：{self._plain(report['data_availability'])}")
        if report.get("reviewer_qa"):
            appendices.append(f"审稿式自检：{self._plain(report['reviewer_qa'])}")
        if report.get("literature_background"):
            appendices.append(f"文献背景：{self._plain(report['literature_background'])}")
        if report.get("citation_map"):
            appendices.append(f"引用映射：{self._plain(report['citation_map'])}")
        if report.get("figure_placeholders"):
            appendices.append(f"图表规格：{self._plain(report['figure_placeholders'])}")
        self._section(lines, "附录", "\n".join(appendices))
        return "\n".join(lines).rstrip() + "\n"

    def _section(self, lines: list[str], title: str, body: str) -> None:
        lines.extend([f"## {title}", "", body.strip() or "暂无。", ""])

    def _list_text(self, items: list[Any]) -> str:
        if not items:
            return ""
        return "\n".join(f"- {self._plain(item)}" for item in items)

    def _findings_text(self, items: list[Any]) -> str:
        lines = []
        for item in items:
            if isinstance(item, dict):
                evidence = item.get("evidence") or []
                suffix = f"（证据：{', '.join(map(str, evidence))}）" if evidence else ""
                lines.append(f"- {item.get('finding') or self._plain(item)}{suffix}")
            else:
                lines.append(f"- {self._plain(item)}")
        return "\n".join(lines)

    def _results_text(self, items: list[Any]) -> str:
        lines = []
        for item in items:
            if isinstance(item, dict):
                name = item.get("name") or "结果"
                summary = item.get("summary") or self._plain(item)
                lines.append(f"- **{name}**：{summary}")
            else:
                lines.append(f"- {self._plain(item)}")
        return "\n".join(lines)

    def _traceability_text(self, value: dict[str, Any]) -> str:
        if not value:
            return ""
        return "\n".join(f"- `{key}`: {self._plain(item)}" for key, item in value.items())

    def _plain(self, value: Any) -> str:
        if isinstance(value, (dict, list)):
            return str(value)
        return str(value)
