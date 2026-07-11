"""HTML-to-PDF renderer backed by Playwright Chromium."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright


class PdfCompiler:
    """Print controlled HTML to a PDF file."""

    def __init__(self, *, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = timeout_seconds

    def compile(self, html: str, *, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        pdf_path = output_dir / "report.pdf"
        try:
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                page = browser.new_page()
                page.set_default_timeout(self.timeout_seconds * 1000)
                page.set_content(html, wait_until="load")
                page.pdf(path=str(pdf_path), format="A4", print_background=True, prefer_css_page_size=True)
                browser.close()
        except Exception as exc:
            return {
                "status": "failed",
                "pdf_path": None,
                "log": f"HTML-to-PDF rendering failed: {type(exc).__name__}: {exc}",
            }
        if pdf_path.exists() and pdf_path.read_bytes().startswith(b"%PDF"):
            return {
                "status": "completed",
                "pdf_path": pdf_path,
                "log": "Playwright Chromium rendered report.pdf",
            }
        return {
            "status": "failed",
            "pdf_path": None,
            "log": "HTML-to-PDF renderer did not produce a valid PDF file.",
        }
