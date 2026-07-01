"""计算智能模块数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


ComputationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
WorkflowType = Literal["MOCK_XTB_ONLY", "MOCK_LASER"]
EngineType = Literal["MOCK"]
ArtifactType = Literal["result_json", "log_text", "structure_json"]


class MoleculeInput(BaseModel):
    """计算任务分子输入。"""

    smiles: str = Field(min_length=1, max_length=512)
    name: str | None = Field(default=None, max_length=120)
    formula: str | None = Field(default=None, max_length=120)

    @field_validator("smiles")
    @classmethod
    def validate_smiles(cls, value: str) -> str:
        """执行 MVP 级输入校验，避免空白和控制字符进入任务。"""
        normalized = value.strip()
        if not normalized:
            raise ValueError("SMILES 不能为空")
        if any(ord(ch) < 32 for ch in normalized):
            raise ValueError("SMILES 不能包含控制字符")
        return normalized


class ComputationParameters(BaseModel):
    """计算参数。"""

    charge: int = Field(default=0, ge=-5, le=5)
    multiplicity: int = Field(default=1, ge=1, le=6)
    method: str = Field(default="GFN2-xTB", max_length=80)
    solvent: str | None = Field(default=None, max_length=80)


class ComputationResources(BaseModel):
    """计算资源上限。"""

    num_cores: int = Field(default=2, ge=1, le=32)
    memory_mb: int = Field(default=4096, ge=512, le=131072)
    max_wallclock_seconds: int = Field(default=1800, ge=60, le=172800)


class ComputationCreateRequest(BaseModel):
    """创建计算任务请求。"""

    workflow_type: WorkflowType = "MOCK_XTB_ONLY"
    engine: EngineType = "MOCK"
    molecule: MoleculeInput
    parameters: ComputationParameters = Field(default_factory=ComputationParameters)
    resources: ComputationResources = Field(default_factory=ComputationResources)
    source: str | None = Field(default=None, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=80)
    suggestion_id: str | None = Field(default=None, max_length=80)


class ComputationStep(BaseModel):
    """计算 workflow 步骤。"""

    step_key: str
    label: str
    status: ComputationStatus
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = None


class ComputationRun(BaseModel):
    """计算任务运行态记录。"""

    run_id: str
    retry_of_run_id: str | None = None
    workflow_type: WorkflowType
    engine: EngineType
    status: ComputationStatus
    molecule: MoleculeInput
    parameters: ComputationParameters
    resources: ComputationResources
    external_refs: dict = Field(default_factory=dict)
    steps: list[ComputationStep] = Field(default_factory=list)
    artifact_ids: list[str] = Field(default_factory=list)
    result_summary: dict = Field(default_factory=dict)
    error: dict | None = None
    created_by: str
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    source: str | None = None
    campaign_id: str | None = None
    suggestion_id: str | None = None


class ComputationCreateData(BaseModel):
    """创建计算任务响应。"""

    run_id: str
    status: ComputationStatus


class ComputationListData(BaseModel):
    """计算任务分页响应。"""

    items: list[ComputationRun]
    page: int
    page_size: int
    total: int


class ComputationArtifact(BaseModel):
    """计算 artifact 元数据。"""

    artifact_id: str
    run_id: str
    step_key: str
    artifact_type: ArtifactType
    name: str
    storage_uri: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    parser_name: str | None = None
    parser_version: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ArtifactListData(BaseModel):
    """artifact 列表响应。"""

    items: list[ComputationArtifact]


class ArtifactPreviewData(BaseModel):
    """artifact 预览响应。"""

    artifact: ComputationArtifact
    preview: dict | str
