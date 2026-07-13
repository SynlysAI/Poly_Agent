from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_import_script_rejects_empty_admin_api_key(tmp_path: Path) -> None:
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"corpus_id":"krf_photoresist","items":[]}', encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/import_approved_corpus.py",
            "--manifest",
            str(manifest),
            "--base-url",
            "http://127.0.0.1:8200",
            "--admin-api-key",
            "",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "--admin-api-key is required and cannot be empty" in result.stderr
