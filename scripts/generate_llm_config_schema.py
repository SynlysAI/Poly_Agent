"""Generate LLM provider configuration schema docs from Pydantic models."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.llm_config_schema_service import write_config_schema_docs  # noqa: E402


def main() -> None:
    """生成 docs/llm-provider-config-schema.md 与同名 JSON。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PROJECT_ROOT,
        help="项目根目录，默认自动推断为仓库根目录。",
    )
    args = parser.parse_args()
    paths = write_config_schema_docs(args.project_root)
    print(f"markdown: {paths['markdown']}")
    print(f"json: {paths['json']}")


if __name__ == "__main__":
    main()
