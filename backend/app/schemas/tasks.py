"""全局任务中心数据契约。"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class GlobalTaskItem(BaseModel):
    """全局任务中心中的单行任务。"""

    task_id: str
    task_type: str
    module_id: str
    module_name: str
    title: str
    summary: str = "-"
    status: str
    status_text: str
    created_at: datetime | None = None
    updated_at: datetime | None = None
    route: dict = Field(default_factory=dict)
    raw: dict = Field(default_factory=dict)


class GlobalTaskCenterData(BaseModel):
    """全局任务中心分页响应。"""

    items: list[GlobalTaskItem]
    page: int
    page_size: int
    total: int
    summary: dict[str, int] = Field(default_factory=dict)
