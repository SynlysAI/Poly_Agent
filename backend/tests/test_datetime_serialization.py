"""UTC datetime JSON serialization tests."""

from __future__ import annotations

import json
import sys
import unittest
from datetime import UTC
from datetime import datetime
from datetime import timezone
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.schemas.common import UtcDatetimeJsonModel


class TimestampExample(UtcDatetimeJsonModel):
    created_at: datetime
    updated_at: datetime
    checked_at: datetime


class UtcDatetimeJsonModelTest(unittest.TestCase):
    def test_serializes_datetimes_as_explicit_utc(self) -> None:
        payload = TimestampExample(
            created_at=datetime(2026, 7, 21, 6, 6, 17),
            updated_at=datetime(2026, 7, 21, 6, 6, 17, tzinfo=UTC),
            checked_at=datetime(2026, 7, 21, 14, 6, 17, tzinfo=timezone(timedelta(hours=8))),
        )

        data = json.loads(payload.model_dump_json())

        self.assertEqual(data["created_at"], "2026-07-21T06:06:17Z")
        self.assertEqual(data["updated_at"], "2026-07-21T06:06:17Z")
        self.assertEqual(data["checked_at"], "2026-07-21T06:06:17Z")


if __name__ == "__main__":
    unittest.main()
