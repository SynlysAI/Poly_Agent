"""LaTeX report renderer."""

from __future__ import annotations

from typing import Any


class LatexReportRenderer:
    """Render structured report JSON to a Chinese-friendly LaTeX document."""

    def render(self, report: dict[str, Any]) -> str:
        title = self._escape(str(report.get("title") or "研发运行报告"))
        sections = [
            ("摘要", report.get("abstract") or ""),
            ("研发任务与目标", self._plain(report.get("traceability") or {})),
            ("方法与数据来源", self._items(report.get("methods") or [])),
            ("阶段过程与追溯", self._plain(report.get("traceability") or {})),
            ("结果汇总", self._items(report.get("results") or [])),
            ("关键发现", self._items(report.get("key_findings") or [])),
            ("局限性与风险", self._items(report.get("limitations") or [])),
            ("下一步建议", self._items(report.get("next_steps") or [])),
            ("附录", self._appendix(report)),
        ]
        body = "\n\n".join(
            f"\\section{{{self._escape(section_title)}}}\n{self._escape(section_body) or '暂无。'}"
            for section_title, section_body in sections
        )
        return (
            "\\documentclass[UTF8]{article}\n"
            "\\usepackage{ctex}\n"
            "\\usepackage[a4paper,margin=2.5cm]{geometry}\n"
            "\\usepackage{hyperref}\n"
            f"\\title{{{title}}}\n"
            "\\author{Poly\\_Agent}\n"
            "\\date{\\today}\n"
            "\\begin{document}\n"
            "\\maketitle\n"
            f"{body}\n"
            "\\end{document}\n"
        )

    def _items(self, value: list[Any]) -> str:
        if not value:
            return ""
        return "\n".join(f"- {self._plain(item)}" for item in value)

    def _appendix(self, report: dict[str, Any]) -> str:
        parts = []
        if report.get("data_availability"):
            parts.append(f"数据可用性：{self._plain(report['data_availability'])}")
        if report.get("reviewer_qa"):
            parts.append(f"审稿式自检：{self._plain(report['reviewer_qa'])}")
        if report.get("literature_background"):
            parts.append(f"文献背景：{self._plain(report['literature_background'])}")
        if report.get("citation_map"):
            parts.append(f"引用映射：{self._plain(report['citation_map'])}")
        if report.get("figure_placeholders"):
            parts.append(f"图表规格：{self._plain(report['figure_placeholders'])}")
        return "\n".join(parts)

    def _plain(self, value: Any) -> str:
        if isinstance(value, dict):
            return "; ".join(f"{key}: {self._plain(item)}" for key, item in value.items())
        if isinstance(value, list):
            return "；".join(self._plain(item) for item in value)
        return str(value)

    def _escape(self, value: str) -> str:
        replacements = {
            "\\": "\\textbackslash{}",
            "&": "\\&",
            "%": "\\%",
            "$": "\\$",
            "#": "\\#",
            "_": "\\_",
            "{": "\\{",
            "}": "\\}",
            "~": "\\textasciitilde{}",
            "^": "\\textasciicircum{}",
        }
        return "".join(replacements.get(ch, ch) for ch in value)
