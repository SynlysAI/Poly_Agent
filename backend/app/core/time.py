"""Time helpers used across backend services."""

from __future__ import annotations

from datetime import UTC
from datetime import datetime


def utc_now() -> datetime:
    """Return a UTC-naive datetime for compatibility with existing persistence models."""
    return datetime.now(UTC).replace(tzinfo=None)


def utc_date_id() -> str:
    """Return the current UTC date segment used in generated business IDs."""
    return utc_now().strftime("%Y%m%d")
