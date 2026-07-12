"""Report renderer tests."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.report_renderers.html import HtmlReportRenderer
from app.services.report_renderers.markdown import MarkdownReportRenderer
from app.services.report_renderers.pdf import PdfCompiler


STRUCTURED_REPORT = {
    "title": "研发运行报告",
    "abstract": "这是摘要。",
    "key_findings": [{"finding": "发现 A", "evidence": ["run_1"]}],
    "methods": ["方法 A"],
    "results": [{"name": "结果 A", "summary": "表现稳定"}],
    "traceability": {"subject_id": "run_1"},
    "limitations": ["局限 A"],
    "next_steps": ["下一步 A"],
    "data_availability": {"statement": "数据来自追溯上下文。"},
    "reviewer_qa": {"status": "pass", "missing_required_sections": []},
}


class ReportRendererTest(unittest.TestCase):
    def test_markdown_renderer_outputs_expected_sections(self) -> None:
        markdown = MarkdownReportRenderer().render(STRUCTURED_REPORT)

        self.assertTrue(markdown.startswith("# 研发运行报告"))
        self.assertIn("## 摘要", markdown)
        self.assertIn("## 方法与数据来源", markdown)
        self.assertIn("## 阶段过程与追溯", markdown)
        self.assertIn("## 下一步建议", markdown)

    def test_html_renderer_outputs_printable_document(self) -> None:
        html = HtmlReportRenderer().render(STRUCTURED_REPORT)

        self.assertIn("<!doctype html>", html)
        self.assertIn("@page", html)
        self.assertIn("研发运行报告", html)

    def test_pdf_compiler_outputs_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            result = PdfCompiler().compile(HtmlReportRenderer().render(STRUCTURED_REPORT), output_dir=tmp_path)

            self.assertEqual(result["status"], "completed")
            self.assertTrue(result["pdf_path"].read_bytes().startswith(b"%PDF"))
