"""通用响应模型。"""

from __future__ import annotations

from datetime import UTC
from datetime import datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field, field_serializer

T = TypeVar("T")


def serialize_utc_datetime(value: datetime) -> str:
    """Serialize backend UTC datetimes with an explicit UTC designator."""
    normalized = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


class UtcDatetimeJsonModel(BaseModel):
    """Base model that emits datetime fields as explicit UTC JSON strings."""

    @field_serializer("*", when_used="json", check_fields=False)
    def serialize_datetime_fields(self, value):
        if isinstance(value, datetime):
            return serialize_utc_datetime(value)
        return value


class ApiResponse(BaseModel, Generic[T]):
    """统一响应结构。

    Args:
        code: 业务状态码，0 表示成功。
        message: 响应消息。
        data: 响应数据体，可为空。
        request_id: 请求追踪 ID，可选。
    """

    code: int = Field(default=0, description="业务状态码")
    message: str = Field(default="ok", description="响应消息")
    data: Optional[T] = Field(default=None, description="响应数据")
    request_id: Optional[str] = Field(default=None, description="请求追踪ID")
