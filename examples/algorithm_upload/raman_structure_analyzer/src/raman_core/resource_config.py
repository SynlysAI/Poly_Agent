"""Resource configuration bridge for the PolyAgent Raman demo package."""

from __future__ import annotations


GLOBAL_CONFIG = {
    "resources": {
        "raman_checkpoints_root": "",
        "raman_database_root": "",
        "raman_tokenizer_root": "",
    }
}


def configure_from_context(context: dict) -> dict:
    resources = context.get("resource_assets") or {}
    mapping = {
        "raman_checkpoints": "raman_checkpoints_root",
        "raman_database": "raman_database_root",
        "raman_tokenizer": "raman_tokenizer_root",
    }
    missing = []
    for asset_key, config_key in mapping.items():
        path = (resources.get(asset_key) or {}).get("path")
        if not path:
            missing.append(asset_key)
        else:
            GLOBAL_CONFIG["resources"][config_key] = path
    if missing:
        raise RuntimeError(f"missing managed Raman resources: {', '.join(missing)}")
    return GLOBAL_CONFIG
