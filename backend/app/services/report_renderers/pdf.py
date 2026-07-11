"""PDF compiler for LaTeX report artifacts."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any


class PdfCompiler:
    """Compile LaTeX files to PDF when a local toolchain is available."""

    def __init__(self, *, engine: str = "xelatex", timeout_seconds: int = 120) -> None:
        self.engine = engine
        self.timeout_seconds = timeout_seconds

    def compile(self, tex_path: Path, *, output_dir: Path) -> dict[str, Any]:
        output_dir.mkdir(parents=True, exist_ok=True)
        command = self._command(tex_path, output_dir)
        if not command:
            return {
                "status": "failed",
                "pdf_path": None,
                "log": f"LaTeX engine not found: {self.engine}",
            }
        try:
            completed = subprocess.run(
                command,
                cwd=output_dir,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return {
                "status": "failed",
                "pdf_path": None,
                "log": f"PDF compilation timed out after {self.timeout_seconds}s: {exc}",
            }

        pdf_path = output_dir / f"{tex_path.stem}.pdf"
        log = (completed.stdout or "") + "\n" + (completed.stderr or "")
        if completed.returncode == 0 and pdf_path.exists():
            return {
                "status": "completed",
                "pdf_path": pdf_path,
                "log": log,
            }
        return {
            "status": "failed",
            "pdf_path": None,
            "log": log or f"PDF compilation failed with exit code {completed.returncode}",
        }

    def _command(self, tex_path: Path, output_dir: Path) -> list[str] | None:
        latexmk = shutil.which("latexmk")
        if latexmk:
            return [
                latexmk,
                "-xelatex",
                "-interaction=nonstopmode",
                "-halt-on-error",
                "-shell-escape=0",
                f"-outdir={output_dir}",
                str(tex_path),
            ]
        engine_path = shutil.which(self.engine)
        if not engine_path:
            return None
        return [
            engine_path,
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-no-shell-escape",
            f"-output-directory={output_dir}",
            str(tex_path),
        ]
