"""优化 campaign API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.optimization import (
    CampaignHistoryData,
    CampaignCreateRequest,
    CampaignDetailData,
    CampaignListData,
    CampaignStatusChangeRequest,
    CandidateImportData,
    CandidateImportCsvRequest,
    CandidateImportRequest,
    CreateObservationFromComputationData,
    ObservationCreateRequest,
    OptimizationCampaign,
    OptimizationObservation,
    OptimizationSuggestion,
    SubmitSuggestionComputationData,
    SuggestionFailureRequest,
    SuggestionRejectRequest,
    SuggestionCreateData,
    SuggestionCreateRequest,
)
from app.services.optimization_service import OptimizationService


router = APIRouter(prefix="/optimization", tags=["optimization"])
service = OptimizationService()


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    """解析当前操作人。"""
    return current_user["user_id"] if current_user else "demo_user"


def _access_user_id(current_user: dict[str, str] | None) -> str | None:
    """解析用于数据权限过滤的用户 ID。"""
    return current_user["user_id"] if current_user else None


def _is_admin(current_user: dict[str, str] | None) -> bool:
    """判断当前用户是否管理员。"""
    return bool(current_user and current_user.get("role") == "admin")


def _request_id(request: Request) -> str | None:
    """读取请求追踪 ID。"""
    return getattr(request.state, "request_id", None) or request.headers.get("x-request-id")


@router.post("/campaigns", response_model=ApiResponse[OptimizationCampaign])
def create_campaign(
    payload: CampaignCreateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """创建 campaign。"""
    data = service.create_campaign(payload, actor_user_id=_actor_user_id(current_user), request_id=_request_id(request))
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/campaigns", response_model=ApiResponse[CampaignListData])
def list_campaigns(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CampaignListData]:
    """查询 campaign 列表。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.list_campaigns(
            page=page,
            page_size=page_size,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/campaigns/{campaign_id}", response_model=ApiResponse[CampaignDetailData])
def get_campaign(
    campaign_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CampaignDetailData]:
    """查询 campaign 详情。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_detail(
            campaign_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.get("/campaigns/{campaign_id}/history", response_model=ApiResponse[CampaignHistoryData])
def get_campaign_history(
    campaign_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CampaignHistoryData]:
    """查询 campaign 可追踪历史。"""
    return ApiResponse(
        code=0,
        message="ok",
        data=service.get_history(
            campaign_id,
            actor_user_id=_access_user_id(current_user),
            is_admin=_is_admin(current_user),
        ),
    )


@router.post("/campaigns/{campaign_id}:pause", response_model=ApiResponse[OptimizationCampaign])
def pause_campaign(
    campaign_id: str,
    payload: CampaignStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """暂停 campaign。"""
    data = service.change_campaign_status(
        campaign_id,
        "paused",
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}:resume", response_model=ApiResponse[OptimizationCampaign])
def resume_campaign(
    campaign_id: str,
    payload: CampaignStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """恢复 campaign。"""
    data = service.change_campaign_status(
        campaign_id,
        "running",
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}:archive", response_model=ApiResponse[OptimizationCampaign])
def archive_campaign(
    campaign_id: str,
    payload: CampaignStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """归档 campaign。"""
    data = service.change_campaign_status(
        campaign_id,
        "archived",
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}:complete", response_model=ApiResponse[OptimizationCampaign])
def complete_campaign(
    campaign_id: str,
    payload: CampaignStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """完成 campaign。"""
    data = service.change_campaign_status(
        campaign_id,
        "completed",
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}:fail", response_model=ApiResponse[OptimizationCampaign])
def fail_campaign(
    campaign_id: str,
    payload: CampaignStatusChangeRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationCampaign]:
    """标记 campaign 失败。"""
    data = service.change_campaign_status(
        campaign_id,
        "failed",
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}/candidates:import", response_model=ApiResponse[CandidateImportData])
def import_campaign_candidates(
    campaign_id: str,
    payload: CandidateImportRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CandidateImportData]:
    """导入候选分子。"""
    data = service.import_candidates(
        campaign_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}/candidates:import-csv", response_model=ApiResponse[CandidateImportData])
async def import_campaign_candidates_csv(
    campaign_id: str,
    request: Request,
    file: UploadFile | None = File(default=None),
    csv_text: str | None = Form(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CandidateImportData]:
    """从 CSV 文件或 CSV 文本导入候选分子。"""
    text = csv_text
    if file is not None:
        raw = await file.read()
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise HTTPException(status_code=400, detail="CSV 文件必须是 UTF-8 文本") from exc
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="请提供 CSV 文件或 CSV 文本")
    data = service.import_candidates_csv(
        campaign_id,
        CandidateImportCsvRequest(csv_text=text),
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}/suggestions", response_model=ApiResponse[SuggestionCreateData])
def generate_suggestions(
    campaign_id: str,
    payload: SuggestionCreateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[SuggestionCreateData]:
    """生成推荐。"""
    data = service.generate_suggestions(
        campaign_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}/observations", response_model=ApiResponse[OptimizationObservation])
def create_observation(
    campaign_id: str,
    payload: ObservationCreateRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationObservation]:
    """写入 observation。"""
    data = service.create_observation(
        campaign_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/computations/{run_id}/create-observation", response_model=ApiResponse[CreateObservationFromComputationData])
def create_observation_from_computation(
    run_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CreateObservationFromComputationData]:
    """从 completed computation 生成 observation。"""
    data = service.create_observation_from_computation(
        run_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/suggestions/{suggestion_id}/submit-computation", response_model=ApiResponse[SubmitSuggestionComputationData])
def submit_suggestion_computation(
    suggestion_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[SubmitSuggestionComputationData]:
    """将推荐转为计算任务。"""
    data = service.submit_suggestion_computation(
        suggestion_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/suggestions/{suggestion_id}/reject", response_model=ApiResponse[OptimizationSuggestion])
def reject_suggestion(
    suggestion_id: str,
    payload: SuggestionRejectRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationSuggestion]:
    """拒绝推荐。"""
    data = service.reject_suggestion(
        suggestion_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/suggestions/{suggestion_id}/failed", response_model=ApiResponse[OptimizationSuggestion])
def mark_suggestion_failed(
    suggestion_id: str,
    payload: SuggestionFailureRequest,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[OptimizationSuggestion]:
    """标记推荐失败。"""
    data = service.mark_suggestion_failed(
        suggestion_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)
