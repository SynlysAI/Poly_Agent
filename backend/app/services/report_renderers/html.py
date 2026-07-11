"""Safe HTML renderer for report previews and PDF output."""

from __future__ import annotations

from html import escape
from typing import Any


class HtmlReportRenderer:
    """Render validated report data as a self-contained printable document."""

    def render(self, report: dict[str, Any]) -> str:
        sections = [
            ("摘要", self._paragraph(report.get("abstract"))),
            ("研发任务与目标", self._mapping(report.get("traceability") or {})),
            ("方法与数据来源", self._list(report.get("methods") or [])),
            ("结果汇总", self._results(report.get("results") or [])),
            ("关键发现", self._findings(report.get("key_findings") or [])),
            ("局限性与风险", self._list(report.get("limitations") or [])),
            ("下一步建议", self._list(report.get("next_steps") or [])),
        ]
        body = "".join(f"<section><h2>{escape(title)}</h2>{content}</section>" for title, content in sections)
        return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><style>
@page {{ size: A4; margin: 18mm 16mm; }}
* {{ box-sizing: border-box; }}
body {{ color: #172033; font-family: "Noto Sans CJK SC", "Microsoft YaHei", sans-serif; font-size: 11pt; line-height: 1.65; }}
h1 {{ margin: 0 0 18px; font-size: 22pt; }} h2 {{ margin: 20px 0 8px; font-size: 14pt; border-bottom: 1px solid #d7dde8; padding-bottom: 4px; }}
p {{ margin: 0 0 8px; white-space: pre-wrap; }} ul {{ margin: 4px 0 8px; padding-left: 22px; }} li {{ margin: 3px 0; }}
.evidence {{ color: #5b6475; font-size: 9.5pt; }} code {{ overflow-wrap: anywhere; }}
</style></head><body><h1>{escape(str(report.get('title') or '研发运行报告'))}</h1>{body}</body></html>"""

    def _paragraph(self, value: Any) -> str:
        return f"<p>{escape(str(value or '暂无。'))}</p>"

    def _list(self, values: list[Any]) -> str:
        return "<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in values) + "</ul>"

    def _mapping(self, value: dict[str, Any]) -> str:
        return self._list([f"{key}: {item}" for key, item in value.items()]) if value else self._paragraph(None)

    def _results(self, values: list[Any]) -> str:
        items = []
        for item in values:
            if isinstance(item, dict):
                items.append(f"<strong>{escape(str(item.get('name') or '结果'))}</strong>：{escape(str(item.get('summary') or ''))}")
        return "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"

    def _findings(self, values: list[Any]) -> str:
        items = []
        for item in values:
            if not isinstance(item, dict):
                continue
            evidence = ", ".join(map(str, item.get("evidence") or []))
            items.append(
                f"<li>{escape(str(item.get('finding') or ''))}"
                f"<div class=\"evidence\">证据：{escape(evidence)}</div></li>"
            )
        return "<ul>" + "".join(items) + "</ul>"
