"""LUI 评测手动运行接口契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import UtcDatetimeJsonModel


LuiEvaluationMode = Literal["smoke", "full"]


class LuiEvaluationRunRequest(BaseModel):
    """创建 LUI 评测任务的请求体。"""

    model_config = ConfigDict(extra="forbid")

    mode: LuiEvaluationMode
    provider_id: str | None = Field(default=None, max_length=120)
    model_id: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def validate_full_model(self) -> "LuiEvaluationRunRequest":
        """校验 full 模式必须固定 provider 与 model。

        Returns:
            校验通过的请求对象。
        """
        if self.mode == "full" and (not self.provider_id or not self.model_id):
            raise ValueError("full 模式必须选择 provider 和 model")
        return self


class LuiEvaluationProgress(BaseModel):
    """评测任务进度。"""

    done: int = Field(default=0, ge=0)
    total: int | None = Field(default=None, ge=0)
    current_task: str | None = None


class LuiEvaluationRun(UtcDatetimeJsonModel):
    """LUI 评测任务文档。"""

    job_id: str
    mode: LuiEvaluationMode
    evaluation_id: str
    provider_id: str | None = None
    model_id: str | None = None
    status: Literal[
        "queued",
        "capturing",
        "evaluating",
        "completed",
        "failed",
        "cancelled",
    ]
    progress: LuiEvaluationProgress = Field(default_factory=LuiEvaluationProgress)
    log_tail: list[str] = Field(default_factory=list)
    error: str | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    baseline_file: str | None = None
    report_file: str | None = None


class LuiEvaluationRunListData(BaseModel):
    """LUI 评测任务分页数据。"""

    items: list[LuiEvaluationRun] = Field(default_factory=list)
    total: int = Field(ge=0)
    page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)
