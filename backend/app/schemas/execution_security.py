"""统一执行分级与受限操作契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ExecutionAccessMode = Literal["read_only", "writable"]
ExecutionOperation = Literal["query", "persist", "artifact_write", "external_dispatch"]


class ExecutionAccessRecord(BaseModel):
    """一次受限执行的访问模式快照。"""

    access_mode: ExecutionAccessMode = "writable"
    sandbox_profile: str | None = None
    operations: list[ExecutionOperation] = Field(default_factory=list)
    confirmed_preview_digest: str | None = Field(default=None, max_length=128)


class ExecutionAccessError(ValueError):
    """受限执行操作违反访问模式时抛出的异常。"""


def validate_execution_access(
    access_mode: ExecutionAccessMode,
    *,
    persist_count: int = 0,
    artifact_write_count: int = 0,
    external_dispatch_count: int = 0,
) -> None:
    """校验当前访问模式是否允许即将执行的受限操作。

    Args:
        access_mode: 执行访问模式，preview/query 使用 read_only，确认后的执行使用 writable。
        persist_count: 即将持久化的记录数量。
        artifact_write_count: 即即将写入的可追溯制品数量。
        external_dispatch_count: 即将触发的 external dispatch 数量。

    Raises:
        ExecutionAccessError: 访问模式未知，或 read_only 模式尝试任何写入/外部下发操作。
    """
    if access_mode not in {"read_only", "writable"}:
        raise ExecutionAccessError(f"未知执行访问模式: {access_mode}")
    if access_mode != "read_only":
        return
    denied: list[tuple[ExecutionOperation, int]] = [
        ("persist", persist_count),
        ("artifact_write", artifact_write_count),
        ("external_dispatch", external_dispatch_count),
    ]
    violations = [operation for operation, count in denied if count > 0]
    if violations:
        raise ExecutionAccessError(f"read_only 模式禁止执行写入或外部下发操作: {', '.join(violations)}")
