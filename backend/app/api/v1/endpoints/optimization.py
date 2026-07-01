"""优化 campaign API。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.optimization import (
    CampaignHistoryData,
    CampaignCreateRequest,
    CampaignDetailData,
    CampaignListData,
    CandidateImportData,
    CandidateImportRequest,
    CreateObservationFromComputationData,
    ObservationCreateRequest,
    OptimizationCampaign,
    OptimizationObservation,
    SubmitSuggestionComputationData,
    SuggestionCreateData,
    SuggestionCreateRequest,
)
from app.services.optimization_service import OptimizationService


router = APIRouter(prefix="/optimization", tags=["optimization"])
service = OptimizationService()


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    """解析当前操作人。"""
    return current_user["user_id"] if current_user else "demo_user"


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
) -> ApiResponse[CampaignListData]:
    """查询 campaign 列表。"""
    return ApiResponse(code=0, message="ok", data=service.list_campaigns(page=page, page_size=page_size))


@router.get("/campaigns/{campaign_id}", response_model=ApiResponse[CampaignDetailData])
def get_campaign(campaign_id: str) -> ApiResponse[CampaignDetailData]:
    """查询 campaign 详情。"""
    return ApiResponse(code=0, message="ok", data=service.get_detail(campaign_id))


@router.get("/campaigns/{campaign_id}/history", response_model=ApiResponse[CampaignHistoryData])
def get_campaign_history(campaign_id: str) -> ApiResponse[CampaignHistoryData]:
    """查询 campaign 可追踪历史。"""
    return ApiResponse(code=0, message="ok", data=service.get_history(campaign_id))


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
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/campaigns/{campaign_id}/candidates:import-chemos-demo", response_model=ApiResponse[CandidateImportData])
def import_chemos_demo_candidates(
    campaign_id: str,
    request: Request,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[CandidateImportData]:
    """导入 ChemOS reference demo 候选。"""
    data = service.import_chemos_demo_candidates(
        campaign_id,
        actor_user_id=_actor_user_id(current_user),
        request_id=_request_id(request),
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
    )
    return ApiResponse(code=0, message="ok", data=data)
    CreateObservationFromComputationData,
