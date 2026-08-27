"""实验方案转发台 API。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from fastapi.encoders import jsonable_encoder

from app.core.auth import get_current_user
from app.schemas.common import ApiResponse
from app.schemas.experiment_dispatch import (
    ExperimentDispatchBuildRequest,
    ExperimentDispatchListData,
    ExperimentDispatchManifest,
    ExperimentTemplateListData,
)
from app.schemas.experiment_dispatch_profile import (
    DispatchTargetDefinition,
    DispatchTargetListData,
    ExperimentDispatchNLParseRequest,
    NLDispatchParseResult,
    ExperimentDispatchCandidateListData,
    ExperimentDispatchProfile,
    ExperimentDispatchProfileCloneRequest,
    ExperimentDispatchProfileCreateRequest,
    ExperimentDispatchProfileEvaluation,
    ExperimentDispatchProfileEvaluationRequest,
    ExperimentDispatchProfileListData,
    ExperimentDispatchProfileSaveRequest,
    ExperimentDispatchProfileUpdateRequest,
    ExperimentDispatchProfileVisibilityRequest,
)
from app.services.experiment_dispatch_service import experiment_dispatch_service
from app.services.experiment_dispatch_profile_service import experiment_dispatch_profile_service


router = APIRouter(tags=["experiment-dispatch"])


def _actor_user_id(current_user: dict[str, str] | None) -> str:
    return current_user.get("user_id", "demo_user") if current_user else "demo_user"


def _is_admin(current_user: dict[str, str] | None) -> bool:
    return bool(current_user and current_user.get("role") == "admin")


@router.post(
    "/experiment-dispatch-nl-parses",
    response_model=ApiResponse[NLDispatchParseResult],
)
def parse_experiment_dispatch_natural_language(
    payload: ExperimentDispatchNLParseRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[NLDispatchParseResult]:
    """把自然语言实验条件解析为 manual_values 候选并写入审计。"""
    data = experiment_dispatch_profile_service.parse_natural_language(
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/experiment-dispatch-profiles", response_model=ApiResponse[ExperimentDispatchProfileListData])
def list_experiment_dispatch_profiles(
    status: str | None = Query(default=None),
    target_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfileListData]:
    data = experiment_dispatch_profile_service.list(
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
        status=status,
        target_id=target_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/experiment-dispatch-profiles", response_model=ApiResponse[ExperimentDispatchProfile])
def create_experiment_dispatch_profile(
    payload: ExperimentDispatchProfileCreateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.create(payload, actor_user_id=_actor_user_id(current_user))
    return ApiResponse(code=0, message="created", data=data)


@router.get("/experiment-dispatch-profiles/{profile_id}", response_model=ApiResponse[ExperimentDispatchProfile])
def get_experiment_dispatch_profile(
    profile_id: str,
    version: str | None = Query(default=None),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.get(
        profile_id,
        version,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.patch(
    "/experiment-dispatch-profiles/{profile_id}/versions/{version}",
    response_model=ApiResponse[ExperimentDispatchProfile],
)
def update_experiment_dispatch_profile(
    profile_id: str,
    version: str,
    payload: ExperimentDispatchProfileUpdateRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.update(
        profile_id, version, payload, actor_user_id=_actor_user_id(current_user)
    )
    return ApiResponse(code=0, message="updated", data=data)


@router.post(
    "/experiment-dispatch-profiles/{profile_id}/versions/{version}/publication",
    response_model=ApiResponse[ExperimentDispatchProfile],
)
def publish_experiment_dispatch_profile(
    profile_id: str,
    version: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.publish(
        profile_id, version, actor_user_id=_actor_user_id(current_user)
    )
    return ApiResponse(code=0, message="published", data=data)


@router.post(
    "/experiment-dispatch-profiles/{profile_id}/versions/{version}/copies",
    response_model=ApiResponse[ExperimentDispatchProfile],
)
def clone_experiment_dispatch_profile(
    profile_id: str,
    version: str,
    payload: ExperimentDispatchProfileCloneRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.clone_version(
        profile_id, version, payload.version, actor_user_id=_actor_user_id(current_user)
    )
    return ApiResponse(code=0, message="created", data=data)


@router.patch(
    "/experiment-dispatch-profiles/{profile_id}/versions/{version}/visibility",
    response_model=ApiResponse[ExperimentDispatchProfile],
)
def update_experiment_dispatch_profile_visibility(
    profile_id: str,
    version: str,
    payload: ExperimentDispatchProfileVisibilityRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfile]:
    data = experiment_dispatch_profile_service.set_visibility(
        profile_id, version, payload.visibility, actor_user_id=_actor_user_id(current_user)
    )
    return ApiResponse(code=0, message="updated", data=data)


@router.get("/experiment-dispatch-targets", response_model=ApiResponse[DispatchTargetListData])
def list_experiment_dispatch_targets() -> ApiResponse[DispatchTargetListData]:
    return ApiResponse(code=0, message="ok", data=experiment_dispatch_profile_service.list_targets())


@router.get("/experiment-dispatch-targets/{target_id}", response_model=ApiResponse[DispatchTargetDefinition])
def get_experiment_dispatch_target(
    target_id: str,
    version: str | None = Query(default=None),
) -> ApiResponse[DispatchTargetDefinition]:
    return ApiResponse(code=0, message="ok", data=experiment_dispatch_profile_service.get_target(target_id, version))


@router.get("/experiment-dispatch-candidates", response_model=ApiResponse[ExperimentDispatchCandidateListData])
def list_experiment_dispatch_candidates(
    trigger_source: str | None = Query(default=None),
    algorithm_type: str | None = Query(default=None),
    algorithm_family: str | None = Query(default=None),
    algorithm_id: str | None = Query(default=None),
    profile_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchCandidateListData]:
    data = experiment_dispatch_profile_service.list_candidates(
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
        trigger_source=trigger_source,
        algorithm_type=algorithm_type,
        algorithm_family=algorithm_family,
        algorithm_id=algorithm_id,
        profile_id=profile_id,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/experiment-dispatch-profile-evaluations",
    response_model=ApiResponse[ExperimentDispatchProfileEvaluation],
)
def evaluate_experiment_dispatch_profile(
    payload: ExperimentDispatchProfileEvaluationRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchProfileEvaluation]:
    data = experiment_dispatch_profile_service.evaluate(
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/experiment-dispatches", response_model=ApiResponse[ExperimentDispatchManifest])
def save_profile_experiment_dispatch(
    payload: ExperimentDispatchProfileSaveRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchManifest]:
    data = experiment_dispatch_profile_service.save_dispatch(
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="created", data=data)


@router.get("/experiment-templates", response_model=ApiResponse[ExperimentTemplateListData])
def list_experiment_templates() -> ApiResponse[ExperimentTemplateListData]:
    """列出仓库内可用的实验模板。"""
    return ApiResponse(code=0, message="ok", data=experiment_dispatch_service.list_templates())


@router.post(
    "/algorithm-runs/{run_id}/experiment-dispatches/preview",
    response_model=ApiResponse[ExperimentDispatchManifest],
)
def preview_experiment_dispatch(
    run_id: str,
    payload: ExperimentDispatchBuildRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchManifest]:
    """预览实验方案，不写入持久化集合。"""
    data = experiment_dispatch_service.preview(
        run_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post(
    "/algorithm-runs/{run_id}/experiment-dispatches",
    response_model=ApiResponse[ExperimentDispatchManifest],
)
def create_experiment_dispatch(
    run_id: str,
    payload: ExperimentDispatchBuildRequest,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchManifest]:
    """保存一份已生成的实验方案转发清单。"""
    data = experiment_dispatch_service.create(
        run_id,
        payload,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/experiment-dispatches", response_model=ApiResponse[ExperimentDispatchListData])
def list_experiment_dispatches(
    run_id: str | None = Query(default=None),
    template_id: str | None = Query(default=None),
    profile_id: str | None = Query(default=None),
    keyword: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchListData]:
    """分页查询当前用户可见的实验方案。"""
    data = experiment_dispatch_service.list(
        run_id=run_id,
        template_id=template_id,
        profile_id=profile_id,
        keyword=keyword,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
        page=page,
        page_size=page_size,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get(
    "/experiment-dispatches/{dispatch_id}",
    response_model=ApiResponse[ExperimentDispatchManifest],
)
def get_experiment_dispatch(
    dispatch_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> ApiResponse[ExperimentDispatchManifest]:
    """查询实验方案详情。"""
    data = experiment_dispatch_service.get(
        dispatch_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.get("/experiment-dispatches/{dispatch_id}/export")
def export_experiment_dispatch(
    dispatch_id: str,
    current_user: dict[str, str] | None = Depends(get_current_user),
) -> Response:
    """导出实验方案 JSON 清单。"""
    data = experiment_dispatch_service.get(
        dispatch_id,
        actor_user_id=_actor_user_id(current_user),
        is_admin=_is_admin(current_user),
    )
    content = json.dumps(jsonable_encoder(data), ensure_ascii=False, indent=2)
    return Response(
        content=content,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{dispatch_id}.json"'},
    )
