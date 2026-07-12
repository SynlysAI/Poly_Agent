#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.corpus import build_manifest, extract_notebook_dois, resolve_unpaywall, search_openalex, verify_crossref


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the auditable KrF photoresist corpus manifest")
    parser.add_argument("--notebook", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--email", required=True, help="Contact email sent to OpenAlex")
    parser.add_argument("--target", type=int, default=30)
    args = parser.parse_args()

    notebook_dois = set(extract_notebook_dois(args.notebook))
    records = search_openalex(email=args.email)
    for record in records:
        record_doi = str(record.get("doi") or "").removeprefix("https://doi.org/").lower()
        record["present_in_legacy_notebook"] = bool(record_doi and record_doi in notebook_dois)
    manifest = build_manifest(records, target=args.target)
    for item in manifest["items"]:
        if not item["selected"]:
            continue
        item.update(verify_crossref(item["doi"], email=args.email))
        if item["approval_status"] == "pending":
            oa = resolve_unpaywall(item["doi"], email=args.email)
            if oa.get("fulltext_url"):
                item.update(source_kind="unpaywall", source_url=oa["fulltext_url"],
                            license=oa.get("license"), approval_status="approved", exclusion_reason=None)
    manifest["summary"]["approved_selected_count"] = sum(
        item["selected"] and item["approval_status"] == "approved" for item in manifest["items"]
    )
    manifest["summary"]["pending_authorized_upload_count"] = sum(
        item["selected"] and item["approval_status"] == "pending" for item in manifest["items"]
    )
    manifest["legacy_notebook_doi_count"] = len(notebook_dois)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
