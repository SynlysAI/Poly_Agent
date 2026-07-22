"""计算智能模块数据契约。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


ComputationStatus = Literal["queued", "running", "completed", "failed", "cancelled"]
WorkflowType = Literal["LOCAL_STRUCTURE", "LOCAL_XTB", "ORCA_COMPUTE_ENGINE_LASER"]
EngineType = Literal["LOCAL", "RDKit", "OPENBABEL", "XTB", "ORCA"]
LegacyWorkflowType = Literal["MOCK_XTB_ONLY", "MOCK_LASER"]
LegacyEngineType = Literal["MOCK"]
PersistedWorkflowType = WorkflowType | LegacyWorkflowType
PersistedEngineType = EngineType | LegacyEngineType
ArtifactType = Literal[
    "input_file",
    "parsed_input_json",
    "table_json",
    "series_json",
    "result_json",
    "log_text",
    "structure_json",
    "input_json",
    "error_json",
    "sdf",
    "xyz",
    "spectrum_json",
    "metrics_json",
    "report_json",
    "image_png",
    "csv",
    "binary_file",
]
ArtifactOwnerType = Literal["computation_run", "algorithm_run"]

ALLOWED_METHODS = {
    "GFN2-XTB": "GFN2-xTB",
    "GFN1-XTB": "GFN1-xTB",
    "GFN0-XTB": "GFN0-xTB",
    "ORCA_B3LYP_DEF2_SVP": "ORCA_B3LYP_DEF2_SVP",
    "ORCA_PBE0_DEF2_SVP": "ORCA_PBE0_DEF2_SVP",
}
ALLOWED_SOLVENTS = {
    "WATER": "WATER",
    "ACETONITRILE": "ACETONITRILE",
    "TOLUENE": "TOLUENE",
    "ETHANOL": "ETHANOL",
    "METHANOL": "METHANOL",
    "DCM": "DCM",
    "THF": "THF",
}


class MoleculeInput(BaseModel):
    """计算任务分子输入。"""

    model_config = ConfigDict(extra="forbid")

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

    model_config = ConfigDict(extra="forbid")

    charge: int = Field(default=0, ge=-5, le=5)
    multiplicity: int = Field(default=1, ge=1, le=6)
    method: str = Field(default="GFN2-xTB", max_length=80)
    solvent: str | None = Field(default=None, max_length=80)

    @field_validator("method")
    @classmethod
    def validate_method(cls, value: str) -> str:
        """Restrict methods to backend-owned presets."""
        normalized = value.strip().replace("_XTB", "-XTB")
        key = normalized.upper()
        if key not in ALLOWED_METHODS:
            raise ValueError("method 必须来自后端白名单")
        return ALLOWED_METHODS[key]

    @field_validator("solvent")
    @classmethod
    def validate_solvent(cls, value: str | None) -> str | None:
        """Restrict solvents to backend-owned presets."""
        if value is None or not value.strip():
            return None
        key = value.strip().upper()
        if key not in ALLOWED_SOLVENTS:
            raise ValueError("solvent 必须来自后端白名单")
        return ALLOWED_SOLVENTS[key]


class ComputationResources(BaseModel):
    """计算资源上限。"""

    model_config = ConfigDict(extra="forbid")

    num_cores: int = Field(default=2, ge=1, le=32)
    memory_mb: int = Field(default=4096, ge=512, le=131072)
    max_wallclock_seconds: int = Field(default=1800, ge=60, le=172800)


class ComputationCreateRequest(BaseModel):
    """创建计算任务请求。"""

    model_config = ConfigDict(extra="forbid")

    workflow_type: WorkflowType = "LOCAL_XTB"
    engine: EngineType = "XTB"
    molecule: MoleculeInput
    parameters: ComputationParameters = Field(default_factory=ComputationParameters)
    resources: ComputationResources = Field(default_factory=ComputationResources)
    source: str | None = Field(default=None, max_length=80)
    campaign_id: str | None = Field(default=None, max_length=80)
    suggestion_id: str | None = Field(default=None, max_length=80)
    material_record_id: str | None = Field(default=None, max_length=120)
    dataset_id: str | None = Field(default=None, max_length=120)


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
    workflow_type: PersistedWorkflowType
    engine: PersistedEngineType
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
    material_record_id: str | None = None
    dataset_id: str | None = None


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
    owner_type: ArtifactOwnerType = "computation_run"
    owner_id: str | None = None
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


class ComputationArtifactResponse(BaseModel):
    """计算 artifact 公开响应元数据。"""

    artifact_id: str
    run_id: str
    owner_type: ArtifactOwnerType = "computation_run"
    owner_id: str | None = None
    step_key: str
    artifact_type: ArtifactType
    name: str
    mime_type: str
    size_bytes: int
    checksum_sha256: str
    download_url: str
    parser_name: str | None = None
    parser_version: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class ArtifactListResponseData(BaseModel):
    """artifact 公开列表响应。"""

    items: list[ComputationArtifactResponse]


class ArtifactPreviewResponseData(BaseModel):
    """artifact 公开预览响应。"""

    artifact: ComputationArtifactResponse
    preview: dict | str


class ArtifactStructureResponseData(BaseModel):
    """结构 artifact 公开响应。"""

    artifact: ComputationArtifactResponse
    structure: dict


class ArtifactSpectrumResponseData(BaseModel):
    """光谱/曲线 artifact 公开响应。"""

    artifact: ComputationArtifactResponse
    spectrum: dict


class ArtifactListData(BaseModel):
    """artifact 列表响应。"""

    items: list[ComputationArtifact]


class ArtifactPreviewData(BaseModel):
    """artifact 预览响应。"""

    artifact: ComputationArtifact
    preview: dict | str


class ArtifactStructureData(BaseModel):
    """结构 artifact 响应。"""

    artifact: ComputationArtifact
    structure: dict


class ArtifactSpectrumData(BaseModel):
    """光谱/曲线 artifact 响应。"""

    artifact: ComputationArtifact
    spectrum: dict


class AuditEvent(BaseModel):
    """审计事件记录。"""

    event_id: str
    event_type: str
    actor_user_id: str
    actor_role: str
    request_id: str | None = None
    entity_type: str
    entity_id: str
    related_ids: dict = Field(default_factory=dict)
    before: dict = Field(default_factory=dict)
    after: dict = Field(default_factory=dict)
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class AuditEventListData(BaseModel):
    """审计事件分页响应。"""

    items: list[AuditEvent]
    page: int
    page_size: int
    total: int
