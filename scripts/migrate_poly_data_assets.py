#!/usr/bin/env python3
"""Migrate polymer data assets to MongoDB poly_data and MinIO datasets/ keys."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import signal
import stat
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
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
from app.services.poly_data_extra_datasets import EXTRA_DATASET_SPECS, DatasetFileSpec, ExtraDatasetSpec  # noqa: E402


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
EXTRA_TARGET_COLLECTIONS = {spec.dataset_id: spec.collection_name for spec in EXTRA_DATASET_SPECS}
TARGET_DATASET_STATS_COLLECTION = "dataset_stats"
TARGET_IMPORT_JOBS_COLLECTION = "import_jobs"
TARGET_IMPORT_CHECKPOINTS_COLLECTION = "import_checkpoints"
TARGET_UPLOAD_JOBS_COLLECTION = "upload_jobs"
TARGET_UPLOAD_CHECKPOINTS_COLLECTION = "upload_checkpoints"
TARGET_MIGRATION_MANIFESTS_COLLECTION = "migration_manifests"
TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION = "migration_manifest_records"
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
DEFAULT_PI1M_SAMPLE_SIZE: int | None = None
DEFAULT_PI1M_CHUNK_SIZE = 50000
DEFAULT_EXTRA_SAMPLE_SIZE: int | None = None
DEFAULT_UPLOAD_WORKERS = 8
DEFAULT_UPLOAD_RETRIES = 3
UPLOAD_MULTIPART_THRESHOLD = 64 * 1024 * 1024
UPLOAD_PART_SIZE = 64 * 1024 * 1024
UPLOAD_READ_CHUNK_SIZE = 8 * 1024 * 1024
MANIFEST_KEY = "manifests/poly_data_manifest.json"
LOCAL_MANIFEST_PATH = Path(".runtime/data_catalog/poly_data_manifest.json")
MONGO_MANIFEST_RECORD_CHUNK_BYTES = 8 * 1024 * 1024
MD_ALLATOM_STRUCTURED_OBJECT_KEYS = {
    "diamine": "datasets/md_allatom/structured/diamine.csv",
    "dianhydride": "datasets/md_allatom/structured/dianhydride.csv",
    "carbon": "datasets/md_allatom/structured/carbon.csv",
    "requirements_doc": "datasets/md_allatom/docs/integration_requirements.docx",
}


class MigrationCancelled(RuntimeError):
    """Raised when a migration receives a shutdown request."""


class MigrationConfigurationError(ValueError):
    """Raised when an applied migration lacks required configuration."""


CANCEL_EVENT = threading.Event()


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
    *[
        SftpObjectMigrationRecord(
            dataset_id=spec.dataset_id,
            role=file_spec.role,
            remote_relative_path=file_spec.remote_relative_path,
            object_key=file_spec.object_key,
            content_type=file_spec.content_type,
        )
        for spec in EXTRA_DATASET_SPECS
        for file_spec in spec.files
    ],
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

    def put_object_multipart(
        self,
        bucket: str,
        object_key: str,
        chunks: Any,
        *,
        content_type: str,
        part_size: int = 64 * 1024 * 1024,
    ) -> None:
        """Upload an object using S3 multipart upload from a byte chunk iterator."""
        upload_id = self._create_multipart_upload(bucket, object_key, content_type=content_type)
        parts: list[dict[str, Any]] = []
        try:
            buffer = bytearray()
            part_number = 1
            for chunk in chunks:
                if not chunk:
                    continue
                buffer.extend(chunk)
                while len(buffer) >= part_size:
                    payload = bytes(buffer[:part_size])
                    del buffer[:part_size]
                    etag = self._upload_part(bucket, object_key, upload_id, part_number, payload)
                    parts.append({"part_number": part_number, "etag": etag})
                    part_number += 1
            if buffer or not parts:
                etag = self._upload_part(bucket, object_key, upload_id, part_number, bytes(buffer))
                parts.append({"part_number": part_number, "etag": etag})
            self._complete_multipart_upload(bucket, object_key, upload_id, parts)
        except BaseException:
            self._abort_multipart_upload(bucket, object_key, upload_id)
            raise

    def list_objects(self, bucket: str, prefix: str) -> dict[str, dict[str, Any]]:
        """List object metadata under a prefix without generating HEAD 404 responses."""
        objects: dict[str, dict[str, Any]] = {}
        continuation: str | None = None
        while True:
            query = {
                "list-type": "2",
                "prefix": prefix,
                "max-keys": "1000",
                "encoding-type": "url",
            }
            if continuation:
                query["continuation-token"] = continuation
            request = self._signed_request("GET", bucket, "", query=query)
            with urllib.request.urlopen(request, timeout=120) as response:
                root = ET.fromstring(response.read())
            for item in root.findall(".//{*}Contents"):
                encoded_key = item.findtext("{*}Key") or ""
                object_key = urllib.parse.unquote(encoded_key)
                if not object_key:
                    continue
                objects[object_key] = {
                    "size_bytes": int(item.findtext("{*}Size") or 0),
                    "etag": (item.findtext("{*}ETag") or "").strip('"'),
                    "last_modified": item.findtext("{*}LastModified"),
                }
            if (root.findtext("{*}IsTruncated") or "false").lower() != "true":
                break
            continuation = root.findtext("{*}NextContinuationToken") or None
            if not continuation:
                break
        return objects

    def list_multipart_uploads(self, bucket: str, prefix: str) -> list[dict[str, str]]:
        """List incomplete multipart uploads under a migration-owned prefix."""
        uploads: list[dict[str, str]] = []
        key_marker: str | None = None
        upload_id_marker: str | None = None
        while True:
            query = {"uploads": "", "prefix": prefix, "max-uploads": "1000", "encoding-type": "url"}
            if key_marker:
                query["key-marker"] = key_marker
            if upload_id_marker:
                query["upload-id-marker"] = upload_id_marker
            request = self._signed_request("GET", bucket, "", query=query)
            with urllib.request.urlopen(request, timeout=120) as response:
                root = ET.fromstring(response.read())
            for item in root.findall(".//{*}Upload"):
                key = urllib.parse.unquote(item.findtext("{*}Key") or "")
                upload_id = item.findtext("{*}UploadId") or ""
                if key and upload_id:
                    uploads.append({"object_key": key, "upload_id": upload_id})
            if (root.findtext("{*}IsTruncated") or "false").lower() != "true":
                break
            key_marker = root.findtext("{*}NextKeyMarker") or None
            upload_id_marker = root.findtext("{*}NextUploadIdMarker") or None
            if not key_marker:
                break
        return uploads

    def abort_multipart_upload(self, bucket: str, object_key: str, upload_id: str) -> None:
        """Abort one explicitly selected incomplete multipart upload."""
        self._abort_multipart_upload(bucket, object_key, upload_id)

    def _create_multipart_upload(self, bucket: str, object_key: str, *, content_type: str) -> str:
        request = self._signed_request(
            "POST",
            bucket,
            object_key,
            query={"uploads": ""},
            headers={"content-type": content_type},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            root = ET.fromstring(response.read())
        upload_id = root.findtext(".//{*}UploadId") or root.findtext("UploadId")
        if not upload_id:
            raise RuntimeError("MinIO multipart upload did not return UploadId")
        return upload_id

    def _upload_part(self, bucket: str, object_key: str, upload_id: str, part_number: int, payload: bytes) -> str:
        request = self._signed_request(
            "PUT",
            bucket,
            object_key,
            query={"partNumber": str(part_number), "uploadId": upload_id},
            body=payload,
        )
        with urllib.request.urlopen(request, timeout=300) as response:
            response.read()
            return (response.headers.get("ETag") or "").strip('"')

    def _complete_multipart_upload(
        self,
        bucket: str,
        object_key: str,
        upload_id: str,
        parts: list[dict[str, Any]],
    ) -> None:
        body = (
            "<CompleteMultipartUpload>"
            + "".join(
                f"<Part><PartNumber>{part['part_number']}</PartNumber><ETag>\"{part['etag']}\"</ETag></Part>"
                for part in parts
            )
            + "</CompleteMultipartUpload>"
        ).encode("utf-8")
        request = self._signed_request(
            "POST",
            bucket,
            object_key,
            query={"uploadId": upload_id},
            body=body,
            headers={"content-type": "application/xml"},
        )
        with urllib.request.urlopen(request, timeout=120) as response:
            response.read()

    def _abort_multipart_upload(self, bucket: str, object_key: str, upload_id: str) -> None:
        request = self._signed_request(
            "DELETE",
            bucket,
            object_key,
            query={"uploadId": upload_id},
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                response.read()
        except Exception:
            pass

    def delete_object(self, bucket: str, object_key: str) -> None:
        request = self._signed_request("DELETE", bucket, object_key)
        with urllib.request.urlopen(request, timeout=30) as response:
            response.read()

    def get_object(self, bucket: str, object_key: str) -> bytes:
        """Download one object."""
        request = self._signed_request("GET", bucket, object_key)
        with urllib.request.urlopen(request, timeout=120) as response:
            return response.read()

    def open_object(self, bucket: str, object_key: str) -> Any:
        """Open an object as a streaming HTTP response; caller must close it."""
        request = self._signed_request("GET", bucket, object_key)
        return urllib.request.urlopen(request, timeout=300)

    def _signed_request(
        self,
        method: str,
        bucket: str,
        object_key: str,
        *,
        query: dict[str, str] | None = None,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> urllib.request.Request:
        headers = {key.lower(): value for key, value in (headers or {}).items()}
        parsed_endpoint = urllib.parse.urlparse(self.endpoint)
        host = parsed_endpoint.netloc
        encoded_key = urllib.parse.quote(object_key, safe="/-_.~")
        canonical_uri = f"/{bucket}{('/' + encoded_key) if encoded_key else ''}"
        canonical_query = self._canonical_query(query or {})
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
        canonical_request = "\n".join([method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash])
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
            f"{self.endpoint}{canonical_uri}{('?' + canonical_query) if canonical_query else ''}",
            method=method,
            headers=request_headers,
            data=body if method in {"PUT", "POST"} else None,
        )

    def _canonical_query(self, query: dict[str, str]) -> str:
        return "&".join(
            f"{urllib.parse.quote(str(key), safe='-_.~')}={urllib.parse.quote(str(value), safe='-_.~')}"
            for key, value in sorted(query.items())
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
        self._sftp.get_channel().settimeout(300)

    def stat_file(self, remote_path: str) -> dict[str, Any]:
        attrs = self._sftp.stat(remote_path)
        return {
            "size_bytes": int(attrs.st_size or 0),
            "mtime": datetime.fromtimestamp(float(attrs.st_mtime or 0), tz=timezone.utc).isoformat(),
        }

    def read_file(self, remote_path: str) -> bytes:
        with self._sftp.open(remote_path, "rb") as fp:
            return fp.read()

    def read_file_chunks(self, remote_path: str, *, chunk_size: int = 8 * 1024 * 1024) -> Any:
        with self._sftp.open(remote_path, "rb") as fp:
            while True:
                chunk = fp.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    def list_files_recursive(self, remote_root: str) -> list[dict[str, Any]]:
        """Return all files under a remote directory with paths relative to the root."""
        root = remote_root.rstrip("/")
        files: list[dict[str, Any]] = []

        def walk(current: str) -> None:
            if CANCEL_EVENT.is_set():
                raise MigrationCancelled("migration cancelled")
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
        try:
            self._sftp.close()
        finally:
            self._ssh.close()


def validate_runtime_configuration(args: argparse.Namespace, *, sftp_password: str) -> None:
    """Fail before any mutation when an applied SFTP migration is misconfigured."""
    if not args.apply:
        return
    if not 1 <= int(args.upload_workers) <= 64:
        raise MigrationConfigurationError("--upload-workers must be between 1 and 64")
    if not 0 <= int(args.upload_retries) <= 10:
        raise MigrationConfigurationError("--upload-retries must be between 0 and 10")
    if not (args.migrate_sftp_open_databases or args.migrate_sftp_md_allatom):
        return
    missing: list[str] = []
    if not sftp_password:
        missing.append(args.sftp_password_env)
    if not args.endpoint:
        missing.append("MINIO_ENDPOINT/--endpoint")
    if not args.access_key:
        missing.append("MINIO_ACCESS_KEY/--access-key")
    if not args.secret_key:
        missing.append("MINIO_SECRET_KEY/--secret-key")
    if not args.mongodb_uri:
        missing.append("DATA_ASSET_MONGODB_URI/--mongodb-uri")
    if missing:
        raise MigrationConfigurationError("missing required migration configuration: " + ", ".join(missing))


def _load_target_inventory(s3_client: Any, bucket: str, prefixes: list[str]) -> dict[str, dict[str, Any]] | None:
    if s3_client is None or not hasattr(s3_client, "list_objects"):
        return None
    inventory: dict[str, dict[str, Any]] = {}
    for prefix in sorted(set(prefixes)):
        inventory.update(s3_client.list_objects(bucket, prefix))
    return inventory


def cleanup_incomplete_multipart_uploads(s3_client: Any, *, bucket: str, prefixes: list[str]) -> int:
    """Abort only incomplete uploads under explicitly supplied migration prefixes."""
    if s3_client is None or not hasattr(s3_client, "list_multipart_uploads"):
        return 0
    cleaned = 0
    for prefix in sorted(set(prefixes)):
        for upload in s3_client.list_multipart_uploads(bucket, prefix):
            s3_client.abort_multipart_upload(bucket, upload["object_key"], upload["upload_id"])
            cleaned += 1
    return cleaned


def _persist_upload_checkpoint(target_db: Any, record: dict[str, Any], *, job_id: str) -> None:
    if target_db is None or not record.get("object_key"):
        return
    target_db[TARGET_UPLOAD_CHECKPOINTS_COLLECTION].update_one(
        {"bucket": record.get("bucket"), "object_key": record["object_key"]},
        {
            "$set": {
                "job_id": job_id,
                "dataset_id": record.get("dataset_id"),
                "family": record.get("family"),
                "role": record.get("role"),
                "remote_path": record.get("remote_path"),
                "source": record.get("remote"),
                "target": record.get("target"),
                "status": record.get("status"),
                "attempts": int(record.get("attempts") or 0),
                "error": record.get("error"),
                "updated_at": datetime.now(timezone.utc),
            }
        },
        upsert=True,
    )


def _persist_dataset_object(target_db: Any, record: dict[str, Any]) -> None:
    if target_db is None or not record.get("object_key"):
        return
    target_db["dataset_objects"].update_one(
        {"object_key": record["object_key"]},
        {"$set": {**record, "updated_at": datetime.now(timezone.utc)}},
        upsert=True,
    )


def _start_upload_job(
    target_db: Any,
    *,
    job_id: str,
    job_type: str,
    records: list[dict[str, Any]],
    upload_workers: int,
) -> None:
    if target_db is None:
        return
    now = datetime.now(timezone.utc)
    target_db[TARGET_UPLOAD_JOBS_COLLECTION].update_one(
        {"job_id": job_id},
        {
            "$set": {
                "job_id": job_id,
                "job_type": job_type,
                "status": "running",
                "worker_count": upload_workers,
                "total_files": len(records),
                "total_bytes": sum(int((record.get("remote") or {}).get("size_bytes") or 0) for record in records),
                "completed_files": 0,
                "skipped_files": 0,
                "failed_files": 0,
                "uploaded_bytes": 0,
                "started_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )


def _update_upload_job(target_db: Any, *, job_id: str, record: dict[str, Any]) -> None:
    if target_db is None:
        return
    status = record.get("status")
    increments: dict[str, int] = {}
    if status == "uploaded":
        increments = {
            "completed_files": 1,
            "uploaded_bytes": int((record.get("target") or {}).get("size_bytes") or 0),
        }
    elif status == "already_migrated":
        increments = {"completed_files": 1, "skipped_files": 1}
    elif status in {"failed", "verify_failed"}:
        increments = {"failed_files": 1}
    update: dict[str, Any] = {"$set": {"updated_at": datetime.now(timezone.utc)}}
    if increments:
        update["$inc"] = increments
    target_db[TARGET_UPLOAD_JOBS_COLLECTION].update_one({"job_id": job_id}, update, upsert=True)


def _finish_upload_job(target_db: Any, *, job_id: str, records: list[dict[str, Any]], cancelled: bool) -> None:
    if target_db is None:
        return
    failed = any(record.get("status") in {"failed", "verify_failed"} for record in records)
    now = datetime.now(timezone.utc)
    target_db[TARGET_UPLOAD_JOBS_COLLECTION].update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": "cancelled" if cancelled else ("failed" if failed else "completed"),
                "finished_at": now,
                "updated_at": now,
            }
        },
        upsert=True,
    )


def _cancellable_chunks(sftp_client: Any, remote_path: str, cancel_event: threading.Event) -> Any:
    for chunk in sftp_client.read_file_chunks(remote_path, chunk_size=UPLOAD_READ_CHUNK_SIZE):
        if cancel_event.is_set():
            raise MigrationCancelled("migration cancelled")
        yield chunk


def _describe_upload_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTPError {exc.code} {exc.reason}"
    return f"{exc.__class__.__name__}: {exc}"


def _upload_one_record(
    record: dict[str, Any],
    *,
    sftp_client: Any,
    s3_client: Any,
    bucket: str,
    target_inventory: dict[str, dict[str, Any]] | None,
    upload_retries: int,
    cancel_event: threading.Event,
) -> dict[str, Any]:
    result = dict(record)
    object_key = str(result["object_key"])
    remote = result.get("remote") or {}
    target = target_inventory.get(object_key) if target_inventory is not None else s3_client.head_object(bucket, object_key)
    result["target"] = target
    result["target_exists"] = target is not None
    result["attempts"] = 0
    if target and int(target.get("size_bytes") or 0) == int(remote.get("size_bytes") or 0):
        result["status"] = "already_migrated"
        result["error"] = None
        return result

    for attempt in range(1, upload_retries + 2):
        result["attempts"] = attempt
        if cancel_event.is_set():
            raise MigrationCancelled("migration cancelled")
        try:
            remote_size = int(remote.get("size_bytes") or 0)
            if remote_size >= UPLOAD_MULTIPART_THRESHOLD and hasattr(s3_client, "put_object_multipart"):
                s3_client.put_object_multipart(
                    bucket,
                    object_key,
                    _cancellable_chunks(sftp_client, str(result["remote_path"]), cancel_event),
                    content_type=str(result.get("content_type") or "application/octet-stream"),
                    part_size=UPLOAD_PART_SIZE,
                )
            else:
                content = sftp_client.read_file(str(result["remote_path"]))
                if cancel_event.is_set():
                    raise MigrationCancelled("migration cancelled")
                s3_client.put_object(
                    bucket,
                    object_key,
                    content,
                    str(result.get("content_type") or "application/octet-stream"),
                )
            target = s3_client.head_object(bucket, object_key)
            result["target"] = target
            result["target_exists"] = target is not None
            if target and int(target.get("size_bytes") or 0) == remote_size:
                result["status"] = "uploaded"
                result["error"] = None
                return result
            result["status"] = "verify_failed"
            result["error"] = "size mismatch"
        except MigrationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - retry and persist external boundary failures.
            result["status"] = "failed"
            result["error"] = _describe_upload_error(exc)
        if attempt <= upload_retries:
            time.sleep(2 ** (attempt - 1))
    return result


def upload_records_concurrently(
    records: list[dict[str, Any]],
    *,
    sftp_client: Any,
    sftp_client_factory: Any | None,
    s3_client: Any,
    target_db: Any,
    bucket: str,
    job_type: str,
    upload_workers: int,
    upload_retries: int,
    target_inventory: dict[str, dict[str, Any]] | None,
    on_record_complete: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Upload records with bounded concurrency and durable file-level checkpoints."""
    if not records:
        return []
    cancel_event = cancel_event or CANCEL_EVENT
    workers = max(1, min(int(upload_workers), 64))
    job_id = f"{job_type}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    _start_upload_job(target_db, job_id=job_id, job_type=job_type, records=records, upload_workers=workers)
    results: list[dict[str, Any] | None] = [None] * len(records)
    thread_local = threading.local()
    owned_clients: list[Any] = []
    clients_lock = threading.Lock()
    progress_lock = threading.Lock()
    progress = {"processed": 0, "completed": 0, "skipped": 0, "failed": 0, "uploaded_bytes": 0}
    progress_started = monotonic()
    last_progress_log = [progress_started]

    def report_progress(record: dict[str, Any]) -> None:
        status = record.get("status")
        now = monotonic()
        with progress_lock:
            progress["processed"] += 1
            if status == "uploaded":
                progress["completed"] += 1
                progress["uploaded_bytes"] += int((record.get("target") or {}).get("size_bytes") or 0)
            elif status == "already_migrated":
                progress["completed"] += 1
                progress["skipped"] += 1
            elif status in {"failed", "verify_failed"}:
                progress["failed"] += 1
            should_log = (
                status in {"failed", "verify_failed"}
                or now - last_progress_log[0] >= 10
                or progress["processed"] == len(records)
            )
            if not should_log:
                return
            elapsed = max(now - progress_started, 0.001)
            throughput = progress["uploaded_bytes"] / 1024 / 1024 / elapsed
            print(
                f"[upload] job={job_id} processed={progress['processed']}/{len(records)} "
                f"completed={progress['completed']} skipped={progress['skipped']} failed={progress['failed']} "
                f"throughput={throughput:.2f}MiB/s key={record.get('object_key')} status={status}",
                flush=True,
            )
            last_progress_log[0] = now

    def worker_client() -> Any:
        if sftp_client_factory is None:
            return sftp_client
        client = getattr(thread_local, "sftp_client", None)
        if client is None:
            client = sftp_client_factory()
            thread_local.sftp_client = client
            with clients_lock:
                owned_clients.append(client)
        return client

    def run_one(index: int) -> tuple[int, dict[str, Any]]:
        record = dict(records[index])
        try:
            result = _upload_one_record(
                record,
                sftp_client=worker_client(),
                s3_client=s3_client,
                bucket=bucket,
                target_inventory=target_inventory,
                upload_retries=upload_retries,
                cancel_event=cancel_event,
            )
        except MigrationCancelled:
            result = {**record, "status": "cancelled", "error": "migration cancelled"}
        except Exception as exc:  # noqa: BLE001 - isolate connection/worker failures to one file.
            result = {
                **record,
                "status": "failed",
                "attempts": int(record.get("attempts") or 0),
                "error": _describe_upload_error(exc),
            }
        if result.get("status") != "cancelled" and not cancel_event.is_set():
            _persist_upload_checkpoint(target_db, result, job_id=job_id)
            _persist_dataset_object(target_db, result)
            if on_record_complete is not None:
                on_record_complete(result)
            _update_upload_job(target_db, job_id=job_id, record=result)
        report_progress(result)
        return index, result

    try:
        if workers == 1:
            for index in range(len(records)):
                if cancel_event.is_set():
                    break
                result_index, result = run_one(index)
                results[result_index] = result
        else:
            max_in_flight = min(32, workers * 4)
            next_index = 0
            futures: dict[Future[tuple[int, dict[str, Any]]], int] = {}
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="poly-upload") as executor:
                while next_index < len(records) or futures:
                    while not cancel_event.is_set() and next_index < len(records) and len(futures) < max_in_flight:
                        future = executor.submit(run_one, next_index)
                        futures[future] = next_index
                        next_index += 1
                    if not futures:
                        break
                    completed, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in completed:
                        futures.pop(future, None)
                        result_index, result = future.result()
                        results[result_index] = result
        finalized = [result for result in results if result is not None]
        cancelled = cancel_event.is_set() or any(result.get("status") == "cancelled" for result in finalized)
        if not cancelled:
            _finish_upload_job(target_db, job_id=job_id, records=finalized, cancelled=False)
        return finalized
    finally:
        for client in owned_clients:
            try:
                client.close()
            except Exception:
                pass


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
    if dataset_id in EXTRA_TARGET_COLLECTIONS:
        return {
            "record_collection_key": f"poly_data.{EXTRA_TARGET_COLLECTIONS[dataset_id]}",
        }
    if dataset_id == "openpoly":
        return {
            "record_collection_key": "poly_data.material_records",
        }
    if dataset_id == "radonpy_pi1070":
        return {
            "record_collection_key": "poly_data.radonpy_records",
        }
    if dataset_id == "pi1m_v2":
        return {
            "record_collection_key": "poly_data.pi1m_samples",
        }
    if dataset_id == "smipoly":
        return {
            "record_collection_key": "poly_data.smipoly_monomers",
        }
    if dataset_id == "polyuniverse":
        return {
            "record_collection_key": "poly_data.polyuniverse_monomers",
        }
    if dataset_id == "md_allatom":
        return {
            "record_collection_key": "poly_data.md_allatom_carbon_results",
        }
    return {"record_collection_key": None}


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
        except MigrationCancelled:
            raise
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
    dataset_ids: list[str] | None = None,
    apply: bool,
    target_db: Any | None = None,
    upload_workers: int = 1,
    upload_retries: int = DEFAULT_UPLOAD_RETRIES,
    sftp_client_factory: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Upload source SFTP files into canonical MinIO dataset keys."""
    records: list[dict[str, Any]] = []
    root = sftp_root.rstrip("/")
    requested = {item.strip() for item in (dataset_ids or []) if item.strip()}
    if apply and target_db is not None:
        create_indexes(target_db)
    for mapping in SFTP_OBJECT_MIGRATIONS:
        if cancel_event is not None and cancel_event.is_set():
            break
        if requested and mapping.dataset_id not in requested:
            continue
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
            record["remote"] = sftp_client.stat_file(remote_path) if sftp_client else None
            if apply and sftp_client is None:
                record["status"] = "skipped"
                record["error"] = "SFTP client is not configured"
            elif apply and s3_client is None:
                record["status"] = "skipped"
                record["error"] = "MinIO client is not configured"
            elif apply and record["remote"] is None:
                record["status"] = "missing_source"
        except MigrationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - manifest must preserve per-object failure.
            record["status"] = "failed"
            record["error"] = _describe_upload_error(exc)
        records.append(record)

    if not apply or sftp_client is None or s3_client is None:
        return records
    uploadable = [record for record in records if record.get("status") == "planned" and record.get("remote")]
    inventory = _load_target_inventory(
        s3_client,
        bucket,
        [f"datasets/{record['dataset_id']}/" for record in uploadable],
    )
    uploaded = upload_records_concurrently(
        uploadable,
        sftp_client=sftp_client,
        sftp_client_factory=sftp_client_factory,
        s3_client=s3_client,
        target_db=target_db,
        bucket=bucket,
        job_type="open-databases",
        upload_workers=upload_workers,
        upload_retries=upload_retries,
        target_inventory=inventory,
        cancel_event=cancel_event,
    )
    uploaded_by_key = {record["object_key"]: record for record in uploaded}
    records = [uploaded_by_key.get(record.get("object_key"), record) for record in records]
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
    upload_workers: int = 1,
    upload_retries: int = DEFAULT_UPLOAD_RETRIES,
    sftp_client_factory: Any | None = None,
    cancel_event: threading.Event | None = None,
) -> list[dict[str, Any]]:
    """Upload MD-AllAtom raw SFTP files into MinIO and index them in MongoDB."""
    records: list[dict[str, Any]] = []
    family_records_by_name: dict[str, list[dict[str, Any]]] = {}
    normalized_families = [family.strip() for family in families if family.strip()]
    for family in normalized_families:
        remote_family_root = f"{md_root.rstrip('/')}/{family}"
        if sftp_client is None:
            records.append({
                "dataset_id": "md_allatom",
                "role": "family_preflight",
                "family": family,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_family_root,
                "remote_file_count": None,
                "remote_total_size": None,
                "status": "skipped",
                "error": "SFTP client is not configured",
            })
            continue
        try:
            family_files = sftp_client.list_files_recursive(remote_family_root)
        except FileNotFoundError:
            records.append({
                "dataset_id": "md_allatom",
                "role": "family_preflight",
                "family": family,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_family_root,
                "remote_file_count": 0,
                "remote_total_size": 0,
                "status": "missing_source",
                "error": "remote family directory does not exist",
            })
            continue
        except PermissionError as exc:
            records.append({
                "dataset_id": "md_allatom",
                "role": "family_preflight",
                "family": family,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_family_root,
                "remote_file_count": None,
                "remote_total_size": None,
                "status": "inaccessible_source",
                "error": f"{exc.__class__.__name__}: {exc}",
            })
            continue
        except MigrationCancelled:
            raise
        except Exception as exc:  # noqa: BLE001 - preflight result must preserve source failures.
            records.append({
                "dataset_id": "md_allatom",
                "role": "family_preflight",
                "family": family,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_family_root,
                "remote_file_count": None,
                "remote_total_size": None,
                "status": "failed",
                "error": f"{exc.__class__.__name__}: {exc}",
            })
            continue
        if not family_files:
            records.append({
                "dataset_id": "md_allatom",
                "role": "family_preflight",
                "family": family,
                "bucket": bucket,
                "sftp_host": sftp_host,
                "remote_path": remote_family_root,
                "remote_file_count": 0,
                "remote_total_size": 0,
                "status": "empty_source",
                "error": "remote family directory is empty",
            })
            continue
        family_records: list[dict[str, Any]] = []
        for file_info in family_files:
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
            record["content_type"] = "application/octet-stream"
            family_records.append(record)
        family_records_by_name[family] = family_records
        records.extend(family_records)

    if apply and target_db is not None:
        create_indexes(target_db)

    raw_records = [record for record in records if record.get("role") == "raw_file"]
    if apply and raw_records and sftp_client is not None and s3_client is not None:
        inventory = _load_target_inventory(
            s3_client,
            bucket,
            [f"datasets/md_allatom/raw/{family}/" for family in normalized_families],
        )

        def persist_md_file(record: dict[str, Any]) -> None:
            if target_db is None or record.get("status") not in {"uploaded", "already_migrated"}:
                return
            document = build_md_allatom_file_document(record, family=str(record["family"]), index=0)
            target_db[TARGET_MD_ALLATOM_FILES_COLLECTION].update_one(
                {"md_allatom_file_id": document["md_allatom_file_id"]},
                {"$set": document},
                upsert=True,
            )

        uploaded = upload_records_concurrently(
            raw_records,
            sftp_client=sftp_client,
            sftp_client_factory=sftp_client_factory,
            s3_client=s3_client,
            target_db=target_db,
            bucket=bucket,
            job_type="md-allatom",
            upload_workers=upload_workers,
            upload_retries=upload_retries,
            target_inventory=inventory,
            on_record_complete=persist_md_file,
            cancel_event=cancel_event,
        )
        uploaded_by_key = {record["object_key"]: record for record in uploaded}
        records = [uploaded_by_key.get(record.get("object_key"), record) for record in records]
        family_records_by_name = {
            family: [uploaded_by_key.get(record["object_key"], record) for record in family_records]
            for family, family_records in family_records_by_name.items()
        }

    if apply and target_db is not None:
        collection = target_db[TARGET_MD_ALLATOM_FILES_COLLECTION]
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "md_allatom"},
            {
                "$set": {
                    "dataset_id": "md_allatom",
                    "asset_coverage": {
                        "file_count": int(collection.count_documents({})),
                        "families": {
                            family: int(collection.count_documents({"family": family}))
                            for family in ("C", "F", "Si")
                        },
                    },
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
    if apply and s3_client is not None:
        for family, family_records in family_records_by_name.items():
            successful = [
                record
                for record in family_records
                if record.get("status") in {"uploaded", "already_migrated"}
            ]
            remote_file_count = len(family_records)
            minio_object_count = sum(
                1 for record in family_records if record.get("target_exists")
            )
            mongo_index_count = (
                int(target_db[TARGET_MD_ALLATOM_FILES_COLLECTION].count_documents({"family": family}))
                if target_db is not None
                else 0
            )
            counts_consistent = (
                len(successful)
                == remote_file_count
                == minio_object_count
                == mongo_index_count
            )
            manifest = {
                "dataset_id": "md_allatom",
                "family": family,
                "remote_root": f"{md_root.rstrip('/')}/{family}",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "sync_status": "verified" if counts_consistent else "partial_failure",
                "counts_consistent": counts_consistent,
                "file_count": remote_file_count,
                "remote_file_count": remote_file_count,
                "remote_total_size": sum(
                    int((record.get("remote") or {}).get("size_bytes") or 0)
                    for record in family_records
                ),
                "minio_object_count": minio_object_count,
                "mongo_index_count": mongo_index_count,
                "records": family_records,
            }
            s3_client.put_object(
                bucket,
                f"datasets/md_allatom/manifests/{family}.json",
                json.dumps(manifest, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
                "application/json; charset=utf-8",
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
    for spec in EXTRA_DATASET_SPECS:
        collection = target_db[spec.collection_name]
        collection.create_index([("record_id", 1)], name="record_id", unique=True)
        collection.create_index([("dataset.dataset_id", 1), ("row_index", 1)], name="dataset_row")
        collection.create_index([("source_file", 1), ("row_index", 1)], name="source_row")
        collection.create_index([("title", 1)], name="title")
    target_db[TARGET_MIGRATION_MANIFESTS_COLLECTION].create_index([("generated_at", -1)], name="generated_at")
    target_db[TARGET_MIGRATION_MANIFESTS_COLLECTION].create_index(
        [("manifest_id", 1)],
        name="manifest_id",
        unique=True,
        partialFilterExpression={"manifest_id": {"$type": "string"}},
    )
    target_db[TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION].create_index(
        [("manifest_id", 1), ("section", 1), ("chunk_index", 1)], name="manifest_section_chunk", unique=True
    )
    target_db[TARGET_DATASET_STATS_COLLECTION].create_index([("dataset_id", 1)], name="dataset_id", unique=True)
    target_db[TARGET_IMPORT_JOBS_COLLECTION].create_index([("job_id", 1)], name="job_id", unique=True)
    target_db[TARGET_IMPORT_JOBS_COLLECTION].create_index([("dataset_id", 1), ("started_at", -1)], name="dataset_started")
    target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].create_index(
        [("job_id", 1), ("chunk_index", 1)], name="job_chunk", unique=True
    )
    target_db[TARGET_UPLOAD_JOBS_COLLECTION].create_index([("job_id", 1)], name="job_id", unique=True)
    target_db[TARGET_UPLOAD_JOBS_COLLECTION].create_index([("started_at", -1)], name="started_at")
    target_db[TARGET_UPLOAD_CHECKPOINTS_COLLECTION].create_index(
        [("bucket", 1), ("object_key", 1)], name="bucket_object_key", unique=True
    )
    target_db[TARGET_UPLOAD_CHECKPOINTS_COLLECTION].create_index(
        [("job_id", 1), ("status", 1)], name="job_status"
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
                "smipoly_record_id": f"SMIPOLY-{index:06d}",
                "dataset": {"dataset_id": "smipoly", "dataset_name": "SMiPoly"},
                "com_id": com_id,
                "molecular_formula": first_present(row, ["MolecularFormula", "molecular_formula"]),
                "molecular_weight": first_present(row, ["MolecularWeight", "molecular_weight"]),
                "smiles": first_present(row, ["SMILES", "smiles"]),
                "iupac_name": first_present(row, ["IUPACName", "iupac_name"]),
                "source_file": "202207_smip_monset.csv",
                "source_row_index": index,
                "row_index": index,
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


def build_extra_dataset_documents(
    dataframe: Any,
    *,
    dataset_spec: ExtraDatasetSpec,
    file_spec: DatasetFileSpec,
    start_index: int = 1,
    source_start_index: int = 1,
) -> list[dict[str, Any]]:
    """Build generic Mongo documents for processed 05–16 open database tables."""
    docs: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)
    source_file = Path(file_spec.remote_relative_path).name
    records = dataframe.to_dict(orient="records")
    for offset, raw in enumerate(records):
        row_index = start_index + offset
        source_row_index = source_start_index + offset
        row = normalized_row(raw)
        title = first_present(row, list(file_spec.title_fields)) or first_present(
            row,
            [
                "smiles",
                "SMILES",
                "Smiles",
                "product",
                "polymer_smiles",
                "smiles_polymer",
                "polymer",
                "Polymer",
                "UUID",
                "name",
            ],
        )
        record_prefix = file_spec.record_prefix or dataset_spec.dataset_id.upper()
        doc: dict[str, Any] = {
            "record_id": f"{record_prefix}-{source_row_index:08d}",
            "dataset": {"dataset_id": dataset_spec.dataset_id, "dataset_name": dataset_spec.display_name},
            "source_file": source_file,
            "source_table": file_spec.table_name or Path(source_file).stem,
            "row_index": row_index,
            "source_row_index": source_row_index,
            "title": str(title) if title is not None else f"{dataset_spec.display_name} #{source_row_index}",
            "smiles": first_present(
                row,
                [
                    "smiles",
                    "SMILES",
                    "Smiles",
                    "product",
                    "methyl_terminated_product",
                    "polymer_smiles",
                    "smiles_polymer",
                    "smiles_list",
                    "smiles_monomer",
                    "mono_smiles",
                    "mono1_smiles",
                    "mono2_smiles",
                ],
            ),
            "raw": row,
            "created_at": now,
            "updated_at": now,
        }
        for field_name in file_spec.exposed_fields:
            value = first_present(row, [field_name])
            if value is not None:
                doc[str(field_name).strip()] = value
        docs.append(doc)
    return docs


def source_object_stream_or_bytes(s3_client: Any, bucket: str, object_key: str) -> Any:
    """Return a context manager or byte buffer for reading a MinIO object."""
    if hasattr(s3_client, "open_object"):
        return s3_client.open_object(bucket, object_key)
    return BytesIO(s3_client.get_object(bucket, object_key))


def iter_extra_dataset_frames(
    *,
    s3_client: Any,
    bucket: str,
    file_spec: DatasetFileSpec,
    remaining: int | None,
) -> Any:
    """Yield pandas dataframes for one generic dataset file."""
    import pandas as pd

    if file_spec.file_format == "xlsx":
        dataframe = pd.read_excel(
            BytesIO(s3_client.get_object(bucket, file_spec.object_key)),
            sheet_name=file_spec.sheet_name or 0,
        )
        if remaining is not None:
            dataframe = dataframe.head(max(remaining, 0))
        if len(dataframe):
            yield dataframe
        return

    read_kwargs: dict[str, Any] = {
        "chunksize": max(int(file_spec.chunksize), 1),
    }
    if remaining is not None:
        read_kwargs["nrows"] = max(int(remaining), 0)
    if file_spec.separator is not None:
        read_kwargs["sep"] = file_spec.separator
    if file_spec.file_format == "tsv":
        read_kwargs["sep"] = "\t"
    if file_spec.file_format == "txt":
        read_kwargs.update({"header": None, "names": ["smiles"]})
    source = source_object_stream_or_bytes(s3_client, bucket, file_spec.object_key)
    close = getattr(source, "close", None)
    try:
        for dataframe in pd.read_csv(source, **read_kwargs):
            if len(dataframe):
                yield dataframe
    finally:
        if callable(close):
            close()


def update_extra_dataset_stats(
    stats: dict[str, Any],
    *,
    documents: list[dict[str, Any]],
    file_spec: DatasetFileSpec,
    sample_limit: int = 5000,
    value_limit: int = 50000,
) -> None:
    """Accumulate compact stats for generic processed datasets."""
    category_counts = stats.setdefault("category_counts", {})
    source_counts = category_counts.setdefault("source_file", {})
    table_counts = category_counts.setdefault("source_table", {})
    numeric_values = stats.setdefault("_numeric_values", {})
    samples = stats.setdefault("analysis_samples", [])
    for doc in documents:
        source_file = str(doc.get("source_file") or "")
        source_table = str(doc.get("source_table") or "")
        if source_file:
            source_counts[source_file] = source_counts.get(source_file, 0) + 1
        if source_table:
            table_counts[source_table] = table_counts.get(source_table, 0) + 1
        first_numeric: float | None = None
        for field_name in file_spec.exposed_fields:
            value = as_float(doc.get(field_name))
            if value is None:
                continue
            values = numeric_values.setdefault(field_name, [])
            if len(values) < value_limit:
                values.append(value)
            if first_numeric is None:
                first_numeric = value
        if len(samples) < sample_limit:
            samples.append(
                {
                    "record_id": doc["record_id"],
                    "x": doc.get("row_index"),
                    "y": first_numeric,
                    "category": source_table or source_file,
                    "title": doc.get("title"),
                    "source_file": source_file,
                }
            )


def finalize_extra_dataset_stats(stats: dict[str, Any]) -> dict[str, Any]:
    """Finalize transient generic stats into the persisted dataset_stats shape."""
    numeric_values = stats.pop("_numeric_values", {})
    stats["numeric_histograms"] = {
        field: histogram(values)
        for field, values in numeric_values.items()
        if values
    }
    return stats


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


def source_object_snapshots(s3_client: Any, bucket: str, object_keys: list[str]) -> list[dict[str, Any]]:
    """Capture immutable source metadata used to verify one import run."""
    snapshots: list[dict[str, Any]] = []
    for object_key in object_keys:
        metadata = s3_client.head_object(bucket, object_key) if hasattr(s3_client, "head_object") else None
        if metadata is None:
            raise FileNotFoundError(f"source object is missing: {object_key}")
        snapshots.append(
            {
                "object_key": object_key,
                "size_bytes": int(metadata.get("size_bytes") or 0),
                "etag": metadata.get("etag"),
                "last_modified": metadata.get("last_modified"),
            }
        )
    return snapshots


def staging_collection_name(dataset_id: str, job_id: str) -> str:
    """Return a Mongo-safe staging collection name for one dataset import."""
    safe_job_id = "".join(char if char.isalnum() else "_" for char in job_id)[-48:]
    return f"__staging_{dataset_id}_{safe_job_id}"


def atomic_replace_collection(target_db: Any, staging_name: str, target_name: str) -> None:
    """Replace a canonical collection only after staging verification succeeds."""
    if hasattr(target_db, "replace_collection"):
        target_db.replace_collection(staging_name, target_name)
        return
    target_db[staging_name].rename(target_name, dropTarget=True)


def import_verified_small_dataset(
    target_db: Any,
    *,
    s3_client: Any,
    bucket: str,
    dataset_id: str,
    object_keys: list[str],
    target_collection: str,
    collection_key: str,
    key_field: str,
    load_document_groups: Any,
    indexes: list[tuple[list[tuple[str, int]], str, bool]],
) -> dict[str, Any]:
    """Load a bounded dataset through a fingerprinted, auditable staging collection."""
    job_id = f"{dataset_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    staging_name = staging_collection_name(dataset_id, job_id)
    summary = {
        "dataset_id": dataset_id,
        "source_object_keys": list(object_keys),
        "target_collection": target_collection,
        "staging_collection": staging_name,
        "job_id": job_id,
        "records_upserted": 0,
        "checkpoint_count": 0,
        "status": "planned",
        "error": None,
    }
    started_at = datetime.now(timezone.utc)
    try:
        source_objects = source_object_snapshots(s3_client, bucket, object_keys)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "dataset_id": dataset_id,
                    "source_objects": source_objects,
                    "target_collection": target_collection,
                    "staging_collection": staging_name,
                    "status": "running",
                    "started_at": started_at,
                    "updated_at": started_at,
                }
            },
            upsert=True,
        )
        staging = target_db[staging_name]
        staging.drop()
        document_groups = list(load_document_groups())
        file_counts: list[dict[str, Any]] = []
        row_start = 1
        for chunk_index, (object_key, documents) in enumerate(document_groups, start=1):
            if object_key not in object_keys:
                raise RuntimeError(f"unexpected source object: {object_key}")
            imported = upsert_documents_bulk(staging, key_field, documents)
            summary["records_upserted"] += imported
            summary["checkpoint_count"] += 1
            file_counts.append({"object_key": object_key, "record_count": len(documents)})
            target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].update_one(
                {"job_id": job_id, "chunk_index": chunk_index},
                {
                    "$set": {
                        "job_id": job_id,
                        "dataset_id": dataset_id,
                        "source_file": Path(object_key).name,
                        "chunk_index": chunk_index,
                        "row_start": row_start,
                        "row_end": row_start + len(documents) - 1,
                        "records": len(documents),
                        "status": "completed",
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
            row_start += len(documents)
        if {item["object_key"] for item in file_counts} != set(object_keys):
            raise RuntimeError("not all source objects were parsed")
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {"$set": {"status": "verifying", "expected_count": summary["records_upserted"]}},
            upsert=True,
        )
        if source_objects != source_object_snapshots(s3_client, bucket, object_keys):
            raise RuntimeError("source objects changed during import")
        staging_count = int(staging.count_documents({}))
        if staging_count != summary["records_upserted"]:
            raise RuntimeError(
                f"staging count mismatch: parsed={summary['records_upserted']} stored={staging_count}"
            )
        for keys, name, unique in indexes:
            staging.create_index(keys, name=name, unique=unique)
        atomic_replace_collection(target_db, staging_name, target_collection)
        verified_count = int(target_db[target_collection].count_documents({}))
        if verified_count != summary["records_upserted"]:
            raise RuntimeError(
                f"canonical count mismatch: parsed={summary['records_upserted']} stored={verified_count}"
            )
        record_mode = "full" if verified_count else "metadata_only"
        update_dataset_record_count(
            target_db,
            dataset_id,
            count=verified_count,
            source_count=summary["records_upserted"],
            record_mode=record_mode,
            verification_status="verified" if verified_count else "metadata_only",
            source_objects=source_objects,
            collection_key=collection_key,
        )
        finished_at = datetime.now(timezone.utc)
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": dataset_id},
            {
                "$set": {
                    "dataset_id": dataset_id,
                    "record_count": verified_count,
                    "source_file_counts": file_counts,
                    "source_objects": source_objects,
                    "sampling": {"strategy": "none", "analysis_sample_count": 0},
                    "updated_at": finished_at,
                }
            },
            upsert=True,
        )
        elapsed = max((finished_at - started_at).total_seconds(), 0.001)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "processed_count": summary["records_upserted"],
                    "expected_count": summary["records_upserted"],
                    "verified_count": verified_count,
                    "checkpoint_count": summary["checkpoint_count"],
                    "source_file_counts": file_counts,
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    "duration_seconds": round(elapsed, 3),
                    "throughput_rows_per_second": round(verified_count / elapsed, 2),
                }
            },
            upsert=True,
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
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
        target_db["datasets"].update_one(
            {"dataset_id": dataset_id},
            {"$set": {"verification_status": "failed", "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
    return summary


def update_dataset_record_count(
    target_db: Any,
    dataset_id: str,
    *,
    count: int,
    record_mode: str,
    collection_key: str,
    source_count: int | None = None,
    verification_status: str | None = None,
    source_objects: list[dict[str, Any]] | None = None,
) -> None:
    """Persist dataset import status."""
    payload: dict[str, Any] = {
        "record_collection_key": collection_key,
        "record_count": count,
        "record_mode": record_mode if count else "metadata_only",
        "verification_status": verification_status
        or ("verified" if record_mode == "full" and count else "partial" if count else "metadata_only"),
        "updated_at": datetime.now(timezone.utc),
    }
    if source_count is not None:
        payload["source_record_count"] = source_count
        if record_mode == "full":
            payload["row_count"] = source_count
    if source_objects is not None:
        payload["source_objects"] = source_objects
    if payload["verification_status"] == "verified":
        payload["verified_at"] = datetime.now(timezone.utc)
    target_db["datasets"].update_one(
        {"dataset_id": dataset_id},
        {"$set": payload},
        upsert=True,
    )


def upsert_catalog_metadata(target_db: Any, *, object_records: list[dict[str, Any]], apply: bool) -> int:
    """Upsert dataset, field, and object metadata documents."""
    if not apply:
        return 0
    metadata_upserted = 0
    create_indexes(target_db)
    for doc in dataset_documents():
        existing = target_db["datasets"].find_one({"dataset_id": doc["dataset_id"]}, {"_id": 0})
        if existing:
            doc = {
                key: value
                for key, value in doc.items()
                if key not in {"row_count", "record_count", "record_mode", "verification_status", "source_objects", "verified_at"}
            }
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
    def load_document_groups() -> list[tuple[str, list[dict[str, Any]]]]:
        import pandas as pd

        content = s3_client.get_object(bucket, RADONPY_OBJECT_KEY)
        dataframe = pd.read_excel(BytesIO(content), engine="openpyxl")
        return [(RADONPY_OBJECT_KEY, build_radonpy_documents(dataframe))]

    return import_verified_small_dataset(
        target_db,
        s3_client=s3_client,
        bucket=bucket,
        dataset_id="radonpy_pi1070",
        object_keys=[RADONPY_OBJECT_KEY],
        target_collection=TARGET_RADONPY_COLLECTION,
        collection_key="poly_data.radonpy_records",
        key_field="radonpy_record_id",
        load_document_groups=load_document_groups,
        indexes=[
            ([("radonpy_record_id", 1)], "radonpy_record_id", True),
            ([("smiles", 1)], "smiles", False),
        ],
    )


def import_pi1m_samples(
    target_db: Any,
    *,
    s3_client: Any,
    bucket: str,
    sample_size: int | None,
    chunk_size: int = DEFAULT_PI1M_CHUNK_SIZE,
    apply: bool,
    resume_job_id: str | None = None,
) -> dict[str, Any]:
    """Import PI1M v2 rows from MinIO into MongoDB with chunked bulk upserts."""
    job_id = resume_job_id or f"pi1m_v2-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    staging_name = staging_collection_name("pi1m_v2", job_id)
    summary = {
        "dataset_id": "pi1m_v2",
        "source_object_key": PI1M_OBJECT_KEY,
        "target_collection": TARGET_PI1M_COLLECTION,
        "staging_collection": staging_name,
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
    source_stream: Any | None = None
    try:
        import pandas as pd

        source_objects = source_object_snapshots(s3_client, bucket, [PI1M_OBJECT_KEY])
        existing_job = target_db[TARGET_IMPORT_JOBS_COLLECTION].find_one({"job_id": job_id}, {"_id": 0})
        if resume_job_id:
            if not existing_job or existing_job.get("dataset_id") != "pi1m_v2":
                raise RuntimeError("resume job does not match PI1M v2")
            if existing_job.get("source_objects") != source_objects:
                raise RuntimeError("source objects changed since the failed import")
        completed_checkpoints = {
            int(item.get("chunk_index") or 0): item
            for item in target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].find(
                {"job_id": job_id, "status": "completed"},
                {"_id": 0},
            )
        } if resume_job_id else {}
        started_at = datetime.now(timezone.utc)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "dataset_id": "pi1m_v2",
                    "source_object_key": PI1M_OBJECT_KEY,
                    "source": source_objects[0],
                    "source_objects": source_objects,
                    "target_collection": TARGET_PI1M_COLLECTION,
                    "staging_collection": staging_name,
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
        collection = target_db[staging_name]
        if not resume_job_id:
            collection.drop()
        source_stream = source_object_stream_or_bytes(s3_client, bucket, PI1M_OBJECT_KEY)
        read_csv_kwargs: dict[str, Any] = {"chunksize": max(int(chunk_size), 1)}
        if sample_size is not None:
            read_csv_kwargs["nrows"] = max(int(sample_size), 0)
        reader = pd.read_csv(source_stream, **read_csv_kwargs)
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
            checkpoint = completed_checkpoints.get(chunk_index)
            if (
                checkpoint
                and int(checkpoint.get("row_start") or 0) == row_index
                and int(checkpoint.get("row_end") or 0) == row_index + records_in_chunk - 1
                and int(checkpoint.get("records") or 0) == records_in_chunk
            ):
                summary["records_upserted"] += records_in_chunk
            else:
                summary["records_upserted"] += upsert_documents_bulk(
                    collection, "pi1m_record_id", documents
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
            target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "processed_count": summary["records_upserted"],
                        "checkpoint_count": summary["checkpoint_count"],
                        "updated_at": datetime.now(timezone.utc),
                    }
                },
                upsert=True,
            )
        elapsed = max(monotonic() - start_time, 0.001)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {"$set": {"status": "verifying", "expected_count": summary["records_upserted"]}},
            upsert=True,
        )
        if source_objects != source_object_snapshots(s3_client, bucket, [PI1M_OBJECT_KEY]):
            raise RuntimeError("source objects changed during import")
        staging_count = int(collection.count_documents({}))
        if staging_count != summary["records_upserted"]:
            raise RuntimeError(
                f"staging count mismatch: parsed={summary['records_upserted']} stored={staging_count}"
            )
        collection.create_index([("pi1m_record_id", 1)], name="pi1m_record_id", unique=True)
        collection.create_index([("smiles", 1)], name="smiles")
        collection.create_index([("smiles_hash", 1)], name="smiles_hash")
        collection.create_index([("row_index", 1)], name="row_index")
        collection.create_index([("sa_score", 1), ("row_index", 1)], name="sa_score_row")
        collection.create_index([("dataset.dataset_id", 1), ("row_index", 1)], name="dataset_row")
        atomic_replace_collection(target_db, staging_name, TARGET_PI1M_COLLECTION)
        verified_count = int(target_db[TARGET_PI1M_COLLECTION].count_documents({}))
        if verified_count != summary["records_upserted"]:
            raise RuntimeError(
                f"canonical count mismatch: parsed={summary['records_upserted']} stored={verified_count}"
            )
        record_mode = "full" if sample_size is None else "sample"
        update_dataset_record_count(
            target_db,
            "pi1m_v2",
            count=verified_count,
            source_count=summary["records_upserted"] if sample_size is None else None,
            record_mode=record_mode,
            verification_status="verified" if record_mode == "full" else "partial",
            source_objects=source_objects,
            collection_key="poly_data.pi1m_samples",
        )
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "pi1m_v2"},
            {
                "$set": {
                    "dataset_id": "pi1m_v2",
                    "record_count": verified_count,
                    "sa_score_histogram": histogram(scores),
                    "unique_smiles_count": len(smiles_seen),
                    "duplicate_smiles_count": duplicate_smiles_count,
                    "visual_samples": visual_samples,
                    "source_objects": source_objects,
                    "sampling": {
                        "strategy": "bounded_row_stride",
                        "analysis_sample_count": len(visual_samples),
                    },
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
                    "status": "completed",
                    "imported_count": verified_count,
                    "processed_count": summary["records_upserted"],
                    "expected_count": summary["records_upserted"],
                    "verified_count": verified_count,
                    "failed_count": summary["failed_count"],
                    "checkpoint_count": summary["checkpoint_count"],
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    "duration_seconds": round(elapsed, 3),
                    "throughput_rows_per_second": round(verified_count / elapsed, 2),
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
            target_db["datasets"].update_one(
                {"dataset_id": "pi1m_v2"},
                {"$set": {"verification_status": "failed", "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        except Exception:
            pass
    finally:
        close_source = getattr(source_stream, "close", None)
        if callable(close_source):
            close_source()
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
    def load_document_groups() -> list[tuple[str, list[dict[str, Any]]]]:
        import pandas as pd

        content = s3_client.get_object(bucket, SMIPOLY_OBJECT_KEY)
        dataframe = pd.read_csv(BytesIO(content))
        return [(SMIPOLY_OBJECT_KEY, build_smipoly_documents(dataframe))]

    return import_verified_small_dataset(
        target_db,
        s3_client=s3_client,
        bucket=bucket,
        dataset_id="smipoly",
        object_keys=[SMIPOLY_OBJECT_KEY],
        target_collection=TARGET_SMIPOLY_COLLECTION,
        collection_key="poly_data.smipoly_monomers",
        key_field="smipoly_record_id",
        load_document_groups=load_document_groups,
        indexes=[
            ([("smipoly_record_id", 1)], "smipoly_record_id", True),
            ([("com_id", 1)], "com_id", False),
            ([("smiles", 1)], "smiles", False),
        ],
    )


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
    def load_document_groups() -> list[tuple[str, list[dict[str, Any]]]]:
        import pandas as pd

        groups: list[tuple[str, list[dict[str, Any]]]] = []
        for source_file, object_key in POLYUNIVERSE_OBJECT_KEYS.items():
            content = s3_client.get_object(bucket, object_key)
            dataframe = pd.read_csv(BytesIO(content))
            groups.append((object_key, build_polyuniverse_documents(dataframe, source_file=source_file)))
        return groups

    return import_verified_small_dataset(
        target_db,
        s3_client=s3_client,
        bucket=bucket,
        dataset_id="polyuniverse",
        object_keys=list(POLYUNIVERSE_OBJECT_KEYS.values()),
        target_collection=TARGET_POLYUNIVERSE_COLLECTION,
        collection_key="poly_data.polyuniverse_monomers",
        key_field="polyuniverse_record_id",
        load_document_groups=load_document_groups,
        indexes=[
            ([("polyuniverse_record_id", 1)], "polyuniverse_record_id", True),
            ([("source_file", 1), ("row_index", 1)], "source_row", False),
            ([("monomer_class", 1)], "monomer_class", False),
            ([("smiles", 1)], "smiles", False),
        ],
    )


def import_extra_open_database_records(
    target_db: Any,
    *,
    s3_client: Any,
    bucket: str,
    dataset_ids: list[str],
    sample_size: int | None,
    apply: bool,
    resume_job_id: str | None = None,
) -> list[dict[str, Any]]:
    """Import selected processed 05–16 dataset rows into generic Mongo collections."""
    requested = {item.strip() for item in dataset_ids if item.strip()}
    selected_specs = [spec for spec in EXTRA_DATASET_SPECS if not requested or spec.dataset_id in requested]
    if resume_job_id and len(selected_specs) != 1:
        raise ValueError("resume_job_id requires exactly one extra dataset id")
    summaries: list[dict[str, Any]] = []
    for dataset_spec in selected_specs:
        job_id = resume_job_id or f"{dataset_spec.dataset_id}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        staging_name = staging_collection_name(dataset_spec.dataset_id, job_id)
        summary = {
            "dataset_id": dataset_spec.dataset_id,
            "source_object_keys": [file_spec.object_key for file_spec in dataset_spec.files if file_spec.importable],
            "target_collection": dataset_spec.collection_name,
            "staging_collection": staging_name,
            "sample_size": sample_size,
            "job_id": job_id,
            "records_upserted": 0,
            "failed_count": 0,
            "checkpoint_count": 0,
            "status": "planned",
            "error": None,
        }
        if not apply:
            summaries.append(summary)
            continue
        if s3_client is None:
            summary["status"] = "skipped"
            summary["error"] = "MinIO client is not configured"
            summaries.append(summary)
            continue
        try:
            source_objects = source_object_snapshots(
                s3_client,
                bucket,
                list(summary["source_object_keys"]),
            )
            existing_job = target_db[TARGET_IMPORT_JOBS_COLLECTION].find_one(
                {"job_id": job_id},
                {"_id": 0},
            )
            if resume_job_id:
                if not existing_job or existing_job.get("dataset_id") != dataset_spec.dataset_id:
                    raise RuntimeError(f"resume job does not match dataset {dataset_spec.dataset_id}")
                if existing_job.get("source_objects") != source_objects:
                    raise RuntimeError("source objects changed since the failed import")
            completed_checkpoints = {
                int(item.get("chunk_index") or 0): item
                for item in target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].find(
                    {"job_id": job_id, "status": "completed"},
                    {"_id": 0},
                )
            } if resume_job_id else {}
            started_at = datetime.now(timezone.utc)
            target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "job_id": job_id,
                        "dataset_id": dataset_spec.dataset_id,
                        "target_collection": dataset_spec.collection_name,
                        "staging_collection": staging_name,
                        "source_objects": source_objects,
                        "sample_size": sample_size,
                        "status": "running",
                        "processed_count": 0,
                        "checkpoint_count": 0,
                        "started_at": started_at,
                        "updated_at": started_at,
                    }
                },
                upsert=True,
            )
            collection = target_db[staging_name]
            if not resume_job_id:
                collection.drop()
            row_index = 1
            global_chunk_index = 0
            file_counts: list[dict[str, Any]] = []
            stats: dict[str, Any] = {
                "dataset_id": dataset_spec.dataset_id,
                "record_count": 0,
                "category_counts": {},
                "analysis_samples": [],
                "asset_coverage": {
                    "importable_file_count": sum(1 for file_spec in dataset_spec.files if file_spec.importable),
                },
            }
            for file_spec in dataset_spec.files:
                if not file_spec.importable:
                    continue
                source_row_index = 1
                remaining = None if sample_size is None else sample_size - summary["records_upserted"]
                if remaining is not None and remaining <= 0:
                    break
                for dataframe in iter_extra_dataset_frames(
                    s3_client=s3_client,
                    bucket=bucket,
                    file_spec=file_spec,
                    remaining=remaining,
                ):
                    documents = build_extra_dataset_documents(
                        dataframe,
                        dataset_spec=dataset_spec,
                        file_spec=file_spec,
                        start_index=row_index,
                        source_start_index=source_row_index,
                    )
                    if not documents:
                        continue
                    global_chunk_index += 1
                    checkpoint = completed_checkpoints.get(global_chunk_index)
                    expected_row_start = row_index
                    expected_row_end = row_index + len(documents) - 1
                    if (
                        checkpoint
                        and checkpoint.get("source_file") == Path(file_spec.remote_relative_path).name
                        and int(checkpoint.get("row_start") or 0) == expected_row_start
                        and int(checkpoint.get("row_end") or 0) == expected_row_end
                        and int(checkpoint.get("records") or 0) == len(documents)
                    ):
                        imported = len(documents)
                    else:
                        imported = upsert_documents_bulk(collection, "record_id", documents)
                    summary["records_upserted"] += imported
                    summary["checkpoint_count"] += 1
                    row_index += len(documents)
                    source_row_index += len(documents)
                    stats["record_count"] = summary["records_upserted"]
                    update_extra_dataset_stats(stats, documents=documents, file_spec=file_spec)
                    target_db[TARGET_IMPORT_CHECKPOINTS_COLLECTION].update_one(
                        {"job_id": job_id, "chunk_index": global_chunk_index},
                        {
                            "$set": {
                                "job_id": job_id,
                                "dataset_id": dataset_spec.dataset_id,
                                "source_file": Path(file_spec.remote_relative_path).name,
                                "chunk_index": global_chunk_index,
                                "row_start": row_index - len(documents),
                                "row_end": row_index - 1,
                                "records": len(documents),
                                "status": "completed",
                                "updated_at": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True,
                    )
                    target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                        {"job_id": job_id},
                        {
                            "$set": {
                                "processed_count": summary["records_upserted"],
                                "checkpoint_count": summary["checkpoint_count"],
                                "updated_at": datetime.now(timezone.utc),
                            }
                        },
                        upsert=True,
                    )
                    if sample_size is not None and summary["records_upserted"] >= sample_size:
                        break
                file_counts.append(
                    {
                        "object_key": file_spec.object_key,
                        "record_count": source_row_index - 1,
                    }
                )
                if sample_size is not None and summary["records_upserted"] >= sample_size:
                    break

            target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                {"job_id": job_id},
                {"$set": {"status": "verifying", "expected_count": summary["records_upserted"]}},
                upsert=True,
            )
            if source_objects != source_object_snapshots(s3_client, bucket, list(summary["source_object_keys"])):
                raise RuntimeError("source objects changed during import")
            staging_count = int(collection.count_documents({}))
            if staging_count != summary["records_upserted"]:
                raise RuntimeError(
                    f"staging count mismatch: parsed={summary['records_upserted']} stored={staging_count}"
                )
            collection.create_index([("record_id", 1)], name="record_id", unique=True)
            collection.create_index([("dataset.dataset_id", 1), ("row_index", 1)], name="dataset_row")
            collection.create_index([("source_file", 1), ("source_row_index", 1)], name="source_row")
            collection.create_index([("title", 1)], name="title")
            atomic_replace_collection(target_db, staging_name, dataset_spec.collection_name)
            verified_count = int(target_db[dataset_spec.collection_name].count_documents({}))
            if verified_count != summary["records_upserted"]:
                raise RuntimeError(
                    f"canonical count mismatch: parsed={summary['records_upserted']} stored={verified_count}"
                )
            record_mode = "full" if sample_size is None else "sample"
            update_dataset_record_count(
                target_db,
                dataset_spec.dataset_id,
                count=verified_count,
                source_count=summary["records_upserted"] if sample_size is None else None,
                record_mode=record_mode,
                verification_status="verified" if record_mode == "full" else "partial",
                source_objects=source_objects,
                collection_key=f"poly_data.{dataset_spec.collection_name}",
            )
            stats["source_file_counts"] = file_counts
            stats["source_objects"] = source_objects
            stats["sampling"] = {
                "strategy": "bounded_first_rows",
                "analysis_sample_count": len(stats.get("analysis_samples", [])),
                "numeric_value_limit": 50_000,
            }
            target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
                {"dataset_id": dataset_spec.dataset_id},
                {"$set": {**finalize_extra_dataset_stats(stats), "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
            finished_at = datetime.now(timezone.utc)
            elapsed = max((finished_at - started_at).total_seconds(), 0.001)
            target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": "completed",
                        "imported_count": verified_count,
                        "verified_count": verified_count,
                        "expected_count": summary["records_upserted"],
                        "source_file_counts": file_counts,
                        "finished_at": finished_at,
                        "updated_at": finished_at,
                        "duration_seconds": round(elapsed, 3),
                        "throughput_rows_per_second": round(verified_count / elapsed, 2),
                    }
                },
                upsert=True,
            )
            summary["status"] = "imported"
        except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
            summary["status"] = "failed"
            summary["error"] = f"{exc.__class__.__name__}: {exc}"
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
            target_db["datasets"].update_one(
                {"dataset_id": dataset_spec.dataset_id},
                {"$set": {"verification_status": "failed", "updated_at": datetime.now(timezone.utc)}},
                upsert=True,
            )
        summaries.append(summary)
    return summaries


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
    job_id = f"md_allatom-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    staging_names = {
        target_name: staging_collection_name(f"md_allatom_{target_name}", job_id)
        for target_name in [
            TARGET_MD_ALLATOM_DIAMINES_COLLECTION,
            TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION,
            TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION,
        ]
    }
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
        "job_id": job_id,
        "staging_collections": staging_names,
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

        summary["uploaded_objects"] = upload_md_allatom_structured_assets(
            s3_client=s3_client,
            bucket=bucket,
            structured_data_root=structured_data_root,
            requirements_doc=requirements_doc,
        )
        source_keys = list(MD_ALLATOM_STRUCTURED_OBJECT_KEYS.values())
        source_objects = source_object_snapshots(s3_client, bucket, source_keys)
        started_at = datetime.now(timezone.utc)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_id": job_id,
                    "dataset_id": "md_allatom",
                    "status": "running",
                    "source_objects": source_objects,
                    "staging_collections": staging_names,
                    "started_at": started_at,
                    "updated_at": started_at,
                }
            },
            upsert=True,
        )
        diamines = build_md_allatom_diamine_documents(pd.read_csv(structured_data_root / "二胺.csv", encoding="utf-8-sig"))
        dianhydrides = build_md_allatom_dianhydride_documents(
            pd.read_csv(structured_data_root / "二酐.csv", encoding="utf-8-sig")
        )
        carbon_results = build_md_allatom_carbon_documents(pd.read_csv(structured_data_root / "碳基.csv", encoding="utf-8-sig"))
        for staging_name in staging_names.values():
            target_db[staging_name].drop()
        summary["diamine_records_upserted"] = upsert_documents(
            target_db[staging_names[TARGET_MD_ALLATOM_DIAMINES_COLLECTION]], "md_allatom_diamine_id", diamines
        )
        summary["dianhydride_records_upserted"] = upsert_documents(
            target_db[staging_names[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION]], "md_allatom_dianhydride_id", dianhydrides
        )
        summary["carbon_records_upserted"] = upsert_documents_bulk(
            target_db[staging_names[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION]],
            "md_allatom_carbon_result_id",
            carbon_results,
        )
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "verifying",
                    "processed_count": summary["carbon_records_upserted"],
                    "expected_count": summary["carbon_records_upserted"],
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        if source_objects != source_object_snapshots(s3_client, bucket, source_keys):
            raise RuntimeError("source objects changed during import")
        expected_counts = {
            TARGET_MD_ALLATOM_DIAMINES_COLLECTION: len(diamines),
            TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION: len(dianhydrides),
            TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION: len(carbon_results),
        }
        for target_name, expected_count in expected_counts.items():
            stored_count = int(target_db[staging_names[target_name]].count_documents({}))
            if stored_count != expected_count:
                raise RuntimeError(
                    f"staging count mismatch for {target_name}: parsed={expected_count} stored={stored_count}"
                )
        diamine_collection = target_db[staging_names[TARGET_MD_ALLATOM_DIAMINES_COLLECTION]]
        diamine_collection.create_index([("md_allatom_diamine_id", 1)], name="md_allatom_diamine_id", unique=True)
        diamine_collection.create_index([("diamine_id", 1)], name="diamine_id", unique=True)
        diamine_collection.create_index([("smiles", 1)], name="smiles")
        dianhydride_collection = target_db[staging_names[TARGET_MD_ALLATOM_DIANHYDRIDES_COLLECTION]]
        dianhydride_collection.create_index(
            [("md_allatom_dianhydride_id", 1)], name="md_allatom_dianhydride_id", unique=True
        )
        dianhydride_collection.create_index([("dianhydride_id", 1)], name="dianhydride_id", unique=True)
        dianhydride_collection.create_index([("smiles", 1)], name="smiles")
        carbon_collection = target_db[staging_names[TARGET_MD_ALLATOM_CARBON_RESULTS_COLLECTION]]
        carbon_collection.create_index(
            [("md_allatom_carbon_result_id", 1)], name="md_allatom_carbon_result_id", unique=True
        )
        carbon_collection.create_index(
            [("diamine_id", 1), ("dianhydride_id", 1), ("dp", 1), ("temperature", 1)],
            name="carbon_natural_fields",
        )
        carbon_collection.create_index([("temperature", 1)], name="temperature")
        carbon_collection.create_index([("dp", 1)], name="dp")
        for target_name, staging_name in staging_names.items():
            atomic_replace_collection(target_db, staging_name, target_name)
        file_docs = load_md_allatom_file_documents(target_db)
        stats = md_allatom_stats(carbon_results, file_documents=file_docs)
        target_db[TARGET_DATASET_STATS_COLLECTION].update_one(
            {"dataset_id": "md_allatom"},
            {
                "$set": {
                    "dataset_id": "md_allatom",
                    "record_count": summary["carbon_records_upserted"],
                    "source_objects": source_objects,
                    "sampling": {
                        "strategy": "bounded_row_stride",
                        "analysis_sample_count": len(stats.get("analysis_samples", [])),
                    },
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
            source_count=summary["carbon_records_upserted"],
            record_mode="full",
            verification_status="verified",
            source_objects=source_objects,
            collection_key="poly_data.md_allatom_carbon_results",
        )
        finished_at = datetime.now(timezone.utc)
        elapsed = max((finished_at - started_at).total_seconds(), 0.001)
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "status": "completed",
                    "imported_count": summary["carbon_records_upserted"],
                    "verified_count": summary["carbon_records_upserted"],
                    "finished_at": finished_at,
                    "updated_at": finished_at,
                    "duration_seconds": round(elapsed, 3),
                }
            },
            upsert=True,
        )
        summary["status"] = "imported"
    except Exception as exc:  # noqa: BLE001 - import manifest must preserve failure detail.
        summary["status"] = "failed"
        summary["error"] = f"{exc.__class__.__name__}: {exc}"
        target_db[TARGET_IMPORT_JOBS_COLLECTION].update_one(
            {"job_id": job_id},
            {"$set": {"status": "failed", "error": summary["error"], "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
        target_db["datasets"].update_one(
            {"dataset_id": "md_allatom"},
            {"$set": {"verification_status": "failed", "updated_at": datetime.now(timezone.utc)}},
            upsert=True,
        )
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
        if record["status"] in {
            "failed",
            "verify_failed",
            "copy_failed",
            "missing_source",
            "empty_source",
            "inaccessible_source",
            "skipped",
            "cancelled",
        }
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


def json_safe(value: Any) -> Any:
    """Return a JSON-compatible copy for Mongo persistence."""
    return json.loads(json.dumps(value, default=str))


def manifest_status_counts(records: list[dict[str, Any]]) -> dict[str, int]:
    """Count object statuses without storing every object in the parent manifest."""
    counts: dict[str, int] = {}
    for record in records:
        status = str(record.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def chunk_manifest_records(
    *,
    manifest_id: str,
    section: str,
    records: list[dict[str, Any]],
    generated_at: Any,
    max_chunk_bytes: int | None = None,
) -> list[dict[str, Any]]:
    """Build Mongo-safe chunk documents for large manifest record lists."""
    max_bytes = max(int(max_chunk_bytes or MONGO_MANIFEST_RECORD_CHUNK_BYTES), 1)
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_bytes = 2
    start_index = 0

    for index, record in enumerate(records):
        safe_record = json_safe(record)
        record_bytes = len(json.dumps(safe_record, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1
        if current and current_bytes + record_bytes > max_bytes:
            chunks.append(
                {
                    "manifest_id": manifest_id,
                    "section": section,
                    "chunk_index": len(chunks),
                    "record_start": start_index,
                    "record_end": index - 1,
                    "record_count": len(current),
                    "generated_at": generated_at,
                    "records": current,
                }
            )
            current = []
            current_bytes = 2
            start_index = index
        current.append(safe_record)
        current_bytes += record_bytes

    if current:
        chunks.append(
            {
                "manifest_id": manifest_id,
                "section": section,
                "chunk_index": len(chunks),
                "record_start": start_index,
                "record_end": start_index + len(current) - 1,
                "record_count": len(current),
                "generated_at": generated_at,
                "records": current,
            }
        )
    return chunks


def mongo_manifest_document(
    *,
    manifest_id: str,
    manifest: dict[str, Any],
    record_chunks: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a compact parent manifest document that stays below MongoDB's BSON limit."""
    document = json_safe(manifest)
    document["manifest_id"] = manifest_id
    document["full_manifest"] = {
        "bucket": manifest.get("bucket"),
        "object_key": manifest.get("manifest_key", MANIFEST_KEY),
        "local_path": str(LOCAL_MANIFEST_PATH),
    }
    chunks_by_section: dict[str, list[dict[str, Any]]] = {}
    for chunk in record_chunks:
        chunks_by_section.setdefault(str(chunk["section"]), []).append(chunk)

    for section in ("minio", "sftp"):
        section_payload = document.get(section)
        if not isinstance(section_payload, dict):
            continue
        records = section_payload.pop("records", [])
        if not isinstance(records, list):
            records = []
        section_chunks = chunks_by_section.get(section, [])
        section_payload.update(
            {
                "record_count": len(records),
                "status_counts": manifest_status_counts(records),
                "records_collection": TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION,
                "record_chunk_count": len(section_chunks),
            }
        )
    return document


def persist_manifest(*, target_db: Any, client: Any, bucket: str, manifest: dict[str, Any]) -> None:
    """Persist migration manifest to MongoDB and MinIO."""
    manifest_id = str(
        manifest.get("manifest_id")
        or f"poly-data-migration-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
    )
    generated_at = manifest.get("generated_at") or datetime.now(timezone.utc).isoformat()
    record_chunks = [
        chunk
        for section in ("minio", "sftp")
        if isinstance(manifest.get(section), dict)
        for chunk in chunk_manifest_records(
            manifest_id=manifest_id,
            section=section,
            records=list((manifest[section].get("records") or [])),
            generated_at=generated_at,
        )
    ]
    for chunk in record_chunks:
        target_db[TARGET_MIGRATION_MANIFEST_RECORDS_COLLECTION].insert_one(chunk)
    target_db[TARGET_MIGRATION_MANIFESTS_COLLECTION].insert_one(
        mongo_manifest_document(manifest_id=manifest_id, manifest=manifest, record_chunks=record_chunks)
    )
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
    parser.add_argument(
        "--sftp-open-database-dataset-ids",
        default=os.getenv("SFTP_OPEN_DATABASE_DATASET_IDS", ""),
        help="comma-separated dataset ids for --migrate-sftp-open-databases; empty uploads all configured open database files",
    )
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
    parser.add_argument(
        "--import-extra-open-database-records",
        action="store_true",
        help="import processed 05–16 open database rows into generic poly_data collections",
    )
    parser.add_argument(
        "--extra-dataset-ids",
        default=os.getenv("EXTRA_DATASET_IDS", ""),
        help="comma-separated extra dataset ids to import; empty imports all 05–16 configured datasets",
    )
    parser.add_argument(
        "--extra-full-import",
        action="store_true",
        help="stream all configured extra dataset rows instead of limiting to --extra-sample-size",
    )
    parser.add_argument("--extra-sample-size", type=int, default=DEFAULT_EXTRA_SAMPLE_SIZE)
    parser.add_argument("--structured-data-root", type=Path, default=PROJECT_ROOT / "refer" / "data")
    parser.add_argument(
        "--requirements-doc",
        type=Path,
        default=PROJECT_ROOT / "refer" / "requirement" / "PolyAgent_模型数据集成需求收集_填写模板.docx",
    )
    parser.add_argument("--pi1m-sample-size", type=int, default=DEFAULT_PI1M_SAMPLE_SIZE)
    parser.add_argument("--pi1m-chunk-size", type=int, default=DEFAULT_PI1M_CHUNK_SIZE)
    parser.add_argument("--pi1m-resume-job-id", default="", help="resume one interrupted PI1M staging import")
    parser.add_argument("--extra-resume-job-id", default="", help="resume one interrupted extra-dataset staging import")
    parser.add_argument(
        "--upload-workers",
        type=int,
        default=int(os.getenv("POLY_DATA_UPLOAD_WORKERS", str(DEFAULT_UPLOAD_WORKERS))),
        help="parallel SFTP-to-MinIO upload workers (1-64)",
    )
    parser.add_argument(
        "--upload-retries",
        type=int,
        default=int(os.getenv("POLY_DATA_UPLOAD_RETRIES", str(DEFAULT_UPLOAD_RETRIES))),
        help="retries after the first failed upload attempt (0-10)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = parse_args(argv or sys.argv[1:])
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    sftp_password = os.getenv(args.sftp_password_env, "")
    try:
        validate_runtime_configuration(args, sftp_password=sftp_password)
    except MigrationConfigurationError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    CANCEL_EVENT.clear()

    def request_shutdown(signum: int, _frame: Any) -> None:
        if not CANCEL_EVENT.is_set():
            print(f"received signal {signum}; stopping after active uploads are aborted", file=sys.stderr)
        CANCEL_EVENT.set()

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, request_shutdown)
        signal.signal(signal.SIGINT, request_shutdown)
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
    if not args.skip_legacy_poly_agent and not CANCEL_EVENT.is_set():
        minio_records = migrate_minio_objects(
            s3_client,
            bucket=args.bucket,
            apply=args.apply and s3_client is not None,
            delete_legacy=args.delete_legacy_minio,
        )

    sftp_records: list[dict[str, Any]] = []
    if args.migrate_sftp_open_databases and not CANCEL_EVENT.is_set():
        sftp_client = None

        def open_sftp_client() -> SftpClient:
            return SftpClient(
                host=args.sftp_host,
                port=args.sftp_port,
                username=args.sftp_username,
                password=sftp_password,
            )

        try:
            if sftp_password:
                sftp_client = open_sftp_client()
            sftp_records = migrate_sftp_open_database_objects(
                sftp_client,
                s3_client,
                bucket=args.bucket,
                sftp_host=args.sftp_host,
                sftp_root=args.sftp_root,
                dataset_ids=[
                    item.strip()
                    for item in str(args.sftp_open_database_dataset_ids).split(",")
                    if item.strip()
                ],
                apply=args.apply,
                target_db=target_db,
                upload_workers=args.upload_workers,
                upload_retries=args.upload_retries,
                sftp_client_factory=open_sftp_client if args.apply and args.upload_workers > 1 else None,
                cancel_event=CANCEL_EVENT,
            )
        finally:
            if sftp_client is not None:
                sftp_client.close()

    if args.migrate_sftp_md_allatom and not CANCEL_EVENT.is_set():
        sftp_client = None

        def open_md_sftp_client() -> SftpClient:
            return SftpClient(
                host=args.sftp_host,
                port=args.sftp_port,
                username=args.sftp_username,
                password=sftp_password,
            )

        try:
            if sftp_password:
                sftp_client = open_md_sftp_client()
            md_records = migrate_sftp_md_allatom_objects(
                sftp_client,
                s3_client,
                target_db=target_db,
                bucket=args.bucket,
                sftp_host=args.sftp_host,
                md_root=args.md_allatom_root,
                families=[item.strip() for item in str(args.md_allatom_families).split(",") if item.strip()],
                apply=args.apply,
                upload_workers=args.upload_workers,
                upload_retries=args.upload_retries,
                sftp_client_factory=open_md_sftp_client if args.apply and args.upload_workers > 1 else None,
                cancel_event=CANCEL_EVENT,
            )
            sftp_records.extend(md_records)
        finally:
            if sftp_client is not None:
                sftp_client.close()

    object_records = [
        *minio_records,
        *[record for record in sftp_records if "attempts" not in record],
    ]
    if CANCEL_EVENT.is_set():
        mongo_summary = {
            "source_database": args.source_database,
            "source_collection": SOURCE_COLLECTION,
            "target_database": args.target_database,
            "target_collection": TARGET_MATERIAL_COLLECTION,
            "source_count": 0,
            "target_count_before": 0,
            "target_count_after": 0,
            "records_upserted": 0,
            "metadata_upserted": 0,
            "source_dropped": False,
            "status": "cancelled",
        }
    elif args.skip_legacy_poly_agent:
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
    if not CANCEL_EVENT.is_set() and args.import_radonpy_records:
        import_summaries.append(
            import_radonpy_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if not CANCEL_EVENT.is_set() and args.import_pi1m_samples:
        import_summaries.append(
            import_pi1m_samples(
                target_db,
                s3_client=s3_client,
                bucket=args.bucket,
                sample_size=None if args.pi1m_full_import else args.pi1m_sample_size,
                chunk_size=args.pi1m_chunk_size,
                apply=args.apply,
                resume_job_id=args.pi1m_resume_job_id or None,
            )
        )
    if not CANCEL_EVENT.is_set() and args.import_smipoly_records:
        import_summaries.append(
            import_smipoly_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if not CANCEL_EVENT.is_set() and args.import_polyuniverse_records:
        import_summaries.append(
            import_polyuniverse_records(target_db, s3_client=s3_client, bucket=args.bucket, apply=args.apply)
        )
    if not CANCEL_EVENT.is_set() and args.import_md_allatom_structured:
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
    if not CANCEL_EVENT.is_set() and args.import_extra_open_database_records:
        import_summaries.extend(
            import_extra_open_database_records(
                target_db,
                s3_client=s3_client,
                bucket=args.bucket,
                dataset_ids=[item.strip() for item in str(args.extra_dataset_ids).split(",") if item.strip()],
                sample_size=None if args.extra_full_import else args.extra_sample_size,
                apply=args.apply,
                resume_job_id=args.extra_resume_job_id or None,
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
    if args.apply and not CANCEL_EVENT.is_set():
        persist_manifest(target_db=target_db, client=s3_client, bucket=args.bucket, manifest=manifest)

    mode = "APPLY" if args.apply else "DRY-RUN"
    print(f"{mode} Poly Data migration for bucket {args.bucket}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, default=str))
    if CANCEL_EVENT.is_set():
        return 130
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
