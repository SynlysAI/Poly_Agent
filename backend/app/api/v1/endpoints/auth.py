"""认证接口。"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException

from app.core.auth import get_current_user_optional
from app.core.auth import resolve_authenticated_username
from app.core.config import settings
from app.core.logging import get_logger
from app.schemas.auth import AuthStatusData
from app.schemas.auth import CurrentUserData
from app.schemas.auth import LoginData
from app.schemas.auth import LoginRequest
from app.schemas.auth import RegisterRequest
from app.schemas.common import ApiResponse
from app.services.auth_service import AuthService

logger = get_logger("poly_agent.api.auth")

router = APIRouter(prefix="/auth", tags=["auth"])
auth_service = AuthService()


@router.get("/status", response_model=ApiResponse[AuthStatusData])
def get_auth_status(authorization: str | None = Header(default=None)) -> ApiResponse[AuthStatusData]:
    """获取当前服务登录开关与会话状态。

    Args:
        authorization: 请求头中的 Authorization 值。

    Returns:
        当前登录配置与认证状态。
    """
    username: str | None = None
    authenticated = False
    if settings.auth_enabled and authorization:
        try:
            username = resolve_authenticated_username(authorization)
            authenticated = bool(username)
        except HTTPException:
            authenticated = False
            username = None

    data = AuthStatusData(
        auth_enabled=settings.auth_enabled,
        authenticated=authenticated,
        username=username,
    )
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/login", response_model=ApiResponse[LoginData])
def login(payload: LoginRequest) -> ApiResponse[LoginData]:
    """执行用户账号密码登录。

    Args:
        payload: 登录请求参数。

    Returns:
        登录成功后的令牌与会话信息。
    """
    if not settings.auth_enabled:
        logger.warning("登录失败：当前服务未启用登录校验")
        raise HTTPException(status_code=400, detail="当前服务未启用登录校验")
    try:
        data = auth_service.login(
            username=payload.username.strip(),
            password=payload.password,
        )
    except ValueError as exc:
        logger.warning("登录失败：%s，用户名=%s", str(exc), payload.username)
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return ApiResponse(code=0, message="ok", data=data)


@router.post("/register", response_model=ApiResponse[CurrentUserData])
def register(payload: RegisterRequest) -> ApiResponse[CurrentUserData]:
    """执行邀请码注册。

    Args:
        payload: 注册请求参数。

    Returns:
        注册成功后的当前用户信息。
    """
    if not settings.auth_enabled:
        logger.warning("注册失败：当前服务未启用登录校验")
        raise HTTPException(status_code=400, detail="当前服务未启用登录校验")
    invite_code = payload.invite_code.strip()
    username = payload.username.strip()
    if not invite_code:
        raise HTTPException(status_code=400, detail="邀请码不能为空")
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    try:
        user = auth_service.register(
            invite_code=invite_code,
            username=username,
            password=payload.password,
            real_name=(payload.real_name.strip() or None) if payload.real_name else None,
            organization=(payload.organization.strip() or None) if payload.organization else None,
        )
    except ValueError as exc:
        logger.warning("注册失败：%s，用户名=%s", str(exc), payload.username)
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ApiResponse(
        code=0,
        message="ok",
        data=CurrentUserData(
            auth_enabled=True,
            authenticated=True,
            user_id=user.user_id,
            username=user.username,
            role=user.role,
            status=user.status,
        ),
    )


@router.get("/me", response_model=ApiResponse[CurrentUserData])
def get_current_user_profile(
    current_user: dict[str, str] | None = Depends(get_current_user_optional),
) -> ApiResponse[CurrentUserData]:
    """获取当前登录用户信息。

    Args:
        current_user: 当前登录用户信息。

    Returns:
        当前用户信息；未登录时返回匿名状态。
    """
    if not current_user:
        return ApiResponse(
            code=0,
            message="ok",
            data=CurrentUserData(auth_enabled=settings.auth_enabled, authenticated=False),
        )
    return ApiResponse(
        code=0,
        message="ok",
        data=CurrentUserData(
            auth_enabled=True,
            authenticated=True,
            user_id=current_user["user_id"],
            username=current_user["username"],
            role=current_user["role"],
            status=current_user["status"],
        ),
    )
