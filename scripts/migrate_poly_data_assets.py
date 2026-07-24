#!/usr/bin/env python3
"""Migrate polymer data assets to MongoDB poly_data and MinIO datasets/ keys."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import stat
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid
from io import BytesIO
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings  # noqa: E402
from app.services.data_catalog_service import DATASET_DEFINITIONS, MINIO_OBJECT_MAPPINGS  # noqa: E402


DEFAULT_BUCKET = "polymer-data"
SOURCE_DATABASE = "ai4ms"
SOURCE_COLLECTION = "Poly_Agent"
TARGET_DATABASE = "poly_data"
TARGET_MATERIAL_COLLECTION = "material_records"
TARGET_RADONPY_COLLECTION = "radonpy_records"
TARGET_PI1M_COLLECTION = "pi1m_samples"
TARGET_SMIPOLY_COLLECTION = "smipoly_monomers"
TARGET_POLYUNIVERSE_COLLECTION = "polyuniverse_monomers"
TARGET_MD_ALLATOM_FILES_COLLECTION = "md_allatom_files"
TARGET_MD_ALLATOM_DIAMINES_COLLECTION = "md_allatom_diamines"
TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION = "md_allatom_dianhydrides"
TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION = "md_allatom_carbon_results"
TARGET_DATASET_STATS_COLLECTION = "dataset_stats"
TARGET_IMPORT_JOBS_COLLECTION = "import_jobs"
TARGET_IMPORT_CHECKPOINTS_COLLECTION = "import_checkpoints"
RADONPY_OBJECT_KEY = "datasets/radonpy_pi1070/raw/pi1070.xlsx"
PI1M_OBJECT_KEY = "datasets/pi1m_v2/raw/pi1m_v2.csv"
SMIPOLY_OBJECT_KEY = "datasets/smipoly/raw/202207_smip_monset.csv"
POLYUNIVERSE_OBJECT_KEYS = {
    "diCOOH.csv": "datasets/polyuniverse/raw/diCOOH.csv",
    "epoxy_diE.csv": "datasets/polyuniverse/raw/epoxy_diE.csv",
    "epoxy_diN.csv": "datasets/polyuniverse/raw/epoxy_diN.csv",
}
SFTP_DEFAULT_HOST = "10.26.15.53"
SFTP_DEFAULT_ROOT = "/polymer-multi-modal/open-databases/Processed_data"
MD_ALLATOM_DEFAULT_ROOT = "/polymer-multi-modal/MD-AllAtom"
MD_ALLATOM_DEFAULT_FAMILIES = ("C", "F", "Si")
DEFAULT_PI1M_SAMPLE_SIZE = 10000
DEFAULT_PI1M_CHUNK_SIZE = 50000
MANIFEST_KEY = "manifests/poly_data_manifest.json"
LOCAL_MANIFEST_PATH = Path(".runtime/data_catalog/poly_data_manifest.json")
MD_ALLATOM_STRUCTURED_OBJECT_KEYS = {
    "diamine": "datasets/md_allatom/structured/diamine.csv",
    "dianhydride": "datasets/md_allatom/structured/dianhydride.csv",
    "carbon": "datasets/md_allatom/structured/carbon.csv",
    "requirements_doc": "datasets/md_allatom/docs/integration_requirements.docx",
}


@dataclass(frozen=True)
class ObjectMigrationRecord:
    """One MinIO object migration mapping."""

    dataset_id: str
    role: str
    legacy_key: str | None
    object_key: str


@dataclass(frozen=True)
class SftpObjectMigrationRecord:
    """One remote SFTP file to canonical MinIO object mapping."""

    dataset_id: str
    role: str
    remote_relative_path: str
    object_key: str
    content_type: str


OBJECT_MIGRATIONS = [
    ObjectMigrationRecord(
        dataset_id=mapping.dataset_id,
        role=mapping.role,
        legacy_key=mapping.legacy_key,
        object_key=mapping.canonical_key,
    )
    for mapping in MINIO_OBJECT_MAPPINGS
    if mapping.legacy_key
]


SFTP_OBJECT_MIGRATIONS = [
    SftpObjectMigrationRecord(
        dataset_id="smipoly",
        role="readme",
        remote_relative_path="03_SMiPoly/03_SMiPoly_README(3).md",
        object_key="datasets/smipoly/docs/readme.md",
        content_type="text/markdown; charset=utf-8",
    ),
    SftpObjectMigrationRecord(
        dataset_id="smipoly",
        role="raw_table",
        remote_relative_path="03_SMiPoly/202207_smip_monset.csv",
        object_key=SMIPOLY_OBJECT_KEY,
        content_type="text/csv; charset=utf-8",
    ),
    SftpObjectMigrationRecord(
        dataset_id="polyuniverse",
        role="readme",
        remote_relative_path="04_PolyUniverse/04_PolyUniverse_README(4).md",
        object_key="datasets/polyuniverse/docs/readme.md",
        content_type="text/markdown; charset=utf-8",
    ),
    SftpObjectMigrationRecord(
        dataset_id="polyuniverse",
        role="raw_diCOOH",
        remote_relative_path="04_PolyUniverse/diCOOH.csv",
        object_key=POLYUNIVERSE_OBJECT_KEYS["diCOOH.csv"],
        content_type="text/csv; charset=utf-8",
    ),
    SftpObjectMigrationRecord(
        dataset_id="polyuniverse",
        role="raw_epoxy_diE",
        remote_relative_path="04_PolyUniverse/epoxy_diE.csv",
        object_key=POLYUNIVERSE_OBJECT_KEYS["epoxy_diE.csv"],
        content_type="text/csv; charset=utf-8",
    ),
    SftpObjectMigrationRecord(
        dataset_id="polyuniverse",
        role="raw_epoxy_diN",
        remote_relative_path="04_PolyUniverse/epoxy_diN.csv",
        object_key=POLYUNIVERSE_OBJECT_KEYS["epoxy_diN.csv"],
        content_type="text/csv; charset=utf-8",
    ),
]


class S3Client:
    """Minimal S3/MinIO client for migration operations."""

    def __init__(self, *, endpoint: str, access_key: str, secret_key: str, secure: bool) -> None:
        normalized = endpoint.strip().rstrip("/")
        if normalized and not normalized.startswith(("http://", "https://")):
            normalized = f"{'https' if secure else 'http'}://{normalized}"
        self.endpoint = normalized
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = "us-east-1"
        self.service = "s3"

    def is_configured(self) -> bool:
        return bool(self.endpoint and self.access_key and self.secret_key)

    def head_object(self, bucket: str, object_key: str) -> dict[str, Any] | None:
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
        copy_source = f"/{bucket}/{urllib.parse.quote(source_key, safe='/-_.~')}"
        request = self._signed_request("PUT", bucket, target_key, headers={"x-amz-copy-source": copy_source})
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()

    def put_object(self, bucket: str, object_key: str, content: bytes, content_type: str) -> None:
        request = self._signed_request("PUT", bucket, object_key, body=content, headers={"content-type": content_type})
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def delete_object(self, bucket: str, object_key: str) -> None:
        request = self._signed_request("DELETE", bucket, object_key)
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def get_object(self, bucket: str, object_key: str) -> bytes:
        """Download one object."""
        request = self._signed_request("GET", bucket, object_key)
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

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
        canonical_headers = "".join(f"{key}:{str(signed_headers_map[key]).strip()}\n" for key in signed_header_keys)
        signed_headers = ";".join(signed_header_keys)
        canonical_request = "\n".join([method, canonical_uri, "", canonical_headers, signed_headers, payload_hash])
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
        request_headers = {key: value for key, value in signed_headers_map.items() if key != "host"}
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


class SftpClient:
    """Read-only SFTP client for source dataset files."""

    def __init__(self, *, host: str, username: str, password: str, port: int = 22) -> None:
        import paramiko

        self._ssh = paramiko.SSHClient()
        self._ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._ssh.connect(hostname=host, port=port, username=username, password=password, timeout=20)
        self._sftp = self._ssh.open_sftp()

    def stat_file(self, remote_path: str) -> dict[str, Any]:
        attrs = self._sftp.stat(remote_path)
        return {
            "size_bytes": int(attrs.st_size or 0),
            "mtime": datetime.fromtimestamp(float(attrs.st_mtime or 0), tz=timezone.utc).isoformat(),
        }

    def read_file(self, remote_path: str) -> bytes:
        with self._sftp.open(remote_path, "rb") as fp:
            return fp.read()

    def list_files_recursive(self, remote_root: str) -> list[dict[str, Any]]:
        """Return all files under a remote directory with paths relative to the root."""
        root = remote_root.rstrip("/")
        files: list[dict[str, Any]] = []

        def walk(current: str) -> None:
            for attrs in self._sftp.listdir_attr(current):
                name = attrs.filename
                if name in {".", ".."}:
                    continue
                child = f"{current.rstrip('/')}/{name}"
                mode = int(attrs.st_mode or 0)
                if stat.S_ISDIR(mode):
                    walk(child)
                    continue
                if not stat.S_ISREG(mode):
                    continue
                files.append(
                    {
                        "remote_path": child,
                        "relative_path": child.removeprefix(root + "/"),
                        "size_bytes": int(attrs.st_size or 0),
                        "mtime": datetime.fromtimestamp(float(attrs.st_mtime or 0), tz=timezone.utc).isoformat(),
                    }
                )

        walk(root)
        return sorted(files, key=lambda item: item["relative_path"])

    def close(self) -> None:
        self._sftp.close()
        self._ssh.close()


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


def dataset_documents() -> list[dict[str, Any]]:
    """Return dataset-level metadata documents."""
    docs: list[dict[str, Any]] = []
    for dataset_id, definition in DATASET_DEFINITIONS.items():
        docs.append(
            {
                "dataset_id": dataset_id,
                "display_name": definition["display_name"],
                "source_category": definition["source_category"],
                "confidence_label": definition["confidence_label"],
                "description": definition["description"],
                "row_count": definition["row_count"],
                "column_count": definition["column_count"],
                "storage_prefix": definition["storage_prefix"],
                "updated_at": datetime.now(timezone.utc),
                **dataset_record_metadata(dataset_id),
            }
        )
    return docs


def dataset_record_metadata(dataset_id: str) -> dict[str, Any]:
    """Return dataset row-level import metadata."""
    if dataset_id == "openpoly":
        return {
            "record_collection_key": "poly_data.material_records",
            "record_mode": "full",
        }
    if dataset_id == "radonpy_pi1070":
        return {
            "record_collection_key": "poly_data.radonpy_records",
            "record_mode": "full",
        }
    if dataset_id == "pi1m_v2":
        return {
            "record_collection_key": "poly_data.pi1m_samples",
            "record_mode": "full",
        }
    if dataset_id == "smipoly":
        return {
            "record_collection_key": "poly_data.smipoly_monomers",
            "record_mode": "full",
        }
    if dataset_id == "polyuniverse":
        return {
            "record_collection_key": "poly_data.polyuniverse_monomers",
            "record_mode": "full",
        }
    if dataset_id == "md_allatom":
        return {
            "record_collection_key": "poly_data.md_allatom_carbon_results",
            "record_mode": "full",
        }
    return {"record_collection_key": None, "record_mode": "metadata_only"}


def field_documents() -> list[dict[str, Any]]:
    """Return field-level metadata documents."""
    docs: list[dict[str, Any]] = []
    for dataset_id, definition in DATASET_DEFINITIONS.items():
        for raw_name, canonical_name, label, non_empty_count, total_count, example in definition["field_summaries"]:
            docs.append(
                {
                    "dataset_id": dataset_id,
                    "raw_name": raw_name,
                    "canonical_name": canonical_name,
                    "label": label,
                    "non_empty_count": non_empty_count,
                    "total_count": total_count,
                    "coverage": (non_empty_count / total_count) if total_count else None,
                    "example": example,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
    return docs


def migrate_minio_objects(client: Any, *, bucket: str, apply: bool, delete_legacy: bool) -> list[dict[str, Any]]:
    """Copy MinIO objects from legacy keys into datasets/ keys."""
    records: list[dict[str, Any]] = []
    for mapping in OBJECT_MIGRATIONS:
        source = client.head_object(bucket, mapping.legacy_key) if client else None
        target = client.head_object(bucket, mapping.object_key) if client else None
        record = {
            **asdict(mapping),
            "bucket": bucket,
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
                    client.copy_object(bucket, mapping.legacy_key, mapping.object_key)
                    target = client.head_object(bucket, mapping.object_key)
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
                        if delete_legacy and source is not None:
                            client.delete_object(bucket, mapping.legacy_key)
                        record["status"] = "renamed" if delete_legacy and source is not None else "copied"
        except Exception as exc:  # noqa: BLE001 - manifest must preserve per-object failure.
            record["status"] = "failed"
            record["error"] = f"{exc.__class__.__name__}: {exc}"
        records.append(record)
    return records


def migrate_sftp_open_database_objects(
    sftp_client: Any,
    s3_client: Any,
    *,
    bucket: str,
    sftp_host: str,
    sftp_root: str,
    apply: bool,
) -> list[dict[str, Any]]:
    """Upload source SFTP files into canonical MinIO dataset keys."""
    records: list[dict[str, Any]] = []
    root = sftp_root.rstrip("/")
    for mapping in SFTP_OBJECT_MIGRATIONS:
        remote_path = f"{root}/{mapping.remote_relative_path}"
        record = {
            **asdict(mapping),
            "bucket": bucket,
            "sftp_host": sftp_host,
            "remote_path": remote_path,
            "remote": None,
            "target": None,
            "target_exists": False,
            "status": "planned",
            "error": None,
        }
        try:
            remote = sftp_client.stat_file(remote_path) if sftp_client else None
            target = s3_client.head_object(bucket, mapping.object_key) if s3_client else None
            record["remote"] = remote
            record["target"] = target
            record["target_exists"] = target is not None
            if not apply:
                records.append(record)
                continue
            if sftp_client is None:
                record["status"] = "skipped"
                record["error"] = "SFTP client is not configured"
            elif s3_client is None:
                record["status"] = "skipped"
                record["error"] = "MinIO client is not configured"
            elif remote is None:
                record["status"] = "missing_source"
            elif target and target.get("size_bytes") == remote.get("size_bytes"):
                record["status"] = "already_migrated"
            else:
                content = sftp_client.read_file(remote_path)
                s3_client.put_object(bucket, mapping.object_key, content, mapping.content_type)
                target = s3_client.head_object(bucket, mapping.object_key)
                record["target"] = target
                record["target_exists"] = target is not None
                if target and target.get("size_bytes") == remote.get("size_bytes"):
                    record["status"] = "uploaded"
                else:
                    record["status"] = "verify_failed"
                    record["error"] = "size mismatch"
        except Exception as exc:  # noqa: BLE001 - manifest must preserve per-object failure.
            record["status"] = "failed"
            record["error"] = f"{exc.__class__.__name__}: {exc}"
        records.append(record)
    return records


def migrate_sftp_md_allatom_objects(
    sftp_client: Any,
    s3_client: Any,
    *,
    target_db: Any | None,
    bucket: str,
    sftp_host: str,
    md_root: str,
    families: list[str],
    apply: bool,
) -> list[dict[str, Any]]:
    """Upload MD-AllAtom raw SFTP files into MinIO and index them in MongoDB."""
    records: list[dict[str, Any]] = []
    normalized_families = [family.strip() for family in families if family.strip()]
    for family in normalized_families:
        remote_family_root = f"{md_root.rstrip('/')}/{family}"
        family_files = sftp_client.list_files_recursive(remote_family_root) if sftp_client else []
        family_records: list[dict[str, Any]] = []
        for index, file_info in enumerate(family_files, start=1):
            relative_path = str(file_info["relative_path"]).lstrip("/")
            object_key = f"datasets/md_allatom/raw/{family}/{urllib.parse.quote(relative_path, safe='/-_.~')}"
            remote_path = str(file_info["remote_path"])
            record = {
                "dataset_id": "md_allatom",
                "role": "raw_file",
                "family": family,
                "remote_relative_path": relative_path,
                "object_key": object_key,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_path,
                "remote": {
                    "size_bytes": file_info.get("size_bytes"),
                    "mtime": file_info.get("mtime"),
                },
                "target": None,
                "target_exists": False,
                "status": "planned",
                "error": None,
            }
            try:
                target = s3_client.head_object(bucket, object_key) if s3_client else None
                record["target"] = target
                record["target_exists"] = target is not None
                if not apply:
                    family_records.append(record)
                    continue
                if sftp_client is None:
                    record["status"] = "skipped"
                    record["error"] = "SFTP client is not configured"
                elif s3_client is None:
                    record["status"] = "skipped"
                    record["error"] = "MinIO client is not configured"
                elif target and target.get("size_bytes") == file_info.get("size_bytes"):
                    record["status"] = "already_migrated"
                else:
                    content = sftp_client.read_file(remote_path)
                    s3_client.put_object(bucket, object_key, content, "application/octet-stream")
                    target = s3_client.head_object(bucket, object_key)
                    record["target"] = target
                    record["target_exists"] = target is not None
                    if target and target.get("size_bytes") == file_info.get("size_bytes"):
                        record["status"] = "uploaded"
                    else:
                        record["status"] = "verify_failed"
                        record["error"] = "size mismatch"
            except Exception as exc:  # noqa: BLE001 - manifest must preserve per-file failure.
                record["status"] = "failed"
                record["error"] = f"{exc.__class__.__name__}: {exc}"
            family_records.append(record)

        if apply and s3_client is not None:
            manifest = {
                "dataset_id": "md_allatom",
                "family": family,
                "remote_root": remote_family_root,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "file_count": len(family_records),
                "records": family_records,
            }
            s3_client.put_object(
                bucket,
                f"datasets/md_allatom/manifests/{family}.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                "application/json; charset=utf-8",
            )

        records.extend(family_records)

    if apply and target_db is not None:
        create_indexes(target_db)
        documents = [
            build_md_allatom_file_document(record, family=str(record["family"]), index=index)
            for index, record in enumerate(records, start=1)
            if record.get("status") in {"uploaded", "already_migrated"}
        ]
        upsert_documents(target_db[TARGET_MD_ALLATOM_FILES_COLLECTION], "md_allatom_file_id", documents)
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "md_allatom"},
            {
                "$set": {
                    "dataset_id": "md_allatom",
                    "asset_coverage": {
                        "file_count": len(documents),
                        "families": {
                            family: sum(1 for doc in documents if doc.get("family") == family)
                            for family in normalized_families
                        },
                    },
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    return records


def create_indexes(target_db: Any) -> None:
    """Create Poly Data indexes."""
    target_db["datasets"].create_index([("dataset_id", 1)], name="dataset_id", unique=True)
    target_db["dataset_objects"].create_index([("dataset_id", 1), ("role", 1)], name="dataset_role")
    target_db["dataset_objects"].create_index([("object_key", 1)], name="object_key", unique=True)
    target_db["dataset_fields"].create_index([("dataset_id", 1), ("canonical_name", 1)], name="dataset_field")
    target_db[TARGET_MATERIAL_COLLECTION].create_index([("polymer_record_id", 1)], name="polymer_record_id", unique=True)
    target_db[TARGET_MATERIAL_COLLECTION].create_index([("dataset.dataset_code", 1)], name="dataset_code")
    target_db[TARGET_MATERIAL_COLLECTION].create_index([("provenance.created_at", -1)], name="provenance_created")
    target_db[TARGET_RADONPY_COLLECTION].create_index([("radonpy_record_id", 1)], name="radonpy_record_id", unique=True)
    target_db[TARGET_RADONPY_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_PI1M_COLLECTION].create_index([("pi1m_record_id", 1)], name="pi1m_record_id", unique=True)
    target_db[TARGET_PI1M_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_PI1M_COLLECTION].create_index([("smiles_hash", 1)], name="smiles_hash")
    target_db[TARGET_PI1M_COLLECTION].create_index([("row_index", 1)], name="row_index")
    target_db[TARGET_PI1M_COLLECTION].create_index([("sa_score", 1), ("row_index", 1)], name="sa_score_row")
    target_db[TARGET_PI1M_COLLECTION].create_index([("dataset.dataset_id", 1), ("row_index", 1)], name="dataset_row")
    target_db[TARGET_SMIPOLY_COLLECTION].create_index([("smipoly_record_id", 1)], name="smipoly_record_id", unique=True)
    target_db[TARGET_SMIPOLY_COLLECTION].create_index([("com_id", 1)], name="com_id")
    target_db[TARGET_SMIPOLY_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_POLYUNIVERSE_COLLECTION].create_index(
        [("polyuniverse_record_id", 1)], name="polyuniverse_record_id", unique=True
    )
    target_db[TARGET_POLYUNIVERSE_COLLECTION].create_index([("source_file", 1), ("row_index", 1)], name="source_row")
    target_db[TARGET_POLYUNIVERSE_COLLECTION].create_index([("monomer_class", 1)], name="monomer_class")
    target_db[TARGET_POLYUNIVERSE_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_MD_ALLATOM_FILES_COLLECTION].create_index(
        [("md_allatom_file_id", 1)], name="md_allatom_file_id", unique=True
    )
    target_db[TARGET_MD_ALLATOM_FILES_COLLECTION].create_index([("object_key", 1)], name="object_key", unique=True)
    target_db[TARGET_MD_ALLATOM_FILES_COLLECTION].create_index([("family", 1), ("extension", 1)], name="family_ext")
    target_db[TARGET_MD_ALLATOM_DIAMINES_COLLECTION].create_index(
        [("md_allatom_diamine_id", 1)], name="md_allatom_diamine_id", unique=True
    )
    target_db[TARGET_MD_ALLATOM_DIAMINES_COLLECTION].create_index([("diamine_id", 1)], name="diamine_id", unique=True)
    target_db[TARGET_MD_ALLATOM_DIAMINES_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION].create_index(
        [("md_allatom_dianhydride_id", 1)], name="md_allatom_dianhydride_id", unique=True
    )
    target_db[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION].create_index(
        [("dianhydride_id", 1)], name="dianhydride_id", unique=True
    )
    target_db[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION].create_index([("smiles", 1)], name="smiles")
    target_db[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION].create_index(
        [("md_allatom_carbon_result_id", 1)], name="md_allatom_carbon_result_id", unique=True
    )
    target_db[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION].create_index(
        [("diamine_id", 1), ("dianhydride_id", 1), ("dp", 1), ("temperature", 1)],
        name="carbon_natural_fields",
    )
    target_db[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION].create_index([("temperature", 1)], name="temperature")
    target_db[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION].create_index([("dp", 1)], name="dp")
    target_db["migration_manifests"].create_index([("generated_at", -1)], name="generated_at")
    target_db[TARGET_DATASET_STATS_COLLECTION].create_index([("dataset_id", 1)], name="dataset_id", unique=True)
    target_db[TARGET_IMPORT_JOBS_COLLECTION].create_index([("job_id", 1)], name="job_id", unique=True)
    target_db[TARGET_IMPORT_JOBS_COLLECTION].create_index([("dataset_id", 1), ("started_at", -1)], name="dataset_started")
    target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].create_index(
        [("job_id", 1), ("chunk_index", 1)], name="job_chunk", unique=True
    )


def normalize_scalar(value: Any) -> Any:
    """Convert pandas/numpy scalar values into Mongo-friendly values."""
    try:
        import pandas as pd

        if pd.isna(value):
            return None
    except Exception:
        pass
    if hasattr(value, "item"):
        try:
            return value.item()
        except Exception:
            return value
    return value


def normalized_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON/Mongo-friendly row payload."""
    return {str(key).lstrip("\ufeff").strip(): normalize_scalar(value) for key, value in row.items()}


def first_present(row: dict[str, Any], candidates: list[str]) -> Any:
    """Return the first present value matching candidate column names case-insensitively."""
    lower_map = {str(key).strip().lower(): key for key in row}
    for candidate in candidates:
        key = lower_map.get(candidate.strip().lower())
        if key is not None and row.get(key) is not None:
            return row.get(key)
    return None


def build_radonpy_documents(dataframe: Any) -> list[dict[str, Any]]:
    """Build RadonPy Mongo documents from a pandas DataFrame."""
    docs: list[dict[str, Any]] = []
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        smiles = first_present(row, ["smiles", "SMILES", "p_smiles", "psmiles"])
        properties = {
            "density": first_present(row, ["density"]),
            "static_dielectric_const": first_present(row, ["static_dielectric_const", "dielectric_constant"]),
            "thermal_conductivity": first_present(row, ["thermal_conductivity"]),
        }
        properties = {key: value for key, value in properties.items() if value is not None}
        docs.append(
            {
                "radonpy_record_id": f"RADONPY_PI1070-{index:06d}",
                "dataset": {"dataset_id": "radonpy_pi1070", "dataset_name": "RadonPy PI1070"},
                "smiles": smiles,
                "source_file": "pi1070.xlsx",
                "properties": properties,
                "raw": row,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
    return docs


def smiles_hash(smiles: Any) -> str | None:
    """Return stable SHA-256 hash for exact p-SMILES lookup."""
    if smiles is None:
        return None
    normalized = str(smiles).strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def as_float(value: Any) -> float | None:
    """Convert values to finite floats for stats and filtering."""
    if value is None or value == "":
        return None
    try:
        import math

        number = float(value)
        if math.isnan(number) or math.isinf(number):
            return None
        return number
    except (TypeError, ValueError):
        return None


def build_pi1m_documents(dataframe: Any, *, start_index: int = 1, sample_size: int | None = None) -> list[dict[str, Any]]:
    """Build PI1M Mongo documents from one DataFrame chunk."""
    docs: list[dict[str, Any]] = []
    records = dataframe.head(sample_size).to_dict(orient="records") if sample_size else dataframe.to_dict(orient="records")
    now = datetime.now(timezone.utc)
    for offset, raw in enumerate(records):
        index = start_index + offset
        row = normalized_row(raw)
        smiles = first_present(row, ["SMILES", "smiles", "p_smiles", "psmiles"])
        sa_score = first_present(row, ["SA Score", "sa_score", "SAScore", "sa"])
        docs.append(
            {
                "pi1m_record_id": f"PI1M_V2-{index:06d}",
                "dataset": {"dataset_id": "pi1m_v2", "dataset_name": "PI1M v2"},
                "smiles": smiles,
                "smiles_hash": smiles_hash(smiles),
                "sa_score": as_float(sa_score),
                "row_index": index,
                "sample_index": index,
                "source_file": "pi1m_v2.csv",
                "created_at": now,
                "updated_at": now,
            }
        )
    return docs


def histogram(values: list[float], *, bins: int = 12) -> list[dict[str, Any]]:
    """Build compact histogram bins."""
    if not values:
        return []
    lower = min(values)
    upper = max(values)
    if lower == upper:
        return [{"start": lower, "end": upper, "count": len(values)}]
    width = (upper - lower) / bins
    counts = [0 for _ in range(bins)]
    for value in values:
        bucket = min(int((value - lower) / width), bins - 1)
        counts[bucket] += 1
    return [
        {"start": round(lower + index * width, 4), "end": round(lower + (index + 1) * width, 4), "count": count}
        for index, count in enumerate(counts)
    ]


def upsert_documents_bulk(collection: Any, key_field: str, documents: list[dict[str, Any]]) -> int:
    """Bulk upsert documents by key field."""
    if not documents:
        return 0
    try:
        from pymongo import UpdateOne

        operations = [
            UpdateOne({key_field: doc[key_field]}, {"$set": doc}, upsert=True)
            for doc in documents
        ]
        collection.bulk_write(operations, ordered=False)
        return len(documents)
    except Exception:
        return upsert_documents(collection, key_field, documents)


def build_smipoly_documents(dataframe: Any) -> list[dict[str, Any]]:
    """Build SMiPoly monomer Mongo documents from a pandas DataFrame."""
    docs: list[dict[str, Any]] = []
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        com_id = first_present(row, ["comID", "com_id"]) or f"ROW-{index:06d}"
        docs.append(
            {
                "smipoly_record_id": f"SMIPOLY-{com_id}",
                "dataset": {"dataset_id": "smipoly", "dataset_name": "SMiPoly"},
                "com_id": com_id,
                "molecular_formula": first_present(row, ["MolecularFormula", "molecular_formula"]),
                "molecular_weight": first_present(row, ["MolecularWeight", "molecular_weight"]),
                "smiles": first_present(row, ["SMILES", "smiles"]),
                "iupac_name": first_present(row, ["IUPACName", "iupac_name"]),
                "source_file": "202207_smip_monset.csv",
                "raw": row,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
    return docs


POLYUNIVERSE_MONOMER_CLASSES = {
    "diCOOH.csv": "dicarboxylic_acid",
    "epoxy_diE.csv": "diepoxy",
    "epoxy_diN.csv": "diamine",
}


def build_polyuniverse_documents(dataframe: Any, *, source_file: str) -> list[dict[str, Any]]:
    """Build PolyUniverse monomer Mongo documents from one source CSV."""
    docs: list[dict[str, Any]] = []
    source_stem = Path(source_file).stem
    monomer_class = POLYUNIVERSE_MONOMER_CLASSES.get(source_file, "candidate_monomer")
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        docs.append(
            {
                "polyuniverse_record_id": f"POLYUNIVERSE-{source_stem}-{index:06d}",
                "dataset": {"dataset_id": "polyuniverse", "dataset_name": "PolyUniverse"},
                "monomer_class": monomer_class,
                "source_file": source_file,
                "row_index": index,
                "smiles": first_present(row, ["Smiles", "SMILES", "smiles"]),
                "raw": row,
                "created_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            }
        )
    return docs


def parse_int(value: Any) -> int | None:
    """Convert a numeric CSV value into int when possible."""
    number = as_float(value)
    return int(number) if number is not None else None


def build_md_allatom_file_document(record: dict[str, Any], *, family: str, index: int) -> dict[str, Any]:
    """Build a Mongo file-index document for one MD-AllAtom raw asset."""
    object_key = str(record["object_key"])
    filename = Path(object_key).name
    stable_id = hashlib.sha256(object_key.encode("utf-8")).hexdigest()[:12]
    return {
        "md_allatom_file_id": f"MDALLATOM-FILE-{family}-{stable_id}",
        "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
        "family": family,
        "remote_path": record.get("remote_path"),
        "remote_relative_path": record.get("remote_relative_path"),
        "object_key": object_key,
        "filename": filename,
        "extension": Path(filename).suffix.lower(),
        "size_bytes": record.get("remote", {}).get("size_bytes") or record.get("target", {}).get("size_bytes"),
        "mtime": record.get("remote", {}).get("mtime"),
        "sync_status": record.get("status"),
        "created_at": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    }


def build_md_allatom_diamine_documents(dataframe: Any) -> list[dict[str, Any]]:
    """Build MD-AllAtom diamine dictionary documents."""
    docs: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        diamine_id = parse_int(first_present(row, ["diamine_id"]))
        if diamine_id is None:
            continue
        docs.append(
            {
                "md_allatom_diamine_id": f"MDALLATOM-DIAMINE-{diamine_id:06d}",
                "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                "diamine_id": diamine_id,
                "cas": first_present(row, ["diamine_cas"]),
                "name": first_present(row, ["diamine_name"]),
                "name_cn": first_present(row, ["diamine_name_cn"]),
                "abbr": first_present(row, ["diamine_abbr"]),
                "smiles": first_present(row, ["diamine_SMILES", "diamine_smiles"]),
                "source_file": "二胺.csv",
                "row_index": index,
                "raw": row,
                "created_at": now,
                "updated_at": now,
            }
        )
    return docs


def build_md_allatom_dianhydride_documents(dataframe: Any) -> list[dict[str, Any]]:
    """Build MD-AllAtom dianhydride dictionary documents."""
    docs: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        dianhydride_id = parse_int(first_present(row, ["dianhydride_id"]))
        if dianhydride_id is None:
            continue
        docs.append(
            {
                "md_allatom_dianhydride_id": f"MDALLATOM-DIANHYDRIDE-{dianhydride_id:06d}",
                "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
                "dianhydride_id": dianhydride_id,
                "cas": first_present(row, ["dianhydride_cas"]),
                "name": first_present(row, ["dianhydride_name"]),
                "name_cn": first_present(row, ["dianhydride_name_cn"]),
                "abbr": first_present(row, ["dianhydride_abbr"]),
                "smiles": first_present(row, ["dianhydride_SMILES", "dianhydride_smiles"]),
                "source_file": "二酐.csv",
                "row_index": index,
                "raw": row,
                "created_at": now,
                "updated_at": now,
            }
        )
    return docs


def build_md_allatom_carbon_documents(dataframe: Any) -> list[dict[str, Any]]:
    """Build MD-AllAtom carbon MD-result documents from row order."""
    docs: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    numeric_fields = [
        "monomer_len",
        "contour_len",
        "e2e_mean",
        "e2e_std",
        "rg_mean",
        "rg_std",
        "persist_len_mean",
        "persist_len_std",
    ]
    for index, raw in enumerate(dataframe.to_dict(orient="records"), start=1):
        row = normalized_row(raw)
        doc: dict[str, Any] = {
            "md_allatom_carbon_result_id": f"MDALLATOM-C-{index:06d}",
            "dataset": {"dataset_id": "md_allatom", "dataset_name": "MD-AllAtom"},
            "family": "C",
            "row_index": index,
            "diamine_id": parse_int(first_present(row, ["diamine_id"])),
            "dianhydride_id": parse_int(first_present(row, ["dianhydride_id"])),
            "dp": parse_int(first_present(row, ["dp"])),
            "temperature": parse_int(first_present(row, ["temperature"])),
            "data_file": first_present(row, ["data_file"]),
            "out_file": first_present(row, ["out_file"]),
            "raw": row,
            "created_at": now,
            "updated_at": now,
        }
        for field in numeric_fields:
            doc[field] = as_float(first_present(row, [field]))
        docs.append(doc)
    return docs


def md_allatom_stats(
    carbon_documents: list[dict[str, Any]],
    *,
    file_documents: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build compact aggregate stats for the MD-AllAtom analysis page."""
    category_counts: dict[str, dict[str, int]] = {"temperature": {}, "dp": {}, "family": {}}
    histograms: dict[str, list[dict[str, Any]]] = {}
    for doc in carbon_documents:
        for field in ["temperature", "dp", "family"]:
            value = doc.get(field)
            if value is None:
                continue
            key = str(value)
            category_counts[field][key] = category_counts[field].get(key, 0) + 1
    for field in ["e2e_mean", "rg_mean", "persist_len_mean"]:
        values = [as_float(doc.get(field)) for doc in carbon_documents]
        histograms[field] = histogram([value for value in values if value is not None])
    sample_step = max(len(carbon_documents) // 5000, 1)
    samples = [
        {
            "record_id": doc["md_allatom_carbon_result_id"],
            "x": doc.get("temperature"),
            "y": doc.get("e2e_mean"),
            "category": f"dp={doc.get('dp')}" if doc.get("dp") is not None else "dp=-",
            "dp": doc.get("dp"),
            "temperature": doc.get("temperature"),
            "rg_mean": doc.get("rg_mean"),
            "persist_len_mean": doc.get("persist_len_mean"),
        }
        for index, doc in enumerate(carbon_documents)
        if index % sample_step == 0
    ][:5000]
    file_docs = file_documents or []
    family_file_counts: dict[str, int] = {family: 0 for family in MD_ALLATOM_DEFAULT_FAMILIES}
    for doc in file_docs:
        family = str(doc.get("family") or "")
        if family:
            family_file_counts[family] = family_file_counts.get(family, 0) + 1
    return {
        "category_counts": category_counts,
        "numeric_histograms": histograms,
        "analysis_samples": samples,
        "asset_coverage": {
            "file_count": len(file_docs),
            "families": family_file_counts,
            "structured_records": {
                "carbon_results": len(carbon_documents),
            },
        },
    }


def upsert_documents(collection: Any, key_field: str, documents: list[dict[str, Any]]) -> int:
    """Upsert documents by key field and return processed count."""
    for doc in documents:
        collection.update_one({key_field: doc[key_field]}, {"$set": doc}, upsert=True)
    return len(documents)


def update_dataset_record_count(target_db: Any, dataset_id: str, *, count: int, record_mode: str, collection_key: str) -> None:
    """Persist dataset import status."""
    target_db["datasets"].update_one(
        {"dataset_id": dataset_id},
        {
            "$set": {
                "record_collection_key": collection_key,
                "record_count": count,
                "record_mode": record_mode if count else "metadata_only",
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def upsert_catalog_metadata(target_db: Any, *, object_records: list[dict[str, Any]], apply: bool) -> int:
    """Upsert dataset, field, and object metadata documents."""
    if not apply:
        return 0
    metadata_upserted = 0
    create_indexes(target_db)
    for doc in dataset_documents():
        target_db["datasets"].update_one({"dataset_id": doc["dataset_id"]}, {"$set": doc}, upsert=True)
        metadata_upserted += 1
    for doc in field_documents():
        target_db["dataset_fields"].update_one(
            {"dataset_id": doc["dataset_id"], "canonical_name": doc["canonical_name"]},
            {"$set": doc},
            upsert=True,
        )
        metadata_upserted += 1
    for record in object_records:
        object_key = record.get("object_key")
        if not object_key:
            continue
        target_db["dataset_objects"].update_one(
            {"object_key": object_key},
            {"$set": {**record, "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        metadata_upserted += 1
    return metadata_upserted


def import_radonpy_records(target_db: Any, *, s3_client: Any, bucket: str, apply: bool) -> dict[str, Any]:
    """Import all RadonPy PI1070 rows from MinIO into MongoDB."""
    summary = {
        "dataset_id": "radonpy_pi1070",
        "source_object_key": RADONPY_OBJECT_KEY,
        "target_collection": TARGET_RADONPY_COLLECTION,
        "records_upserted": 0,
        "status": "planned",
        "error": None,
    }
    if not apply:
        return summary
    if s3_client is None:
        summary["status"] = "skipped"
        summary["error"] = "MinIO client is not configured"
        return summary
    try:
        import pandas as pd

        content = s3_client.get_object(bucket, RADONPY_OBJECT_KEY)
        dataframe = pd.read_excel(BytesIO(content), engine="openpyxl")
        documents = build_radonpy_documents(dataframe)
        create_indexes(target_db)
        summary["records_upserted"] = upsert_documents(target_db[TARGET_RADONPY_COLLECTION], "radonpy_record_id", documents)
        update_dataset_record_count(
            target_db,
            "radonpy_pi1070",
            count=summary["records_upserted"],
            record_mode="full",
            collection_key="poly_data.radonpy_records",
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
    return summary


def import_pi1m_samples(
    target_db: Any,
    *,
    s3_client: Any,
    bucket: str,
    sample_size: int | None,
    chunk_size: int = DEFAULT_PI1M_CHUNK_SIZE,
    apply: bool,
) -> dict[str, Any]:
    """Import PI1M v2 rows from MinIO into MongoDB with chunked bulk upserts."""
    job_id = f"pi1m_v2-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    summary = {
        "dataset_id": "pi1m_v2",
        "source_object_key": PI1M_OBJECT_KEY,
        "target_collection": TARGET_PI1M_COLLECTION,
        "sample_size": sample_size,
        "chunk_size": chunk_size,
        "job_id": job_id,
        "records_upserted": 0,
        "failed_count": 0,
        "checkpoint_count": 0,
        "status": "planned",
        "error": None,
    }
    if not apply:
        return summary
    if s3_client is None:
        summary["status"] = "skipped"
        summary["error"] = "MinIO client is not configured"
        return summary
    try:
        import pandas as pd

        create_indexes(target_db)
        source = s3_client.head_object(bucket, PI1M_OBJECT_KEY) if hasattr(s3_client, "head_object") else None
        started_at = datetime.now(timezone.utc)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "dataset_id": "pi1m_v2",
                    "source_object_key": PI1M_OBJECT_KEY,
                    "source": source,
                    "status": "running",
                    "sample_size": sample_size,
                    "chunk_size": chunk_size,
                    "started_at": started_at,
                    "updated_at": started_at,
                }
            },
            upsert=True,
        )
        start_time = monotonic()
        content = s3_client.get_object(bucket, PI1M_OBJECT_KEY)
        read_csv_kwargs: dict[str, Any] = {"chunksize": max(int(chunk_size), 1)}
        if sample_size is not None:
            read_csv_kwargs["nrows"] = max(int(sample_size), 0)
        reader = pd.read_csv(BytesIO(content), **read_csv_kwargs)
        row_index = 1
        scores: list[float] = []
        smiles_seen: set[str] = set()
        duplicate_smiles_count = 0
        visual_samples: list[dict[str, Any]] = []
        for chunk_index, dataframe in enumerate(reader, start=1):
            chunk_started = monotonic()
            documents = build_pi1m_documents(dataframe, start_index=row_index)
            records_in_chunk = len(documents)
            if not records_in_chunk:
                continue
            target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].update_one(
                {"job_id": job_id, "chunk_index": chunk_index},
                {
                    "$set": {
                        "job_id": job_id,
                        "dataset_id": "pi1m_v2",
                        "chunk_index": chunk_index,
                        "row_start": row_index,
                        "row_end": row_index + records_in_chunk - 1,
                        "records": records_in_chunk,
                        "status": "running",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            summary["records_upserted"] += upsert_documents_bulk(
                target_db[TARGET_PI1M_COLLECTION], "pi1m_record_id", documents
            )
            for doc in documents:
                score = as_float(doc.get("sa_score"))
                if score is not None:
                    scores.append(score)
                doc_hash = doc.get("smiles_hash")
                if doc_hash:
                    if doc_hash in smiles_seen:
                        duplicate_smiles_count += 1
                    else:
                        smiles_seen.add(doc_hash)
                if len(visual_samples) < 5000 and doc.get("row_index", 0) % max(records_in_chunk // 100, 1) == 0:
                    visual_samples.append(
                        {
                            "record_id": doc["pi1m_record_id"],
                            "row_index": doc["row_index"],
                            "smiles": doc.get("smiles"),
                            "sa_score": doc.get("sa_score"),
                        }
                    )
            chunk_elapsed = max(monotonic() - chunk_started, 0.001)
            target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].update_one(
                {"job_id": job_id, "chunk_index": chunk_index},
                {
                    "$set": {
                        "status": "completed",
                        "records_upserted": records_in_chunk,
                        "duration_seconds": round(chunk_elapsed, 3),
                        "throughput_rows_per_second": round(records_in_chunk / chunk_elapsed, 2),
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            summary["checkpoint_count"] += 1
            row_index += records_in_chunk
        elapsed = max(monotonic() - start_time, 0.001)
        update_dataset_record_count(
            target_db,
            "pi1m_v2",
            count=summary["records_upserted"],
            record_mode="full" if sample_size is None else "sample",
            collection_key="poly_data.pi1m_samples",
        )
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "pi1m_v2"},
            {
                "$set": {
                    "dataset_id": "pi1m_v2",
                    "record_count": summary["records_upserted"],
                    "sa_score_histogram": histogram(scores),
                    "unique_smiles_count": len(smiles_seen),
                    "duplicate_smiles_count": duplicate_smiles_count,
                    "visual_samples": visual_samples,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        finished_at = datetime.now(timezone.utc)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "imported",
                    "imported_count": summary["records_upserted"],
                    "failed_count": summary["failed_count"],
                    "checkpoint_count": summary["checkpoint_count"],
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    "duration_seconds": round(elapsed, 3),
                    "throughput_rows_per_second": round(summary["records_upserted"] / elapsed, 2),
                }
            },
            upsert=True,
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
        try:
            target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "failed",
                        "error": summary["error"],
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        except Exception:
            pass
    return summary


def import_smipoly_records(target_db: Any, *, s3_client: Any, bucket: str, apply: bool) -> dict[str, Any]:
    """Import all SMiPoly monomer rows from MinIO into MongoDB."""
    summary = {
        "dataset_id": "smipoly",
        "source_object_key": SMIPOLY_OBJECT_KEY,
        "target_collection": TARGET_SMIPOLY_COLLECTION,
        "records_upserted": 0,
        "status": "planned",
        "error": None,
    }
    if not apply:
        return summary
    if s3_client is None:
        summary["status"] = "skipped"
        summary["error"] = "MinIO client is not configured"
        return summary
    try:
        import pandas as pd

        content = s3_client.get_object(bucket, SMIPOLY_OBJECT_KEY)
        dataframe = pd.read_csv(BytesIO(content))
        documents = build_smipoly_documents(dataframe)
        create_indexes(target_db)
        summary["records_upserted"] = upsert_documents(
            target_db[TARGET_SMIPOLY_COLLECTION], "smipoly_record_id", documents
        )
        update_dataset_record_count(
            target_db,
            "smipoly",
            count=summary["records_upserted"],
            record_mode="full",
            collection_key="poly_data.smipoly_monomers",
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
    return summary


def import_polyuniverse_records(target_db: Any, *, s3_client: Any, bucket: str, apply: bool) -> dict[str, Any]:
    """Import all PolyUniverse monomer rows from MinIO into MongoDB."""
    summary = {
        "dataset_id": "polyuniverse",
        "source_object_keys": list(POLYUNIVERSE_OBJECT_KEYS.values()),
        "target_collection": TARGET_POLYUNIVERSE_COLLECTION,
        "records_upserted": 0,
        "status": "planned",
        "error": None,
    }
    if not apply:
        return summary
    if s3_client is None:
        summary["status"] = "skipped"
        summary["error"] = "MinIO client is not configured"
        return summary
    try:
        import pandas as pd

        documents: list[dict[str, Any]] = []
        for source_file, object_key in POLYUNIVERSE_OBJECT_KEYS.items():
            content = s3_client.get_object(bucket, object_key)
            dataframe = pd.read_csv(BytesIO(content))
            documents.extend(build_polyuniverse_documents(dataframe, source_file=source_file))
        create_indexes(target_db)
        summary["records_upserted"] = upsert_documents(
            target_db[TARGET_POLYUNIVERSE_COLLECTION], "polyuniverse_record_id", documents
        )
        update_dataset_record_count(
            target_db,
            "polyuniverse",
            count=summary["records_upserted"],
            record_mode="full",
            collection_key="poly_data.polyuniverse_monomers",
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
    return summary


def upload_md_allatom_structured_assets(
    *,
    s3_client: Any,
    bucket: str,
    structured_data_root: Path,
    requirements_doc: Path,
) -> list[dict[str, Any]]:
    """Upload local MD-AllAtom structured source files to canonical MinIO keys."""
    file_specs = [
        (structured_data_root / "二胺.csv", MD_ALLATOM_STRUCTURED_OBJECT_KEYS["diamine"], "text/csv; charset=utf-8"),
        (structured_data_root / "二酐.csv", MD_ALLATOM_STRUCTURED_OBJECT_KEYS["dianhydride"], "text/csv; charset=utf-8"),
        (structured_data_root / "碳基.csv", MD_ALLATOM_STRUCTURED_OBJECT_KEYS["carbon"], "text/csv; charset=utf-8"),
        (
            requirements_doc,
            MD_ALLATOM_STRUCTURED_OBJECT_KEYS["requirements_doc"],
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ),
    ]
    records: list[dict[str, Any]] = []
    for source_path, object_key, content_type in file_specs:
        content = source_path.read_bytes()
        s3_client.put_object(bucket, object_key, content, content_type)
        target = s3_client.head_object(bucket, object_key) if hasattr(s3_client, "head_object") else None
        records.append(
            {
                "dataset_id": "md_allatom",
                "role": "requirements_doc" if source_path == requirements_doc else "structured_table",
                "source_path": str(source_path),
                "object_key": object_key,
                "bucket": bucket,
                "target": target,
                "status": "uploaded",
            }
        )
    return records


def load_md_allatom_file_documents(target_db: Any) -> list[dict[str, Any]]:
    """Load existing MD-AllAtom file-index documents from fake or real Mongo collections."""
    collection = target_db[TARGET_MD_ALLATOM_FILES_COLLECTION]
    fake_rows = getattr(collection, "rows", None)
    if isinstance(fake_rows, list):
        return [dict(row) for row in fake_rows]
    try:
        return [dict(row) for row in collection.find({}, {"_id": 0})]
    except Exception:
        return []


def import_md_allatom_structured_records(
    target_db: Any,
    *,
    s3_client: Any,
    bucket: str,
    structured_data_root: Path,
    requirements_doc: Path,
    apply: bool,
) -> dict[str, Any]:
    """Upload and import MD-AllAtom structured CSV dictionaries and carbon results."""
    summary = {
        "dataset_id": "md_allatom",
        "source_object_keys": MD_ALLATOM_STRUCTURED_OBJECT_KEYS,
        "target_collections": [
            TARGET_MD_ALLATOM_DIAMINES_COLLECTION,
            TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION,
            TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION,
        ],
        "diamine_records_upserted": 0,
        "dianhydride_records_upserted": 0,
        "carbon_records_upserted": 0,
        "uploaded_objects": [],
        "status": "planned",
        "error": None,
    }
    if not apply:
        return summary
    if s3_client is None:
        summary["status"] = "skipped"
        summary["error"] = "MinIO client is not configured"
        return summary
    try:
        import pandas as pd

        create_indexes(target_db)
        summary["uploaded_objects"] = upload_md_allatom_structured_assets(
            s3_client=s3_client,
            bucket=bucket,
            structured_data_root=structured_data_root,
            requirements_doc=requirements_doc,
        )
        diamines = build_md_allatom_diamine_documents(pd.read_csv(structured_data_root / "二胺.csv", encoding="utf-8-sig"))
        dianhydrides = build_md_allatom_dianhydride_documents(
            pd.read_csv(structured_data_root / "二酐.csv", encoding="utf-8-sig")
        )
        carbon_results = build_md_allatom_carbon_documents(pd.read_csv(structured_data_root / "碳基.csv", encoding="utf-8-sig"))
        summary["diamine_records_upserted"] = upsert_documents(
            target_db[TARGET_MD_ALLATOM_DIAMINES_COLLECTION], "md_allatom_diamine_id", diamines
        )
        summary["dianhydride_records_upserted"] = upsert_documents(
            target_db[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION], "md_allatom_dianhydride_id", dianhydrides
        )
        summary["carbon_records_upserted"] = upsert_documents_bulk(
            target_db[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION],
            "md_allatom_carbon_result_id",
            carbon_results,
        )
        file_docs = load_md_allatom_file_documents(target_db)
        stats = md_allatom_stats(carbon_results, file_documents=file_docs)
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "md_allatom"},
            {
                "$set": {
                    "dataset_id": "md_allatom",
                    "record_count": summary["carbon_records_upserted"],
                    **stats,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        update_dataset_record_count(
            target_db,
            "md_allatom",
            count=summary["carbon_records_upserted"],
            record_mode="full",
            collection_key="poly_data.md_allatom_carbon_results",
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
    return summary


def migrate_mongo_assets(
    *,
    source_db: Any,
    target_db: Any,
    object_records: list[dict[str, Any]],
    apply: bool,
    drop_source_after_verify: bool,
) -> dict[str, Any]:
    """Migrate Mongo data and metadata into poly_data."""
    source_collection = source_db[SOURCE_COLLECTION]
    target_collection = target_db[TARGET_MATERIAL_COLLECTION]
    source_count = int(source_collection.estimated_document_count())
    target_count_before = int(target_collection.estimated_document_count())
    summary = {
        "source_database": SOURCE_DATABASE,
        "source_collection": SOURCE_COLLECTION,
        "target_database": TARGET_DATABASE,
        "target_collection": TARGET_MATERIAL_COLLECTION,
        "source_count": source_count,
        "target_count_before": target_count_before,
        "target_count_after": target_count_before,
        "records_upserted": 0,
        "metadata_upserted": 0,
        "source_dropped": False,
        "status": "planned",
    }
    if not apply:
        return summary

    summary["metadata_upserted"] += upsert_catalog_metadata(target_db, object_records=object_records, apply=True)

    for doc in source_collection.find({}, {"_id": 0}):
        polymer_record_id = doc.get("polymer_record_id")
        if not polymer_record_id:
            continue
        target_collection.update_one({"polymer_record_id": polymer_record_id}, {"$set": doc}, upsert=True)
        summary["records_upserted"] += 1

    target_count_after = int(target_collection.count_documents({}))
    summary["target_count_after"] = target_count_after
    summary["status"] = "verified" if target_count_after >= source_count else "count_mismatch"
    update_dataset_record_count(
        target_db,
        "openpoly",
        count=int(target_collection.count_documents({"dataset.dataset_code": "openpoly"})),
        record_mode="full",
        collection_key="poly_data.material_records",
    )
    if drop_source_after_verify and summary["status"] == "verified":
        source_collection.drop()
        summary["source_dropped"] = True
    return summary


def build_manifest(
    *,
    bucket: str,
    apply: bool,
    minio_records: list[dict[str, Any]],
    sftp_records: list[dict[str, Any]] | None = None,
    mongo_summary: dict[str, Any],
    import_summaries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build migration manifest JSON payload."""
    failed_objects = [record for record in minio_records if record["status"] in {"failed", "verify_failed", "copy_failed"}]
    failed_sftp_objects = [
        record
        for record in (sftp_records or [])
        if record["status"] in {"failed", "verify_failed", "copy_failed", "missing_source", "skipped"}
    ]
    return {
        "operation": "poly_data_asset_migration",
        "applied": apply,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket,
        "manifest_key": MANIFEST_KEY,
        "mongo": mongo_summary,
        "imports": import_summaries or [],
        "minio": {
            "records": minio_records,
            "failed_count": len(failed_objects),
        },
        "sftp": {
            "records": sftp_records or [],
            "failed_count": len(failed_sftp_objects),
        },
    }


def persist_manifest(*, target_db: Any, client: Any, bucket: str, manifest: dict[str, Any]) -> None:
    """Persist migration manifest to MongoDB and MinIO."""
    target_db["migration_manifests"].insert_one(json.loads(json.dumps(manifest, default=str)))
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8")
    LOCAL_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOCAL_MANIFEST_PATH.write_bytes(manifest_bytes)
    if client:
        client.put_object(bucket, MANIFEST_KEY, manifest_bytes, "application/json; charset=utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mongodb-uri", default=os.getenv("DATA_ASSET_MONGODB_URI") or settings.mongodb_uri)
    parser.add_argument("--source-database", default=SOURCE_DATABASE)
    parser.add_argument("--target-database", default=TARGET_DATABASE)
    parser.add_argument("--endpoint", default=os.getenv("MINIO_ENDPOINT", ""))
    parser.add_argument("--access-key", default=os.getenv("MINIO_ACCESS_KEY", ""))
    parser.add_argument("--secret-key", default=os.getenv("MINIO_SECRET_KEY", ""))
    parser.add_argument("--bucket", default=os.getenv("MINIO_BUCKET", DEFAULT_BUCKET))
    parser.add_argument("--secure", action="store_true", default=os.getenv("MINIO_SECURE", "false").lower() == "true")
    parser.add_argument("--apply", action="store_true", help="perform MongoDB/MinIO migration")
    parser.add_argument("--delete-legacy-minio", action="store_true", help="delete poly_agent/* MinIO keys after verification")
    parser.add_argument("--drop-source-after-verify", action="store_true", help="drop ai4ms.Poly_Agent after count verification")
    parser.add_argument("--skip-legacy-poly-agent", action="store_true", help="skip legacy ai4ms.Poly_Agent and poly_agent/* migration")
    parser.add_argument("--migrate-sftp-open-databases", action="store_true", help="copy SFTP open database files into MinIO")
    parser.add_argument("--migrate-sftp-md-allatom", action="store_true", help="copy SFTP MD-AllAtom raw files into MinIO")
    parser.add_argument("--sftp-host", default=os.getenv("SFTP_HOST", SFTP_DEFAULT_HOST))
    parser.add_argument("--sftp-port", type=int, default=int(os.getenv("SFTP_PORT", "22")))
    parser.add_argument("--sftp-username", default=os.getenv("SFTP_USERNAME", "fangyikai"))
    parser.add_argument("--sftp-root", default=os.getenv("SFTP_ROOT", SFTP_DEFAULT_ROOT))
    parser.add_argument("--sftp-password-env", default="SFTP_PASSWORD")
    parser.add_argument("--md-allatom-root", default=os.getenv("MD_ALLATOM_ROOT", MD_ALLATOM_DEFAULT_ROOT))
    parser.add_argument(
        "--md-allatom-families",
        default=os.getenv("MD_ALLATOM_FAMILIES", ",".join(MD_ALLATOM_DEFAULT_FAMILIES)),
        help="comma-separated MD-AllAtom material-family directories to sync",
    )
    parser.add_argument("--import-radonpy-records", action="store_true", help="import all RadonPy PI1070 rows into poly_data.radonpy_records")
    parser.add_argument("--import-pi1m-samples", action="store_true", help="import PI1M v2 rows into poly_data.pi1m_samples")
    parser.add_argument("--pi1m-full-import", action="store_true", help="stream all PI1M v2 rows instead of limiting to --pi1m-sample-size")
    parser.add_argument("--import-smipoly-records", action="store_true", help="import all SMiPoly rows into poly_data.smipoly_monomers")
    parser.add_argument(
        "--import-polyuniverse-records",
        action="store_true",
        help="import all PolyUniverse rows into poly_data.polyuniverse_monomers",
    )
    parser.add_argument(
        "--import-md-allatom-structured",
        action="store_true",
        help="upload and import MD-AllAtom structured CSV files from refer/data",
    )
    parser.add_argument("--structured-data-root", type=Path, default=PROJECT_ROOT / "refer" / "data")
    parser.add_argument(
        "--requirements-doc",
        type=Path,
        default=PROJECT_ROOT / "refer" / "requirement" / "PolyAgent_模型数据集成需求收集_填写模板.docx",
    )
    parser.add_argument("--pi1m-sample-size", type=int, default=DEFAULT_PI1M_SAMPLE_SIZE)
    parser.add_argument("--pi1m-chunk-size", type=int, default=DEFAULT_PI1M_CHUNK_SIZE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv or sys.argv[1:])
    from pymongo import MongoClient  # imported lazily so tests can load without a live server

    mongo_client = MongoClient(args.mongodb_uri, serverSelectionTimeoutMS=5000)
    source_db = mongo_client[args.source_database]
    target_db = mongo_client[args.target_database]
    s3_client = None
    if args.endpoint and args.access_key and args.secret_key:
        s3_client = S3Client(
            endpoint=args.endpoint,
            access_key=args.access_key,
            secret_key=args.secret_key,
            secure=args.secure,
        )

    minio_records = []
    if not args.skip_legacy_poly_agent:
        minio_records = migrate_minio_objects(
            s3_client,
            bucket=args.bucket,
            apply=args.apply and s3_client is not None,
            delete_legacy=args.delete_legacy_minio,
        )

    sftp_records: list[dict[str, Any]] = []
    if args.migrate_sftp_open_databases:
        sftp_client = None
        sftp_password = os.getenv(args.sftp_password_env, "")
        try:
            if sftp_password:
                sftp_client = SftpClient(
                    host=args.sftp_host,
                    port=args.sftp_port,
                    username=args.sftp_username,
                    password=sftp_password,
                )
            sftp_records = migrate_sftp_open_database_objects(
                sftp_client,
                s3_client,
                bucket=args.bucket,
                sftp_host=args.sftp_host,
                sftp_root=args.sftp_root,
                apply=args.apply,
            )
        finally:
            if sftp_client is not None:
                sftp_client.close()

    if args.migrate_sftp_md_allatom:
        sftp_client = None
        sftp_password = os.getenv(args.sftp_password_env, "")
        try:
            if sftp_password:
                sftp_client = SftpClient(
                    host=args.sftp_host,
                    port=args.sftp_port,
                    username=args.sftp_username,
                    password=sftp_password,
                )
            md_records = migrate_sftp_md_allatom_objects(
                sftp_client,
                s3_client,
                target_db=target_db,
                bucket=args.bucket,
                sftp_host=args.sftp_host,
                md_root=args.md_allatom_root,
                families=[item.strip() for item in str(args.md_allatom_families).split(",") if item.strip()],
                apply=args.apply,
            )
            sftp_records.extend(md_records)
        finally:
            if sftp_client is not None:
                sftp_client.close()

    object_records = [*minio_records, *sftp_records]
    if args.skip_legacy_poly_agent:
        mongo_summary = {
            "source_database": args.source_database,
            "source_collection": SOURCE_COLLECTION,
            "target_database": args.target_database,
            "target_collection": TARGET_MATERIAL_COLLECTION,
            "source_count": 0,
            "target_count_before": 0,
            "target_count_after": 0,
            "records_upserted": 0,
            "metadata_upserted": upsert_catalog_metadata(target_db, object_records=object_records, apply=args.apply),
            "source_dropped": False,
            "status": "skipped" if args.apply else "planned",
        }
    else:
        mongo_summary = migrate_mongo_assets(
            source_db=source_db,
            target_db=target_db,
            object_records=object_records,
            apply=args.apply,
            drop_source_after_verify=args.drop_source_after_verify,
        )
    import_summaries: list[dict[str, Any]] = []
    if args.import_radonpy_records:
        import_summaries.append(
            import_radonpy_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if args.import_pi1m_samples:
        import_summaries.append(
            import_pi1m_samples(
                target_db,
                s3_client=s3_client,
                bucket=args.bucket,
                sample_size=None if args.pi1m_full_import else args.pi1m_sample_size,
                chunk_size=args.pi1m_chunk_size,
                apply=args.apply,
            )
        )
    if args.import_smipoly_records:
        import_summaries.append(
            import_smipoly_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if args.import_polyuniverse_records:
        import_summaries.append(
            import_polyuniverse_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if args.import_md_allatom_structured:
        import_summaries.append(
            import_md_allatom_structured_records(
                target_db,
                s3_client=s3_client,
                bucket=args.bucket,
                structured_data_root=args.structured_data_root,
                requirements_doc=args.requirements_doc,
                apply=args.apply,
            )
        )
    manifest = build_manifest(
        bucket=args.bucket,
        apply=args.apply,
        minio_records=minio_records,
        sftp_records=sftp_records,
        mongo_summary=mongo_summary,
        import_summaries=import_summaries,
    )
    if args.apply:
        persist_manifest(target_db=target_db, client=s3_client, bucket=args.bucket, manifest=manifest)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode} Poly Data migration for bucket {args.bucket}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    failed_import = any(item.get("status") in {"failed", "skipped"} for item in import_summaries)
    failed = (
        manifest["minio"]["failed_count"]
        or manifest["sftp"]["failed_count"]
        or manifest["mongo"]["status"] == "count_mismatch"
        or failed_import
    )
    return 1 if args.apply and failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
