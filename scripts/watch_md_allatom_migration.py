#!/usr/bin/env python3
"""Continuously monitor the MD-AllAtom migration progress."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import stat
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PID_FILE = Path(".runtime/logs/md_allatom_migration.pid")
DEFAULT_LOG_FILE = Path(".runtime/logs/md_allatom_migration.log")
DEFAULT_BUCKET = "polymer-data"
DEFAULT_PREFIX = "datasets/md_allatom/raw/C/"
DEFAULT_ENDPOINT = os.getenv("MINIO_ENDPOINT", "10.26.15.93:9000")
DEFAULT_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
DEFAULT_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")


@dataclass(frozen=True)
class MinioProgress:
    count: int
    latest_key: str | None
    latest_modified: datetime | None


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, help="Process id to watch")
    parser.add_argument("--pid-file", type=Path, default=DEFAULT_PID_FILE, help="PID file to read when --pid is omitted")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_FILE, help="Migration log file to tail")
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument("--prefix", default=DEFAULT_PREFIX, help="MinIO object prefix to count")
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--access-key", default=DEFAULT_ACCESS_KEY)
    parser.add_argument("--secret-key", default=DEFAULT_SECRET_KEY)
    parser.add_argument("--secure", action="store_true", default=os.getenv("MINIO_SECURE", "false").lower() == "true")
    parser.add_argument("--interval", type=float, default=15.0, help="Seconds between refreshes")
    parser.add_argument("--tail", type=int, default=12, help="Log lines to show on first render")
    parser.add_argument("--once", action="store_true", help="Print one snapshot and exit")
    return parser.parse_args(argv)


def read_pid(pid: int | None, pid_file: Path) -> int | None:
    if pid is not None:
        return pid
    try:
        text = pid_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    return int(text) if text.isdigit() else None


def process_alive(pid: int) -> bool:
    return Path(f"/proc/{pid}").exists()


def process_summary(pid: int) -> dict[str, str]:
    summary = {"status": "missing"}
    try:
        stat_fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace").strip()
        wchan = Path(f"/proc/{pid}/wchan").read_text(encoding="utf-8").strip()
        cpu_time = int(stat_fields[13]) + int(stat_fields[14])
        hz = os.sysconf(os.sysconf_names["SC_CLK_TCK"])
        utime = int(stat_fields[13]) / hz
        stime = int(stat_fields[14]) / hz
        summary = {
            "status": "running",
            "state": stat_fields[2],
            "cmd": cmdline,
            "wchan": wchan or "-",
            "cpu_time": f"{cpu_time / hz:.1f}s",
            "utime": f"{utime:.1f}s",
            "stime": f"{stime:.1f}s",
        }
    except FileNotFoundError:
        pass
    return summary


def make_opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def sign_request(
    *,
    method: str,
    endpoint: str,
    bucket: str,
    query: dict[str, str],
    access_key: str,
    secret_key: str,
    secure: bool,
    opener: urllib.request.OpenerDirector,
) -> bytes:
    endpoint = endpoint.strip().rstrip("/")
    if not endpoint.startswith(("http://", "https://")):
        endpoint = f"{'https' if secure else 'http'}://{endpoint}"
    parsed = urllib.parse.urlparse(endpoint)
    host = parsed.netloc
    amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    date_stamp = amz_date[:8]
    payload_hash = hashlib.sha256(b"").hexdigest()
    canonical_uri = f"/{bucket}"
    canonical_query = "&".join(
        f"{urllib.parse.quote(key, safe='-_.~')}={urllib.parse.quote(value, safe='-_.~')}"
        for key, value in sorted(query.items())
    )
    signed_headers_map = {
        "host": host,
        "x-amz-content-sha256": payload_hash,
        "x-amz-date": amz_date,
    }
    canonical_headers = "".join(f"{key}:{signed_headers_map[key]}\n" for key in sorted(signed_headers_map))
    signed_headers = ";".join(sorted(signed_headers_map))
    canonical_request = "\n".join([method, canonical_uri, canonical_query, canonical_headers, signed_headers, payload_hash])
    credential_scope = f"{date_stamp}/us-east-1/s3/aws4_request"
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            credential_scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ]
    )

    def sign(key: bytes, message: str) -> bytes:
        return hmac.new(key, message.encode("utf-8"), hashlib.sha256).digest()

    date_key = sign(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    region_key = sign(date_key, "us-east-1")
    service_key = sign(region_key, "s3")
    signing_key = sign(service_key, "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    authorization = (
        "AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )
    request = urllib.request.Request(
        f"{endpoint}{canonical_uri}?{canonical_query}",
        method=method,
        headers={**signed_headers_map, "Authorization": authorization},
    )
    with opener.open(request, timeout=30) as response:
        return response.read()


def count_prefix_objects(
    *,
    endpoint: str,
    bucket: str,
    prefix: str,
    access_key: str,
    secret_key: str,
    secure: bool,
) -> MinioProgress:
    opener = make_opener()
    count = 0
    latest_key: str | None = None
    latest_modified: datetime | None = None
    continuation: str | None = None
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

    while True:
        query = {"list-type": "2", "prefix": prefix, "max-keys": "1000", "encoding-type": "url"}
        if continuation:
            query["continuation-token"] = continuation
        xml_payload = sign_request(
            method="GET",
            endpoint=endpoint,
            bucket=bucket,
            query=query,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            opener=opener,
        )
        root = ET.fromstring(xml_payload)
        for content in root.findall("s3:Contents", ns):
            count += 1
            key = content.findtext("s3:Key", default="", namespaces=ns)
            modified_text = content.findtext("s3:LastModified", default="", namespaces=ns)
            if modified_text:
                modified = datetime.fromisoformat(modified_text.replace("Z", "+00:00"))
                if latest_modified is None or modified > latest_modified:
                    latest_modified = modified
                    latest_key = key
        if root.findtext("s3:IsTruncated", default="false", namespaces=ns) != "true":
            break
        continuation = root.findtext("s3:NextContinuationToken", default="", namespaces=ns) or None

    return MinioProgress(count=count, latest_key=latest_key, latest_modified=latest_modified)


def read_new_log(path: Path, previous_size: int | None, tail: int) -> tuple[str, int]:
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return "", 0

    encoded = data.encode("utf-8", errors="replace")
    current_size = len(encoded)
    if previous_size is None or previous_size > current_size:
        lines = data.splitlines()
        return "\n".join(lines[-tail:]), current_size
    if current_size == previous_size:
        return "", current_size
    delta = encoded[previous_size:current_size].decode("utf-8", errors="replace")
    return delta.strip("\n"), current_size


def format_timestamp(value: datetime | None) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if value else "-"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    pid = read_pid(args.pid, args.pid_file)
    if pid is None:
        print("No PID found. Pass --pid or create the pid file first.", file=sys.stderr)
        return 2

    last_count: int | None = None
    last_log_size: int | None = None
    last_change = time.monotonic()

    while True:
        started = datetime.now().strftime("%H:%M:%S")
        proc = process_summary(pid)
        alive = process_alive(pid)
        if alive:
            progress = count_prefix_objects(
                endpoint=args.endpoint,
                bucket=args.bucket,
                prefix=args.prefix,
                access_key=args.access_key,
                secret_key=args.secret_key,
                secure=args.secure,
            )
            delta = 0 if last_count is None else progress.count - last_count
            if last_count is None or delta != 0:
                last_change = time.monotonic()
            stagnant_for = int(time.monotonic() - last_change)
            print(
                f"[{started}] pid={pid} state={proc.get('state', '-')}"
                f" cpu={proc.get('utime', '-')}/{proc.get('stime', '-')}"
                f" wchan={proc.get('wchan', '-')}"
                f" minio={progress.count}"
                f" delta={delta:+d}"
                f" latest={format_timestamp(progress.latest_modified)}"
                f" key={progress.latest_key or '-'}"
                f" stagnant_for={stagnant_for}s"
            )
            log_chunk, last_log_size = read_new_log(args.log_file, last_log_size, args.tail)
            if log_chunk:
                print(log_chunk.rstrip())
        else:
            print(f"[{started}] pid={pid} not running")
            return 1

        last_count = progress.count
        if args.once:
            return 0
        time.sleep(max(args.interval, 1.0))


if __name__ == "__main__":
    raise SystemExit(main())
