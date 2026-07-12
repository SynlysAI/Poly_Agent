#!/usr/bin/env python3
"""Rename Poly Agent MinIO objects by copy-verify-delete.

Object stores do not provide atomic rename. This script performs a safe
sequence: copy to canonical key, verify size/ETag, write a manifest, upload the
manifest, then delete the legacy key.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BUCKET = "polymer-data"
MANIFEST_KEY = "poly_agent/manifests/minio_rename_manifest.json"
LOCAL_MANIFEST_PATH = Path(".runtime/data_catalog/minio_rename_manifest.json")


@dataclass(frozen=True)
class RenameMapping:
    """One object rename mapping."""

    dataset_id: str
    role: str
    legacy_key: str
    canonical_key: str


RENAME_MAPPINGS = [
    RenameMapping(
        dataset_id="radonpy_pi1070",
        role="readme",
        legacy_key="01_RadonPy/01_RadonPy_README(1).md",
        canonical_key="poly_agent/datasets/radonpy_pi1070/docs/readme.md",
    ),
    RenameMapping(
        dataset_id="radonpy_pi1070",
        role="raw_table",
        legacy_key="01_RadonPy/PI1070.xlsx",
        canonical_key="poly_agent/datasets/radonpy_pi1070/raw/pi1070.xlsx",
    ),
    RenameMapping(
        dataset_id="pi1m_v2",
        role="readme",
        legacy_key="02_PI1M/02_Pl1M_README(2).md",
        canonical_key="poly_agent/datasets/pi1m_v2/docs/readme.md",
    ),
    RenameMapping(
        dataset_id="pi1m_v2",
        role="raw_table",
        legacy_key="02_PI1M/PI1M_v2.csv",
        canonical_key="poly_agent/datasets/pi1m_v2/raw/pi1m_v2.csv",
    ),
    RenameMapping(
        dataset_id="openpoly",
        role="raw_table",
        legacy_key="OpenPoly/OpenPoly.csv",
        canonical_key="poly_agent/datasets/openpoly/raw/openpoly.csv",
    ),
    RenameMapping(
        dataset_id="openpoly",
        role="requirements_doc",
        legacy_key="OpenPoly/PolyAgent模型与数据集成需求收集表.docx",
        canonical_key="poly_agent/datasets/openpoly/docs/integration_requirements.docx",
    ),
]


class S3Client:
    """Minimal S3/MinIO client for object rename operations."""

    def __init__(self, *, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        normalized = endpoint.strip().rstrip("/")
        if normalized and not normalized.startswith(("http://", "https://")):
            normalized = f"{'https' if secure else 'http'}://{normalized}"
        self.endpoint = normalized
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = "us-east-1"
        self.service = "s3"

    def head_object(self, bucket: str, object_key: str) -> dict[str, Any] | None:
        """Return object metadata or None if the object is missing."""
        request = self._signed_request("HEAD", bucket, object_key)
        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                return {
                    "size_bytes": int(response.headers.get("Content-Length") or 0),
                    "etag": (response.headers.get("ETag") or "").strip('"'),
                    "last_modified": response.headers.get("Last-Modified"),
                }
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def copy_object(self, bucket: str, source_key: str, target_key: str) -> None:
        """Copy source object to target key."""
        copy_source = f"/{bucket}/{urllib.parse.quote(source_key, safe='/-_.~')}"
        request = self._signed_request(
            "PUT",
            bucket,
            target_key,
            headers={"x-amz-copy-source": copy_source},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()

    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        """Upload object content."""
        request = self._signed_request(
            "PUT",
            bucket,
            object_key,
            body=content,
            headers={"content-type": content_type},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def delete_object(self, bucket: str, object_key: str) -> None:
        """Delete one object."""
        request = self._signed_request("DELETE", bucket, object_key)
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def _signed_request(
        self,
        method: str,
        bucket: str,
        object_key: str,
        *,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> urllib.request.Request:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        parsed_endpoint = urllib.parse.urlparse(self.endpoint)
        host = parsed_endpoint.netloc
        canonical_uri = f"/{bucket}/{urllib.parse.quote(object_key, safe='/-_.~')}"
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        date_stamp = amz_date[:8]
        payload_hash = hashlib.sha256(body).hexdigest()
        signed_headers_map = {
            "host": host,
            "x-amz-content-sha256": payload_hash,
            "x-amz-date": amz_date,
            **headers,
        }
        signed_header_keys = sorted(signed_headers_map)
        canonical_headers = "".join(
            f"{key}:{str(signed_headers_map[key]).strip()}\n" for key in signed_header_keys
        )
        signed_headers = ";".join(signed_header_keys)
        canonical_request = "\n".join(
            [method, canonical_uri, "", canonical_headers, signed_headers, payload_hash]
        )
        credential_scope = f"{date_stamp}/{self.region}/{self.service}/aws4_request"
        string_to_sign = "\n".join(
            [
                "AWS4-HMAC-SHA256",
                amz_date,
                credential_scope,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            ]
        )
        signature = hmac.new(self._signing_key(date_stamp), string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            "AWS4-HMAC-SHA256 "
            f"Credential={self.access_key}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request_headers = {
            key: value
            for key, value in signed_headers_map.items()
            if key != "host"
        }
        request_headers["Authorization"] = authorization
        return urllib.request.Request(
            f"{self.endpoint}{canonical_uri}",
            method=method,
            headers=request_headers,
            data=body if method in {"PUT", "POST"} else None,
        )

    def _signing_key(self, date_stamp: str) -> bytes:
        def sign(key: bytes, message: str) -> bytes:
            return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

        date_key = sign(("AWS4" + self.secret_key).encode("utf-8"), date_stamp)
        region_key = sign(date_key, self.region)
        service_key = sign(region_key, self.service)
        return sign(service_key, "aws4_request")


def verify_match(source: dict[str, Any], target: dict[str, Any]) -> tuple[bool, str | None]:
    """Verify copied object metadata."""
    if source.get("size_bytes") != target.get("size_bytes"):
        return False, "size mismatch"
    source_etag = source.get("etag") or ""
    target_etag = target.get("etag") or ""
    if "-" in source_etag or "-" in target_etag:
        return True, None
    if source_etag and target_etag and source_etag != target_etag:
        return False, "etag mismatch"
    return True, None


def build_manifest(records: list[dict[str, Any]], *, bucket: str, apply: bool) -> dict[str, Any]:
    """Build rename manifest JSON payload."""
    return {
        "operation": "poly_agent_minio_object_rename",
        "bucket": bucket,
        "applied": apply,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "manifest_key": MANIFEST_KEY,
        "records": records,
    }


def execute_rename(client: S3Client, *, bucket: str, apply: bool) -> dict[str, Any]:
    """Execute or preview the rename plan."""
    records: list[dict[str, Any]] = []
    for mapping in RENAME_MAPPINGS:
        source = client.head_object(bucket, mapping.legacy_key)
        target = client.head_object(bucket, mapping.canonical_key)
        record = {
            **asdict(mapping),
            "source_exists": source is not None,
            "target_exists": target is not None,
            "source": source,
            "target": target,
            "status": "planned",
            "error": None,
        }

        if not apply:
            records.append(record)
            continue

        try:
            if source is None and target is None:
                record["status"] = "missing_source_and_target"
            elif source is None and target is not None:
                record["status"] = "already_migrated"
            else:
                if target is None:
                    client.copy_object(bucket, mapping.legacy_key, mapping.canonical_key)
                    target = client.head_object(bucket, mapping.canonical_key)
                    record["target"] = target
                    record["target_exists"] = target is not None
                if target is None:
                    record["status"] = "copy_failed"
                    record["error"] = "target missing after copy"
                else:
                    matched, error = verify_match(source, target)
                    if not matched:
                        record["status"] = "verify_failed"
                        record["error"] = error
                    else:
                        client.delete_object(bucket, mapping.legacy_key)
                        record["status"] = "renamed"
        except Exception as exc:  # noqa: BLE001 - manifest must preserve per-object failure.
            record["status"] = "failed"
            record["error"] = f"{exc.__class__.__name__}: {exc}"
        records.append(record)

    manifest = build_manifest(records, bucket=bucket, apply=apply)
    if apply:
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
        LOCAL_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
        LOCAL_MANIFEST_PATH.write_bytes(manifest_bytes)
        client.put_object(bucket, MANIFEST_KEY, manifest_bytes, "application/json; charset=utf-8")
    return manifest


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("MINIO_ENDPOINT", ""))
    parser.add_argument("--access-key", default=os.getenv("MINIO_ACCESS_KEY", ""))
    parser.add_argument("--secret-key", default=os.getenv("MINIO_SECRET_KEY", ""))
    parser.add_argument("--bucket", default=os.getenv("MINIO_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--secure", action="store_true", default=os.getenv("MINIO_SECURE", "false").lower() == "true")
    parser.add_argument("--apply", action="store_true", help="perform copy-verify-delete and write/upload manifest")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv or sys.argv[1:])
    if not args.endpoint or not args.access_key or not args.secret_key:
        print("MINIO_ENDPOINT, MINIO_ACCESS_KEY, and MINIO_SECRET_KEY are required", file=sys.stderr)
        return 2
    client = S3Client(
        endpoint=args.endpoint,
        access_key=args.access_key,
        secret_key=args.secret_key,
        secure=args.secure,
    )
    manifest = execute_rename(client, bucket=args.bucket, apply=args.apply)
    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode} MinIO rename plan for bucket {args.bucket}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    if args.apply:
        failed = [record for record in manifest["records"] if record["status"] in {"failed", "verify_failed", "copy_failed"}]
        return 1 if failed else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
