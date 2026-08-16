"""ResearchEngine API 端点。

暴露 ProblemSpec、AlgorithmRegistry、AlgorithmRun、ResearchRun 和 Stage/Gate 的 REST API。
"""

from __future__ import annotations

import json
from urllib.parse import quote

from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import Response

from app.core.auth import get_current_user
from app.core.config import settings
from app.schemas.common import ApiResponse
from app.schemas.computation import ArtifactListResponseData, ComputationArtifact, ComputationArtifactResponse
from app.schemas.research_engine import (
    AlgorithmCreditSummary,
    AlgorithmCreditUpdateRequest,
    AlgorithmMetadataUpdateRequest,
    AlgorithmHandoff,
    AlgorithmHandoffCreate,
    AlgorithmHandoffListData,
    AlgorithmHandoffValidationResult,
    AlgorithmInterfaceCreate,
    AlgorithmInterfaceDetails,
    AlgorithmInterfaceListData,
    AlgorithmInterfaceTestRequest,
    AlgorithmInterfaceTestResult,
    AlgorithmInterfaceVersionCreate,
    AlgorithmInterfaceVersionUpdate,
    AlgorithmIdAvailability,
    AlgorithmManagedResource,
    AlgorithmManagedResourceCreate,
    AlgorithmManagedResourceListData,
    AlgorithmRequirementDocumentParseResult,
    AlgorithmRegistryEntry,
    AlgorithmRegistryListData,
    AlgorithmPackage,
    AlgorithmPackageCreate,
    AlgorithmPackageExampleListData,
    AlgorithmPackageInspect,
    AlgorithmPackageListData,
    AlgorithmRun,
    AlgorithmRunCreate,
    AlgorithmRunListData,
    AlgorithmResourceBinding,
    AlgorithmRunTraceability,
    AlgorithmVersion,
    AlgorithmVersionProposalUpdate,
    AlgorithmVersionListData,
    ArchiveRequest,
    EntityAuditListData,
    ExecutionDecision,
    ExecutionDecisionCreate,
    ExecutionDecisionListData,
    ManualAlgorithmWorkflow,
    ManualAlgorithmWorkflowCreate,
    ManualAlgorithmWorkflowListData,
    ProblemSpec,
    ProblemSpecCreate,
    ProblemSpecListData,
    ResearchRun,
    ResearchRunCreate,
    ResearchRunListData,
    ResearchEngineReadinessData,
    ResearchRunStatusChangeRequest,
    ResearchRunTraceability,
    ResearchEngineExampleInstantiateResult,
    ResearchEngineExampleListData,
    StageApprovalRequest,
    StageRunTraceability,
    WorkflowRun,
    WorkflowRunListData,
)
from app.services.algorithm_requirement_doc_service import AlgorithmRequirementDocService
from app.services.algorithm_handoff_service import AlgorithmHandoffService
from app.services.algorithm_resource_service import AlgorithmManagedResourceService
from app.services.research_engine_algorithm_package_service import AlgorithmPackageService
from app.services.research_engine_orchestrator import ResearchEngineOrchestrator
from app.services.research_engine_readiness_service import ResearchEngineReadinessService
from app.services.research_engine_service import ResearchEngineService
from app.services.computation_service import ComputationService
from app.services.remote_interface_service import RemoteInterfaceService
from app.infra.research_engine_repositories import AlgorithmRegistryRepository

router = APIRouter(prefix="/research-engine", tags=["research-engine"])
service = ResearchEngineService()
orchestrator = ResearchEngineOrchestrator()
readiness_service = ResearchEngineReadinessService()
package_service = AlgorithmPackageService()
remote_interface_service = RemoteInterfaceService()
handoff_service = AlgorithmHandoffService()
algorithm_resource_service = AlgorithmManagedResourceService()
requirement_doc_service = AlgorithmRequirementDocService()
artifact_service = ComputationService()
MAX_MULTIPART_ASSET_BYTES = 50 * 1024 * 1024


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    """解析当前操作人。"""
    return current_user["user_id"] if current_user else "demo_user"


def _actor_user_name(current_user: dict[str, str] | None) -> str:
    """解析当前操作人的展示名称，未启用鉴权时使用稳定回退值。"""
    return (current_user or {}).get("username") or "demo_user"


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    """解析用于数据权限过滤的用户 ID。"""
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    """判断当前用户是否管理员。"""
    return bool(current_user and current_user.get("role") == "admin")


def _has_full_access(current_user: dict[str, str] | None) -> bool:
    """未开启登录或管理员登录时不做用户级资源过滤。"""
    return current_user is None or _is_admin(current_user)


def _require_full_access(current_user: dict[str, str] | None) -> None:
    """限制宿主机路径类治理操作只能由全权限用户执行。"""
    if not _has_full_access(current_user):
        raise HTTPException(status_code=403, detail="无权限管理算法资源")


def _request_id(request: Request) -> str | None:
    """读取请求追踪 ID。"""
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


def _artifact_download_url(artifact_id: str) -> str:
    return f"{settings.api_prefix}/artifacts/{artifact_id}/download"


def _public_artifact(artifact: ComputationArtifact) -> ComputationArtifactResponse:
    return ComputationArtifactResponse(
        artifact_id=artifact.artifact_id,
        run_id=artifact.run_id,
        owner_type=artifact.owner_type,
        owner_id=artifact.owner_id or artifact.run_id,
        step_key=artifact.step_key,
        artifact_type=artifact.artifact_type,
        name=artifact.name,
        mime_type=artifact.mime_type,
        size_bytes=artifact.size_bytes,
        checksum_sha256=artifact.checksum_sha256,
        download_url=_artifact_download_url(artifact.artifact_id),
        parser_name=artifact.parser_name,
        parser_version=artifact.parser_version,
        metadata=artifact.metadata,
        created_at=artifact.created_at,
    )


def _ensure_package_access(package_id: str, current_user: dict[str, str] | None) -> AlgorithmPackage:
    """校验当前用户是否可访问上传算法包。"""
    package = package_service.get_package(package_id)
    if _has_full_access(current_user) or package.created_by == _access_user_id(current_user):
        return package
    raise HTTPException(status_code=403, detail="无权限访问该算法包")


def _ensure_version_access(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None,
) -> AlgorithmVersion:
    """校验当前用户是否可访问上传算法版本。"""
    version = package_service.get_version(version_id)
    if version.algorithm_id != algorithm_id:
        raise HTTPException(status_code=409, detail="算法 ID 与版本不匹配")
    if _has_full_access(current_user) or version.created_by == _access_user_id(current_user):
        return version
    raise HTTPException(status_code=403, detail="无权限访问该算法版本")


def _ensure_interface_access(
    algorithm_id: str,
    current_user: dict[str, str] | None,
    *,
    manage: bool = False,
) -> AlgorithmRegistryEntry:
    """校验接口模型的查看、调用或治理权限。"""
    entry = service.get_algorithm(algorithm_id)
    if entry.source != "remote_interface":
        raise HTTPException(status_code=409, detail="目标算法不是接口调用模型")
    if _has_full_access(current_user) or entry.owner == _access_user_id(current_user):
        return entry
    if not manage and entry.visibility == "public":
        return entry
    raise HTTPException(status_code=403, detail="无权限访问该接口模型")


def _is_remote_interface_algorithm(algorithm_id: str) -> bool:
    """判断注册表中是否已经登记为远程接口模型。

    上传包在首次部署前可能尚未写入注册表，因此这里不能调用通用详情服务。
    """
    entry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
    return bool(entry and entry.get("source") == "remote_interface")


@router.get("/readiness", response_model=ApiResponse[ResearchEngineReadinessData])
def get_research_engine_readiness() -> ApiResponse[ResearchEngineReadinessData]:
    """获取 AutoResearch 启动前集成可用性摘要。"""
    return ApiResponse(code=0, message="ok", data=readiness_service.get_readiness())


# =============================================================================
# Remote interface algorithm API
# =============================================================================


@router.post("/algorithm-interfaces", response_model=ApiResponse[AlgorithmInterfaceDetails])
def create_algorithm_interface(
    payload: AlgorithmInterfaceCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmInterfaceDetails]:
    """创建远程接口型垂类模型。"""
    data = remote_interface_service.create_interface(
        payload,
        actor_user_id=_actor_user_id(current_user),
        actor_user_name=_actor_user_name(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/algorithm-interfaces/{algorithm_id}/versions",
    response_model=ApiResponse[AlgorithmVersion],
)
def create_algorithm_interface_version(
    algorithm_id: str,
    payload: AlgorithmInterfaceVersionCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """创建远程接口模型的新版本。"""
    _ensure_interface_access(algorithm_id, current_user, manage=True)
    data = remote_interface_service.create_version(
        algorithm_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        actor_user_name=_actor_user_name(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/algorithm-interfaces/{algorithm_id}/versions/{version_id}",
    response_model=ApiResponse[AlgorithmVersion],
)
def update_algorithm_interface_version(
    algorithm_id: str,
    version_id: str,
    payload: AlgorithmInterfaceVersionUpdate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """更新尚未激活的远程接口模型版本草稿。"""
    _ensure_interface_access(algorithm_id, current_user, manage=True)
    data = remote_interface_service.update_version(algorithm_id, version_id, payload)
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-interfaces", response_model=ApiResponse[AlgorithmInterfaceListData])
def list_algorithm_interfaces(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmInterfaceListData]:
    """分页查询可见的远程接口模型。"""
    data = remote_interface_service.list_interfaces(created_by=None, page=page, page_size=page_size)
    if not _has_full_access(current_user):
        user_id = _access_user_id(current_user)
        visible = [
            item for item in data.items
            if item.owner == user_id or item.visibility == "public"
        ]
        data = AlgorithmInterfaceListData(items=visible, page=page, page_size=page_size, total=len(visible))
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/algorithm-interfaces/{algorithm_id}",
    response_model=ApiResponse[AlgorithmInterfaceDetails],
)
def get_algorithm_interface(
    algorithm_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmInterfaceDetails]:
    """获取远程接口模型详情。"""
    _ensure_interface_access(algorithm_id, current_user)
    return ApiResponse(code=0, message="ok", data=remote_interface_service.get_interface(algorithm_id))


@router.post(
    "/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test",
    response_model=ApiResponse[AlgorithmInterfaceTestResult],
)
def test_algorithm_interface(
    algorithm_id: str,
    version_id: str,
    payload: AlgorithmInterfaceTestRequest | None = Body(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmInterfaceTestResult]:
    """使用样例输入测试远程接口版本。"""
    _ensure_interface_access(algorithm_id, current_user, manage=True)
    result = remote_interface_service.test_version(
        algorithm_id,
        version_id,
        input_snapshot=payload.input_snapshot if payload else None,
    )
    return ApiResponse(code=0, message="ok", data=result)


@router.post(
    "/algorithm-interfaces/{algorithm_id}/versions/{version_id}:test-multipart",
    response_model=ApiResponse[AlgorithmInterfaceTestResult],
)
async def test_algorithm_interface_multipart(
    algorithm_id: str,
    version_id: str,
    request: Request,
    input_snapshot: str = Form(default="{}"),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmInterfaceTestResult]:
    """使用 multipart 文件和 JSON 输入测试远程接口版本。"""
    _ensure_interface_access(algorithm_id, current_user, manage=True)
    try:
        snapshot = json.loads(input_snapshot)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="input_snapshot 必须是合法 JSON") from exc
    if not isinstance(snapshot, dict):
        raise HTTPException(status_code=422, detail="input_snapshot 必须是 JSON object")
    form = await request.form()
    temp_root = settings.outputs_root / "interface-tests" / f"{algorithm_id}-{version_id}"
    temp_root.mkdir(parents=True, exist_ok=True)
    uploads: dict[str, dict[str, str]] = {}
    for key, value in form.multi_items():
        if key == "input_snapshot" or not hasattr(value, "read"):
            continue
        content = await value.read(MAX_MULTIPART_ASSET_BYTES + 1)
        if len(content) > MAX_MULTIPART_ASSET_BYTES:
            raise HTTPException(status_code=413, detail=f"输入文件 {key} 超过平台上传上限")
        filename = value.filename or key
        target = temp_root / f"{version_id}-{key}-{filename.replace('/', '_')}"
        target.write_bytes(content)
        uploads[key] = {"path": str(target), "filename": filename, "mime_type": value.content_type or "application/octet-stream"}
    result = remote_interface_service.test_version(algorithm_id, version_id, input_snapshot=snapshot, input_files=uploads)
    return ApiResponse(code=0, message="ok", data=result)


@router.post(
    "/algorithm-interfaces/{algorithm_id}/versions/{version_id}:activate",
    response_model=ApiResponse[AlgorithmVersion],
)
def activate_algorithm_interface_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """激活远程接口模型版本。"""
    _ensure_interface_access(algorithm_id, current_user, manage=True)
    return ApiResponse(
        code=0,
        message="ok",
        data=remote_interface_service.activate_version(algorithm_id, version_id),
    )


# =============================================================================
# AlgorithmPackage API
# =============================================================================


def _json_form_object(raw: str | None, fallback: object) -> object:
    """解析 multipart 中的 JSON 字段。"""
    if raw is None or raw == "":
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail=f"JSON 字段格式错误: {exc.msg}") from exc


@router.post("/algorithm-resources", response_model=ApiResponse[AlgorithmManagedResource])
def create_algorithm_resource(
    payload: AlgorithmManagedResourceCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmManagedResource]:
    """登记后端宿主机可访问的算法大资源路径。"""
    _require_full_access(current_user)
    data = algorithm_resource_service.create_resource(
        payload,
        actor_user_id=_actor_user_id(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-resources", response_model=ApiResponse[AlgorithmManagedResourceListData])
def list_algorithm_resources(
    algorithm_id: str | None = Query(default=None),
    asset_key: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ApiResponse[AlgorithmManagedResourceListData]:
    """查询已登记的算法大资源。"""
    data = algorithm_resource_service.list_resources(
        algorithm_id=algorithm_id,
        asset_key=asset_key,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-resources/{resource_id}:check", response_model=ApiResponse[AlgorithmManagedResource])
def check_algorithm_resource(
    resource_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmManagedResource]:
    """重新检查已登记算法资源的路径健康状态。"""
    _require_full_access(current_user)
    return ApiResponse(code=0, message="ok", data=algorithm_resource_service.check_resource(resource_id))


@router.get("/algorithm-packages/template")
def download_algorithm_package_template() -> Response:
    """下载标准算法模板 ZIP。"""
    content = package_service.create_template_zip()
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=polyagent-algorithm-template.zip"},
    )


@router.get("/algorithm-requirement-docs/template")
def download_algorithm_requirement_document_template() -> Response:
    """下载需求文档模板。"""
    filename, content = requirement_doc_service.download_template()
    media_type = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        if filename.endswith(".docx")
        else "text/markdown; charset=utf-8"
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"},
    )


@router.post(
    "/algorithm-requirement-docs:parse",
    response_model=ApiResponse[AlgorithmRequirementDocumentParseResult],
)
async def parse_algorithm_requirement_document(
    file: UploadFile = File(...),
) -> ApiResponse[AlgorithmRequirementDocumentParseResult]:
    """解析需求文档并生成接入草案。"""
    content = await file.read()
    data = requirement_doc_service.parse_document(
        filename=file.filename or "algorithm-requirement.md",
        content=content,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-package-examples", response_model=ApiResponse[AlgorithmPackageExampleListData])
def list_algorithm_package_examples() -> ApiResponse[AlgorithmPackageExampleListData]:
    """查询面向算法对接人的接入包模板。"""
    return ApiResponse(code=0, message="ok", data=handoff_service.list_examples())


@router.get("/algorithm-package-examples/{example_id}/download")
def download_algorithm_package_example(example_id: str) -> Response:
    """下载指定类型的算法接入 example ZIP。"""
    filename, content = handoff_service.download_example_package(example_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/algorithm-handoffs", response_model=ApiResponse[AlgorithmHandoff])
def create_algorithm_handoff(
    payload: AlgorithmHandoffCreate,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmHandoff]:
    """创建算法对接任务，并生成对接人交付链接。"""
    data = handoff_service.create_handoff(payload, actor_user_id=_actor_user_id(current_user))
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-handoffs", response_model=ApiResponse[AlgorithmHandoffListData])
def list_algorithm_handoffs(
    status: str | None = Query(default=None),
    example_id: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmHandoffListData]:
    """分页查询算法对接任务。"""
    data = handoff_service.list_handoffs(
        status=status,
        example_id=example_id,
        created_by=None if _has_full_access(current_user) else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-handoffs/{handoff_id}", response_model=ApiResponse[AlgorithmHandoff])
def get_algorithm_handoff(handoff_id: str) -> ApiResponse[AlgorithmHandoff]:
    """获取算法对接任务详情。"""
    return ApiResponse(code=0, message="ok", data=handoff_service.get_handoff(handoff_id))


@router.get("/algorithm-handoffs/{handoff_id}/package")
def download_algorithm_handoff_package(handoff_id: str) -> Response:
    """下载已按对接任务预填的算法接入包。"""
    filename, content = handoff_service.download_handoff_package(handoff_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post(
    "/algorithm-handoffs/{handoff_id}:validate",
    response_model=ApiResponse[AlgorithmHandoffValidationResult],
)
async def validate_algorithm_handoff_package(
    handoff_id: str,
    file: UploadFile = File(...),
    resource_bindings: str = Form(default="[]"),
) -> ApiResponse[AlgorithmHandoffValidationResult]:
    """对算法对接包做上传前自测，不创建正式算法版本。"""
    content = await file.read()
    data = handoff_service.validate_handoff_package(
        handoff_id,
        filename=file.filename or "handoff.zip",
        content=content,
        resource_bindings=_json_form_object(resource_bindings, []),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-handoffs/{handoff_id}:submit", response_model=ApiResponse[AlgorithmHandoff])
def mark_algorithm_handoff_submitted(handoff_id: str) -> ApiResponse[AlgorithmHandoff]:
    """标记算法对接任务已提交正式部署。"""
    return ApiResponse(code=0, message="ok", data=handoff_service.mark_submitted(handoff_id))


@router.post("/algorithm-packages:pack", response_model=ApiResponse[AlgorithmPackage])
async def pack_algorithm_package(
    request: Request,
    algorithm_id: str = Form(...),
    name: str = Form(...),
    version: str = Form(...),
    algorithm_family: str = Form(default="vertical_prediction"),
    type: str = Form(default="predictor"),
    material_scope: str = Form(default='["universal"]'),
    task_scope: str = Form(default='["COMPUTE_PREDICT"]'),
    trigger_modes: str = Form(default='["human_workflow","autoresearch"]'),
    entrypoint: str = Form(default="src.handler:predict"),
    loader: str | None = Form(default=None),
    input_schema: str = Form(default='{"fields":{"smiles":"string"},"required":["smiles"]}'),
    output_schema: str = Form(default='{"fields":{"prediction":"object"},"required":["prediction"]}'),
    input_assets: str = Form(default="[]"),
    output_assets: str = Form(default="[]"),
    resource_assets: str = Form(default="[]"),
    result_envelope: str | None = Form(default=None),
    runtime: str = Form(default='{"python":"3.11","resources":{"cpu":1,"memory":"1Gi","gpu":false},"timeout_seconds":30}'),
    sample_input: str = Form(default='{"smiles":"C=C(F)F"}'),
    description: str | None = Form(default=None),
    developer: str | None = Form(default=None),
    developer_organization: str | None = Form(default=None),
    mentor_team: str | None = Form(default=None),
    developer_contact: str | None = Form(default=None),
    source_url: str | None = Form(default=None),
    citation: str | None = Form(default=None),
    contributors: str = Form(default="[]"),
    method_attributions: str = Form(default="[]"),
    logo_asset: str | None = Form(default=None),
    logo_url: str | None = Form(default=None),
    visibility: str = Form(default="private"),
    files: list[UploadFile] = File(default=[]),
    requirements: UploadFile | None = File(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """网页打包助手：原始 Python 文件 + 表单生成标准 ZIP 并保存。"""
    visibility = package_service._normalize_visibility(visibility)
    payload = AlgorithmPackageCreate(
        algorithm_id=algorithm_id,
        name=name,
        version=version,
        algorithm_family=algorithm_family,
        type=type,
        material_scope=_json_form_object(material_scope, ["universal"]),
        task_scope=_json_form_object(task_scope, ["COMPUTE_PREDICT"]),
        trigger_modes=_json_form_object(trigger_modes, ["human_workflow", "autoresearch"]),
        entrypoint=entrypoint,
        loader=loader or None,
        input_schema=_json_form_object(input_schema, {}),
        output_schema=_json_form_object(output_schema, {}),
        input_assets=_json_form_object(input_assets, []),
        output_assets=_json_form_object(output_assets, []),
        resource_assets=_json_form_object(resource_assets, []),
        result_envelope=result_envelope or None,
        runtime=_json_form_object(runtime, {}),
        sample_input=_json_form_object(sample_input, {}),
        description=description,
        developer=developer,
        developer_organization=developer_organization,
        mentor_team=mentor_team,
        developer_contact=developer_contact,
        source_url=source_url,
        citation=citation,
        contributors=_json_form_object(contributors, []),
        method_attributions=_json_form_object(method_attributions, []),
        logo_asset=logo_asset,
        logo_url=logo_url,
        visibility=visibility,
    )
    source_files: dict[str, bytes] = {}
    for upload in files:
        if not upload.filename:
            continue
        source_files[upload.filename] = await upload.read()
    requirements_bytes = await requirements.read() if requirements else None
    zip_bytes = package_service.pack_from_sources(
        payload,
        source_files=source_files,
        requirements=requirements_bytes,
    )
    data = package_service.upload_package(
        filename=f"{payload.algorithm_id}-{payload.version}.zip",
        content=zip_bytes,
        actor_user_id=_actor_user_id(current_user),
        actor_user_name=_actor_user_name(current_user),
        visibility=visibility,
    )
    data = package_service.validate_package(data.package_id)
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-packages", response_model=ApiResponse[AlgorithmPackage])
async def upload_algorithm_package(
    file: UploadFile = File(...),
    visibility: str | None = Form(default=None),
    handoff_id: str | None = Form(default=None),
    target_algorithm_id: str | None = Form(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """上传标准 ZIP 算法包。"""
    if target_algorithm_id and visibility is not None:
        raise HTTPException(
            status_code=422,
            detail="新版本上传时 visibility 由包内 polyagent.algorithm.yaml 决定，不允许单独指定",
        )
    if target_algorithm_id:
        active_version = package_service.resolve_active_version(target_algorithm_id)
        if active_version is None:
            raise HTTPException(status_code=409, detail="目标算法没有可继承的活动版本")
        _ensure_version_access(target_algorithm_id, active_version.version_id, current_user)
    content = await file.read()
    if handoff_id:
        content = handoff_service.rewrite_package_with_handoff(handoff_id, content)
    if visibility is not None:
        visibility = package_service._normalize_visibility(visibility)
    data = package_service.upload_package(
        filename=file.filename or "algorithm-package.zip",
        content=content,
        actor_user_id=_actor_user_id(current_user),
        actor_user_name=_actor_user_name(current_user),
        visibility=visibility,
        target_algorithm_id=target_algorithm_id,
        owner_user_id=(
            package_service.resolve_algorithm_owner(target_algorithm_id)
            if target_algorithm_id
            else None
        ),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-packages:inspect", response_model=ApiResponse[AlgorithmPackageInspect])
async def inspect_algorithm_package(
    file: UploadFile = File(...),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackageInspect]:
    """只读预览标准 ZIP 算法包契约元数据，不落库、不触发校验。"""
    if not (file.filename or "").endswith(".zip"):
        raise HTTPException(status_code=422, detail="仅支持 .zip 算法包")
    content = await file.read()
    metadata = package_service.inspect_package(content)
    return ApiResponse(code=0, message="ok", data=AlgorithmPackageInspect(**metadata))


@router.post("/algorithm-packages:pack-version", response_model=ApiResponse[AlgorithmPackage])
async def pack_algorithm_package_version(
    target_algorithm_id: str = Form(...),
    version: str = Form(...),
    sample_input: str | None = Form(default=None),
    model_proposal: str | None = Form(default=None),
    files: list[UploadFile] = File(default=[]),
    requirements: UploadFile | None = File(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """基于当前活动包替换脚本并创建新版本包。"""
    active_version = package_service.resolve_active_version(target_algorithm_id)
    if active_version is not None:
        _ensure_version_access(target_algorithm_id, active_version.version_id, current_user)
    source_files = {
        upload.filename: await upload.read()
        for upload in files
        if upload.filename
    }
    requirements_bytes = await requirements.read() if requirements else None
    zip_bytes = package_service.pack_new_version_from_sources(
        target_algorithm_id,
        version,
        source_files=source_files,
        requirements=requirements_bytes,
        sample_input=_json_form_object(sample_input, {}) if sample_input is not None else None,
        model_proposal=_json_form_object(model_proposal, {}) if model_proposal is not None else None,
    )
    package = package_service.upload_package(
        filename=f"{target_algorithm_id}-{version}.zip",
        content=zip_bytes,
        actor_user_id=_actor_user_id(current_user),
        actor_user_name=_actor_user_name(current_user),
        target_algorithm_id=target_algorithm_id,
        owner_user_id=package_service.resolve_algorithm_owner(target_algorithm_id),
    )
    return ApiResponse(code=0, message="ok", data=package)


@router.get("/algorithm-packages", response_model=ApiResponse[AlgorithmPackageListData])
def list_algorithm_packages(
    algorithm_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackageListData]:
    """查询上传算法包。"""
    data = package_service.list_packages(
        algorithm_id=algorithm_id,
        status=status,
        created_by=None if _has_full_access(current_user) else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-packages/{package_id}", response_model=ApiResponse[AlgorithmPackage])
def get_algorithm_package(
    package_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """查看算法包状态。"""
    return ApiResponse(code=0, message="ok", data=_ensure_package_access(package_id, current_user))


@router.get("/algorithm-packages/{package_id}/download")
def download_algorithm_package(
    package_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> Response:
    """下载已上传或由平台生成的标准算法 ZIP。"""
    _ensure_package_access(package_id, current_user)
    filename, content = package_service.download_package(package_id)
    return Response(
        content=content,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/algorithm-packages/{package_id}:validate", response_model=ApiResponse[AlgorithmPackage])
def validate_algorithm_package(
    package_id: str,
    resource_bindings: list[AlgorithmResourceBinding] | None = Body(default=None, embed=True),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """校验算法包并生成 AlgorithmVersion。"""
    _ensure_package_access(package_id, current_user)
    return ApiResponse(
        code=0,
        message="ok",
        data=package_service.validate_package(package_id, resource_bindings=resource_bindings),
    )


@router.post("/algorithm-packages/{package_id}:build", response_model=ApiResponse[AlgorithmPackage])
def build_algorithm_package(
    package_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmPackage]:
    """构建算法包。P0 记录本机 adapter build 状态。"""
    _ensure_package_access(package_id, current_user)
    return ApiResponse(code=0, message="ok", data=package_service.build_package(package_id))


@router.post("/algorithm-packages/{package_id}:release", response_model=ApiResponse[AlgorithmVersion])
def release_algorithm_package(
    package_id: str,
    resource_bindings: list[AlgorithmResourceBinding] | None = Body(default=None, embed=True),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """校验、构建、部署并自动激活算法包。"""
    _ensure_package_access(package_id, current_user)
    data = package_service.release_package(package_id, resource_bindings=resource_bindings)
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithms/{algorithm_id}/versions", response_model=ApiResponse[AlgorithmVersionListData])
def list_algorithm_versions(
    algorithm_id: str,
    status: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersionListData]:
    """查询指定算法的版本。"""
    registry = AlgorithmRegistryRepository.find_one({"algorithm_id": algorithm_id})
    public_registry = bool(registry and registry.get("visibility") == "public")
    data = package_service.list_versions(
        algorithm_id=algorithm_id,
        status=status,
        created_by=None if _has_full_access(current_user) or public_registry else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    if public_registry and not _has_full_access(current_user):
        visible_items = [item for item in data.items if item.visibility == "public"]
        data = AlgorithmVersionListData(
            items=visible_items,
            page=data.page,
            page_size=data.page_size,
            total=len(visible_items),
        )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/algorithms/{algorithm_id}/versions/{version_id}/proposal",
    response_model=ApiResponse[AlgorithmVersion],
)
def update_algorithm_version_model_proposal(
    algorithm_id: str,
    version_id: str,
    payload: AlgorithmVersionProposalUpdate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """更新指定算法版本的模型提案。"""
    data = service.update_algorithm_version_model_proposal(
        algorithm_id,
        version_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithms/{algorithm_id}/versions/{version_id}:deploy", response_model=ApiResponse[AlgorithmVersion])
def deploy_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """部署算法版本到 P0 本地 runtime。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        raise HTTPException(status_code=409, detail="远程接口版本无需部署，请先完成样例测试")
    return ApiResponse(code=0, message="ok", data=package_service.deploy_version(algorithm_id, version_id))


@router.post("/algorithms/{algorithm_id}/versions/{version_id}:redeploy", response_model=ApiResponse[AlgorithmVersion])
def redeploy_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """重新部署算法版本到 P0 本地 runtime。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        raise HTTPException(status_code=409, detail="远程接口版本无需重部署，请创建新接口版本")
    return ApiResponse(code=0, message="ok", data=package_service.redeploy_version(algorithm_id, version_id))


@router.get("/algorithms/{algorithm_id}/versions/{version_id}/health", response_model=ApiResponse[dict])
def get_algorithm_version_health(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[dict]:
    """查看算法版本 runtime health。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.version_health(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.version_health(algorithm_id, version_id))


@router.get("/algorithms/{algorithm_id}/versions/{version_id}/logs", response_model=ApiResponse[dict])
def get_algorithm_version_logs(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[dict]:
    """查看算法版本生命周期和 runtime 日志。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.version_logs(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.version_logs(algorithm_id, version_id))


@router.post("/algorithms/{algorithm_id}/versions/{version_id}:activate", response_model=ApiResponse[AlgorithmVersion])
def activate_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """激活算法版本。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.activate_version(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.activate_version(algorithm_id, version_id))


@router.post("/algorithms/{algorithm_id}/versions/{version_id}:rollback", response_model=ApiResponse[AlgorithmVersion])
def rollback_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """回滚到指定历史版本。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.activate_version(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.rollback_version(algorithm_id, version_id))


@router.post("/algorithms/{algorithm_id}/versions/{version_id}:freeze", response_model=ApiResponse[AlgorithmVersion])
def freeze_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """冻结指定算法版本。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.freeze_version(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.freeze_version(algorithm_id, version_id))


@router.post(
    "/algorithms/{algorithm_id}/versions/{version_id}:decommission",
    response_model=ApiResponse[AlgorithmVersion],
)
def decommission_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmVersion]:
    """下线指定算法版本。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.decommission_version(algorithm_id, version_id))
    return ApiResponse(code=0, message="ok", data=package_service.decommission_version(algorithm_id, version_id))


@router.delete("/algorithms/{algorithm_id}/versions/{version_id}", response_model=ApiResponse[dict])
def delete_decommissioned_algorithm_version(
    algorithm_id: str,
    version_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[dict]:
    """删除已下线算法版本及其上传包记录。"""
    _ensure_version_access(algorithm_id, version_id, current_user)
    if _is_remote_interface_algorithm(algorithm_id):
        return ApiResponse(code=0, message="ok", data=remote_interface_service.delete_version(algorithm_id, version_id))
    data = package_service.delete_decommissioned_version(algorithm_id, version_id)
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ProblemSpec API
# =============================================================================


@router.post("/problem-specs", response_model=ApiResponse[ProblemSpec])
def create_problem_spec(
    payload: ProblemSpecCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """创建 ProblemSpec 草稿。

    支持定义材料研发任务的变量、目标、约束和可选执行路径。
    创建时可选择关联已有 campaign 或自动创建首版容器 campaign。
    """
    data = service.create_problem_spec(
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/problem-specs", response_model=ApiResponse[ProblemSpecListData])
def list_problem_specs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    project_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    material_family: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpecListData]:
    """查询 ProblemSpec 列表。

    支持按项目、campaign、状态、材料体系过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_problem_specs(
            project_id=project_id,
            campaign_id=campaign_id,
            created_by=None if _is_admin(current_user) else _access_user_id(current_user),
            status=status,
            material_family=material_family,
            page=page,
            page_size=page_size,
        ),
    )


@router.post("/problem-specs/{problem_spec_id}:archive", response_model=ApiResponse[ProblemSpec])
def archive_problem_spec(
    problem_spec_id: str,
    request: Request,
    payload: ArchiveRequest | None = None,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """归档 ProblemSpec，默认列表隐藏但保留追溯链。"""
    data = service.archive_problem_spec(
        problem_spec_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason if payload else "用户归档研发任务",
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/problem-specs/{problem_spec_id}", response_model=ApiResponse[ProblemSpec])
def get_problem_spec(
    problem_spec_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """获取 ProblemSpec 详情。"""
    data = service.get_problem_spec(
        problem_spec_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch("/problem-specs/{problem_spec_id}", response_model=ApiResponse[ProblemSpec])
def update_problem_spec(
    problem_spec_id: str,
    payload: ProblemSpecCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """更新 ProblemSpec 草稿。

    已冻结的 ProblemSpec 不可直接修改，需复制为新版本。
    """
    data = service.update_problem_spec(
        problem_spec_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/problem-specs/{problem_spec_id}/freeze", response_model=ApiResponse[ProblemSpec])
def freeze_problem_spec(
    problem_spec_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ProblemSpec]:
    """冻结 ProblemSpec。

    冻结后不可直接修改，只能复制为新版本后编辑。
    """
    data = service.freeze_problem_spec(
        problem_spec_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ExecutionDecision API
# =============================================================================


@router.post(
    "/problem-specs/{problem_spec_id}/execution-decisions",
    response_model=ApiResponse[ExecutionDecision],
)
def create_execution_decision(
    problem_spec_id: str,
    payload: ExecutionDecisionCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecision]:
    """为 ProblemSpec 显式选择 manual_workbench 或 autoresearch。"""
    data = service.create_execution_decision(
        problem_spec_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/problem-specs/{problem_spec_id}/execution-decisions",
    response_model=ApiResponse[ExecutionDecisionListData],
)
def list_execution_decisions(
    problem_spec_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecisionListData]:
    """查询 ProblemSpec 的执行决策历史。"""
    data = service.list_execution_decisions(
        problem_spec_id=problem_spec_id,
        mode=mode,
        status=status,
        created_by=None if _is_admin(current_user) else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/problem-specs/{problem_spec_id}/execution-decisions/active",
    response_model=ApiResponse[ExecutionDecision],
)
def get_active_execution_decision(
    problem_spec_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExecutionDecision]:
    """查询 ProblemSpec 当前 active 执行决策。"""
    data = service.get_active_execution_decision(
        problem_spec_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# AlgorithmRegistry API
# =============================================================================


@router.get("/algorithms", response_model=ApiResponse[AlgorithmRegistryListData])
def list_algorithms(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    type: str | None = Query(default=None, alias="type"),
    algorithm_family: str | None = Query(default=None),
    material_scope: str | None = Query(default=None),
    trigger_mode: str | None = Query(default=None),
    status: str | None = Query(default=None),
    source: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRegistryListData]:
    """查询算法能力清单。

    支持按类型、材料体系、触发方式、状态过滤和分页。
    响应字段足够前端渲染算法卡和 schema drawer。
    """
    data = service.list_algorithms(
        algorithm_type=type,
        algorithm_family=algorithm_family,
        material_scope=material_scope,
        trigger_mode=trigger_mode,
        status=status,
        source=source,
        page=page,
        page_size=page_size,
    )
    if not _has_full_access(current_user):
        user_id = _access_user_id(current_user)
        items = [
            item
            for item in data.items
            if item.source not in {"uploaded_package", "remote_interface"}
            or item.owner == user_id
            or item.visibility == "public"
        ]
        data = AlgorithmRegistryListData(
            items=items,
            page=data.page,
            page_size=data.page_size,
            total=len(items),
        )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithms/id-availability", response_model=ApiResponse[AlgorithmIdAvailability])
def get_algorithm_id_availability(
    algorithm_id: str = Query(default="", min_length=1, max_length=80),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmIdAvailability]:
    """检查模型 ID 是否可用，并返回安全的下一步建议。"""
    data = remote_interface_service.get_id_availability(
        algorithm_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=AlgorithmIdAvailability(**data))


@router.delete("/algorithms/{algorithm_id}", response_model=ApiResponse[dict])
def delete_algorithm(
    algorithm_id: str,
    confirm_algorithm_id: str = Query(..., min_length=1, max_length=80),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[dict]:
    """删除接口模型及全部版本，历史运行与 Artifact 保留。"""
    entry = service.get_algorithm(algorithm_id)
    if entry.source != "remote_interface":
        raise HTTPException(status_code=409, detail="算法包模型请使用版本治理删除")
    data = remote_interface_service.delete_algorithm(
        algorithm_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        confirm_algorithm_id=confirm_algorithm_id,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithms/{algorithm_id}", response_model=ApiResponse[AlgorithmRegistryEntry])
def get_algorithm(
    algorithm_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRegistryEntry]:
    """获取单个算法能力条目详情。

    包含算法名称、类型、材料范围、输入输出 schema 等完整信息。
    """
    data = service.get_algorithm(algorithm_id)
    if (
        not _has_full_access(current_user)
        and data.source in {"uploaded_package", "remote_interface"}
        and data.owner != _access_user_id(current_user)
        and data.visibility != "public"
    ):
        raise HTTPException(status_code=403, detail="无权限访问该算法")
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/algorithms/{algorithm_id}/metadata",
    response_model=ApiResponse[AlgorithmRegistryEntry],
)
def update_algorithm_metadata(
    algorithm_id: str,
    payload: AlgorithmMetadataUpdateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRegistryEntry]:
    """由上传者或管理员维护已部署算法的展示信息。"""
    data = service.update_algorithm_metadata(
        algorithm_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/algorithms/{algorithm_id}/credit-summary",
    response_model=ApiResponse[AlgorithmCreditSummary],
)
def get_algorithm_credit_summary(
    algorithm_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmCreditSummary]:
    """查询算法轻量贡献台账。

    仅返回贡献者构成和可复核计数，不返回运行输入、项目内容或原始产物。
    """
    data = service.get_algorithm_credit_summary(
        algorithm_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/algorithms/{algorithm_id}/credit-summary",
    response_model=ApiResponse[AlgorithmCreditSummary],
)
def update_algorithm_credit_summary(
    algorithm_id: str,
    payload: AlgorithmCreditUpdateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmCreditSummary]:
    """管理员修正算法当前贡献者、角色和导师关系。"""
    _require_full_access(current_user)
    data = service.update_algorithm_credit_summary(
        algorithm_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# Examples API
# =============================================================================


@router.get("/examples", response_model=ApiResponse[ResearchEngineExampleListData])
def list_examples(
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchEngineExampleListData]:
    """列出可一键创建的 ResearchEngine 示例流程。"""
    return ApiResponse(code=0, message="ok", data=service.list_examples())


@router.post(
    "/examples/{example_id}/instantiate",
    response_model=ApiResponse[ResearchEngineExampleInstantiateResult],
)
def instantiate_example(
    example_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchEngineExampleInstantiateResult]:
    """实例化 ResearchEngine 示例流程并返回前端跳转信息。"""
    data = service.instantiate_example(
        example_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ManualWorkflow / WorkflowRun / AlgorithmRun API
# =============================================================================


@router.post("/manual-workflows", response_model=ApiResponse[ManualAlgorithmWorkflow])
def create_manual_workflow(
    payload: ManualAlgorithmWorkflowCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflow]:
    """创建人工算法 Workflow。"""
    data = service.create_manual_workflow(
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/manual-workflows", response_model=ApiResponse[ManualAlgorithmWorkflowListData])
def list_manual_workflows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    execution_decision_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflowListData]:
    """查询人工算法 Workflow 列表。"""
    data = service.list_manual_workflows(
        problem_spec_id=problem_spec_id,
        execution_decision_id=execution_decision_id,
        status=status,
        created_by=None if _is_admin(current_user) else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/manual-workflows/{workflow_id}:archive", response_model=ApiResponse[ManualAlgorithmWorkflow])
def archive_manual_workflow(
    workflow_id: str,
    request: Request,
    payload: ArchiveRequest | None = None,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflow]:
    """归档人工 Workflow，默认列表隐藏但保留运行历史和审计。"""
    data = service.archive_manual_workflow(
        workflow_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason if payload else "用户归档人工 Workflow",
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/manual-workflows/{workflow_id}", response_model=ApiResponse[ManualAlgorithmWorkflow])
def get_manual_workflow(
    workflow_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ManualAlgorithmWorkflow]:
    """获取人工算法 Workflow 详情。"""
    data = service.get_manual_workflow(
        workflow_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/manual-workflows/{workflow_id}/runs", response_model=ApiResponse[WorkflowRun])
def start_workflow_run(
    workflow_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRun]:
    """启动人工 WorkflowRun。"""
    data = service.start_workflow_run(
        workflow_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/workflow-runs", response_model=ApiResponse[WorkflowRunListData])
def list_workflow_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    workflow_id: str | None = Query(default=None),
    problem_spec_id: str | None = Query(default=None),
    execution_decision_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRunListData]:
    """查询 WorkflowRun 列表。"""
    data = service.list_workflow_runs(
        workflow_id=workflow_id,
        problem_spec_id=problem_spec_id,
        execution_decision_id=execution_decision_id,
        status=status,
        created_by=None if _is_admin(current_user) else _access_user_id(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/workflow-runs/{workflow_run_id}", response_model=ApiResponse[WorkflowRun])
def get_workflow_run(
    workflow_run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[WorkflowRun]:
    """获取 WorkflowRun 详情。"""
    data = service.get_workflow_run(
        workflow_run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-runs", response_model=ApiResponse[AlgorithmRun])
def create_algorithm_run(
    payload: AlgorithmRunCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRun]:
    """创建并执行算法运行。

    v0.4 产品主路径中，人工模式应由 ManualAlgorithmWorkflow / WorkflowRun 创建节点运行；
    该端点保留给兼容调用和 AutoResearch 内部编排。
    系统校验算法是否支持对应 trigger_source，执行 mock runner 并记录完整运行产物。
    运行产物包含 input_snapshot、output_summary、artifact_refs 和审计事件。
    """
    data = service.create_algorithm_run(
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/algorithm-runs:multipart", response_model=ApiResponse[AlgorithmRun])
async def create_algorithm_run_multipart(
    request: Request,
    payload: str = Form(...),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRun]:
    """创建带文件输入的算法运行。

    multipart 中 `payload` 是 AlgorithmRunCreate JSON，其余文件 part 名称必须匹配 input_assets.key。
    """
    try:
        run_payload = AlgorithmRunCreate(**json.loads(payload))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="payload 必须是合法 JSON") from exc
    form = await request.form()
    input_asset_uploads: dict[str, dict[str, object]] = {}
    for key, value in form.multi_items():
        if key == "payload":
            continue
        if hasattr(value, "filename") and hasattr(value, "read"):
            content = await value.read(MAX_MULTIPART_ASSET_BYTES + 1)
            if len(content) > MAX_MULTIPART_ASSET_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail={
                        "code": "INPUT_ASSET_TOO_LARGE",
                        "message": f"输入文件 {key} 超过平台上传上限",
                        "details": {"asset_key": key, "max_size_bytes": MAX_MULTIPART_ASSET_BYTES},
                    },
                )
            input_asset_uploads[key] = {
                "filename": value.filename or key,
                "content": content,
                "content_type": value.content_type or "application/octet-stream",
            }
    data = service.create_algorithm_run(
        run_payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
        input_asset_uploads=input_asset_uploads,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/algorithm-runs/{run_id}/artifacts", response_model=ApiResponse[ArtifactListResponseData])
def list_algorithm_run_artifacts(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ArtifactListResponseData]:
    """查询 AlgorithmRun 关联文件产物。"""
    artifacts = artifact_service.list_owner_artifacts(
        owner_type="algorithm_run",
        owner_id=run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(
        code=0,
        message="ok",
        data=ArtifactListResponseData(items=[_public_artifact(item) for item in artifacts]),
    )


@router.get("/algorithm-runs", response_model=ApiResponse[AlgorithmRunListData])
def list_algorithm_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    workflow_run_id: str | None = Query(default=None),
    algorithm_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    trigger_source: str | None = Query(default=None),
    research_run_id: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRunListData]:
    """查询 AlgorithmRun 列表。

    支持按 ProblemSpec、Campaign、算法、状态、触发来源、ResearchRun 过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_algorithm_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            workflow_run_id=workflow_run_id,
            algorithm_id=algorithm_id,
            status=status,
            trigger_source=trigger_source,
            research_run_id=research_run_id,
            created_by=None if _is_admin(current_user) else _access_user_id(current_user),
            page=page,
            page_size=page_size,
        ),
    )


@router.get("/algorithm-runs/{run_id}", response_model=ApiResponse[AlgorithmRun])
def get_algorithm_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRun]:
    """获取 AlgorithmRun 详情。

    响应包含 input_snapshot、output_summary、artifact_refs、错误信息和审计事件引用。
    """
    data = service.get_algorithm_run(
        run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ResearchRun API
# =============================================================================


@router.post("/research-runs", response_model=ApiResponse[ResearchRun])
def create_research_run(
    payload: ResearchRunCreate,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """创建 ResearchRun 草稿。

    基于 ProblemSpec 创建 AutoResearch 运行，自动生成默认阶段序列。
    创建后状态为 draft，需要调用 start 端点启动。
    """
    data = orchestrator.create_research_run(
        problem_spec_id=payload.problem_spec_id,
        execution_decision_id=payload.execution_decision_id,
        campaign_id=payload.campaign_id,
        profile_id=payload.profile_id,
        max_iterations=payload.max_iterations,
        batch_size=payload.batch_size,
        description=payload.description,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/research-runs", response_model=ApiResponse[ResearchRunListData])
def list_research_runs(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    problem_spec_id: str | None = Query(default=None),
    campaign_id: str | None = Query(default=None),
    status: str | None = Query(default=None),
    project_id: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRunListData]:
    """查询 ResearchRun 列表。

    支持按 ProblemSpec、Campaign、状态、项目过滤和分页。
    """
    return ApiResponse(
        code=0,
        message="ok",
        data=orchestrator.list_research_runs(
            problem_spec_id=problem_spec_id,
            campaign_id=campaign_id,
            status=status,
            created_by=None if _is_admin(current_user) else _access_user_id(current_user),
            project_id=project_id,
            page=page,
            page_size=page_size,
        ),
    )


@router.post("/research-runs/{run_id}:archive", response_model=ApiResponse[ResearchRun])
def archive_research_run(
    run_id: str,
    request: Request,
    payload: ArchiveRequest | None = None,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """归档 ResearchRun，默认列表隐藏但保留阶段和追溯链。"""
    data = orchestrator.archive_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason if payload else "用户归档 AutoResearch 运行",
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/research-runs/{run_id}", response_model=ApiResponse[ResearchRun])
def get_research_run(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """获取 ResearchRun 详情。

    包含完整阶段序列、当前阶段状态、gate 审批记录和 checkpoint 信息。
    """
    data = orchestrator.get_research_run(
        run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# ResearchRun 状态操作 API
# =============================================================================


@router.post("/research-runs/{run_id}/start", response_model=ApiResponse[ResearchRun])
def start_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """启动 ResearchRun。

    从 draft 状态转为 running，自动推进非 gate 阶段。
    gate 阶段（PROBLEM_SPEC、RECOMMENDATION_ASK、EXPERIMENT_EXECUTION）
    进入 blocked_approval 等待人工审批。
    """
    data = orchestrator.start_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/advance", response_model=ApiResponse[ResearchRun])
def advance_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """继续推进 ResearchRun 阶段。

    从 blocked_approval 或 paused 恢复后继续推进后续阶段。
    """
    data = orchestrator.advance_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/pause", response_model=ApiResponse[ResearchRun])
def pause_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """暂停 ResearchRun。

    running 或 blocked_approval 状态的运行可暂停，暂停前保存 checkpoint。
    """
    data = orchestrator.pause_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/resume", response_model=ApiResponse[ResearchRun])
def resume_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """恢复 ResearchRun。

    paused 状态的运行可恢复，恢复后继续推进后续阶段。
    """
    data = orchestrator.resume_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/research-runs/{run_id}/fail", response_model=ApiResponse[ResearchRun])
def fail_research_run(
    run_id: str,
    payload: ResearchRunStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """手动标记 ResearchRun 为失败。

    任何非终态的运行都可标记为失败。
    """
    data = orchestrator.fail_research_run(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# Stage/Gate 审批 API
# =============================================================================


@router.post(
    "/research-runs/{run_id}/stages/{stage_run_id}/approve",
    response_model=ApiResponse[ResearchRun],
)
def approve_stage(
    run_id: str,
    stage_run_id: str,
    payload: StageApprovalRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """批准 gate 阶段。

    批准后 ResearchRun 从 blocked_approval 转为 running 并继续推进后续阶段。
    决策必须包含 reason（审批原因）。
    """
    data = orchestrator.approve_stage(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/research-runs/{run_id}/stages/{stage_run_id}/reject",
    response_model=ApiResponse[ResearchRun],
)
def reject_stage(
    run_id: str,
    stage_run_id: str,
    payload: StageApprovalRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRun]:
    """拒绝 gate 阶段。

    拒绝后 StageRun 和 ResearchRun 标记为 failed。
    决策必须包含 reason（拒绝原因）。
    """
    data = orchestrator.reject_stage(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_has_full_access(current_user),
        reason=payload.reason,
        request_id=_request_id(request),
    )
    return ApiResponse(code=0, message="ok", data=data)


# =============================================================================
# Traceability 追溯 API
# =============================================================================


@router.get("/audit", response_model=ApiResponse[EntityAuditListData])
def query_audit_events(
    entity_type: str | None = Query(default=None, description="实体类型: problem_spec/algorithm_run/research_run/research_stage_run"),
    entity_id: str | None = Query(default=None, description="实体 ID"),
    event_type: str | None = Query(default=None, description="事件类型: created/completed/failed/approved/rejected"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[EntityAuditListData]:
    """查询审计事件。

    按实体类型和 ID 聚合关键审计事件，支持分页。
    返回内容已脱敏，不暴露本地敏感绝对路径或 secret。
    """
    data = service.query_audit_events(
        entity_type=entity_type,
        entity_id=entity_id,
        event_type=event_type,
        page=page,
        page_size=page_size,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/algorithm-runs/{run_id}/traceability",
    response_model=ApiResponse[AlgorithmRunTraceability],
)
def get_algorithm_run_traceability(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[AlgorithmRunTraceability]:
    """获取 AlgorithmRun 完整追溯链。

    聚合算法运行记录、自有 artifact、关联计算任务产物和审计事件。
    """
    data = service.get_algorithm_run_traceability(
        run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/research-runs/{run_id}/traceability",
    response_model=ApiResponse[ResearchRunTraceability],
)
def get_research_run_traceability(
    run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ResearchRunTraceability]:
    """获取 ResearchRun 完整追溯链。

    聚合 AutoResearch 运行记录、阶段时间线、关联算法运行、
    关联计算任务、关联观测和所有审计事件。
    """
    data = service.get_research_run_traceability(
        run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/research-runs/{run_id}/stages/{stage_run_id}/traceability",
    response_model=ApiResponse[StageRunTraceability],
)
def get_stage_run_traceability(
    run_id: str,
    stage_run_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[StageRunTraceability]:
    """获取 StageRun 完整追溯链。

    聚合单个阶段的输入输出、关联算法运行和审计事件。
    """
    data = service.get_stage_run_traceability(
        research_run_id=run_id,
        stage_run_id=stage_run_id,
        actor_user_id=_access_user_id(current_user),
        is_admin=_has_full_access(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)
