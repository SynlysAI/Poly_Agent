"""Resource configuration bridge for the PolyAgent Raman demo package."""

from __future__ import annotations

import os
import socket
from pathlib import Path


DEFAULT_RAMAN_RESOURCES_ROOTS = [
    Path("/home/fangyikai/github_project/Spec_Agent/backend/resources/raman"),
    Path("/home/fangyikai/code/Spec_Agent/backend/resources/raman"),
    Path("/home/fangyikai/code/Poly_Agent/backend/resources/raman"),
]
DEFAULT_RAMAN_RESOURCES_ROOT = DEFAULT_RAMAN_RESOURCES_ROOTS[0]

DEFAULT_RESOURCES = {
    "raman_checkpoints_root": "",
    "raman_database_root": "",
    "raman_tokenizer_root": "",
}

GLOBAL_CONFIG = {
    "resources": {
        **DEFAULT_RESOURCES,
    }
}


def configure_from_context(context: dict) -> dict:
    GLOBAL_CONFIG["resources"].update(DEFAULT_RESOURCES)
    resources = context.get("resource_assets") or {}
    root_path = (resources.get("raman_runtime_resources") or {}).get("path")
    if root_path:
        _configure_from_root(Path(root_path), validate=True)
        return GLOBAL_CONFIG

    env_root = os.getenv("RAMAN_RESOURCES_ROOT", "").strip()
    if env_root:
        _configure_from_root(Path(env_root), validate=True)
        return GLOBAL_CONFIG

    legacy_mapping = {
        "raman_checkpoints": "raman_checkpoints_root",
        "raman_database": "raman_database_root",
        "raman_tokenizer": "raman_tokenizer_root",
    }
    for asset_key, config_key in legacy_mapping.items():
        path = (resources.get(asset_key) or {}).get("path")
        if path:
            GLOBAL_CONFIG["resources"][config_key] = path

    legacy_checkpoint_root = os.getenv("RAMAN_CHECKPOINTS_ROOT", "").strip()
    if legacy_checkpoint_root and not GLOBAL_CONFIG["resources"]["raman_checkpoints_root"]:
        GLOBAL_CONFIG["resources"]["raman_checkpoints_root"] = legacy_checkpoint_root
    legacy_database_root = os.getenv("RAMAN_DATABASE_ROOT", "").strip()
    if legacy_database_root and not GLOBAL_CONFIG["resources"]["raman_database_root"]:
        GLOBAL_CONFIG["resources"]["raman_database_root"] = legacy_database_root
    legacy_tokenizer_root = os.getenv("RAMAN_TOKENIZER_ROOT", "").strip()
    if legacy_tokenizer_root and not GLOBAL_CONFIG["resources"]["raman_tokenizer_root"]:
        GLOBAL_CONFIG["resources"]["raman_tokenizer_root"] = legacy_tokenizer_root

    missing = [
        "raman_checkpoints",
        "raman_tokenizer",
    ]
    if GLOBAL_CONFIG["resources"]["raman_checkpoints_root"]:
        missing.remove("raman_checkpoints")
    if GLOBAL_CONFIG["resources"]["raman_tokenizer_root"]:
        missing.remove("raman_tokenizer")
    if missing:
        errors = []
        for default_root in DEFAULT_RAMAN_RESOURCES_ROOTS:
            try:
                _configure_from_root(default_root, validate=True)
                return GLOBAL_CONFIG
            except RuntimeError as exc:
                errors.append(str(exc))
        raise RuntimeError(
            "missing Raman service resources on backend host "
            f"{socket.gethostname()} (cwd={Path.cwd()}). Checked default roots: "
            f"{', '.join(str(path) for path in DEFAULT_RAMAN_RESOURCES_ROOTS)}. "
            f"Details: {' | '.join(errors)}"
        )
    return GLOBAL_CONFIG


def _configure_from_root(root: Path, *, validate: bool) -> None:
    root = root.expanduser()
    GLOBAL_CONFIG["resources"]["raman_checkpoints_root"] = str(root / "checkpoints")
    GLOBAL_CONFIG["resources"]["raman_database_root"] = str(root / "database")
    GLOBAL_CONFIG["resources"]["raman_tokenizer_root"] = str(_tokenizer_root(root))
    if validate:
        _validate_root(root)


def _tokenizer_root(root: Path) -> Path:
    moltokenizer = root / "moltokenizer"
    if (moltokenizer / "vocab.json").is_file():
        return moltokenizer
    return root / "tokenizer"


def _validate_root(root: Path) -> None:
    required_files = [
        root / "checkpoints" / "baseline_removal.pth",
        root / "checkpoints" / "raman_generation.pth",
    ]
    tokenizer_vocab_candidates = [
        root / "moltokenizer" / "vocab.json",
        root / "tokenizer" / "vocab.json",
    ]
    missing = [str(path) for path in required_files if not path.is_file()]
    if not any(path.is_file() for path in tokenizer_vocab_candidates):
        missing.append(
            "one of: "
            + ", ".join(str(path) for path in tokenizer_vocab_candidates)
        )
    if missing:
        raise RuntimeError(
            "missing Raman service resources. Set RAMAN_RESOURCES_ROOT to the Raman "
            f"resource root or place resources under {DEFAULT_RAMAN_RESOURCES_ROOT}. "
            f"Missing files: {', '.join(missing)}"
        )
