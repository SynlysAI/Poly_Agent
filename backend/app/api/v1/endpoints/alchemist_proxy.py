"""ALchemist 实验设计与优化工具代理路由。

将 /api/v1/alchemist/* 的请求通过 httpx 转发到 ALchemist 后端（127.0.0.1:8004）。
转发前通过 Poly_Agent 认证校验，确保只有已登录用户可访问。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi import WebSocket
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse

import httpx

from app.core.auth import get_current_user
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("poly_agent.alchemist_proxy")

router = APIRouter(tags=["ALchemist 主动学习工具"])

ALCHEMIST_BACKEND_URL = getattr(settings, "alchemist_backend_url", "http://127.0.0.1:8004/api/v1")
_CLIENT: httpx.AsyncClient | None = None
HOP_BY_HOP_HEADERS = {
    "connection",
    "content-encoding",
    "content-length",
    "host",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}


def _get_client() -> httpx.AsyncClient:
    """获取或创建用于代理转发的 httpx 异步客户端。

    Returns:
        配置了 ALchemist 后端基准 URL 的异步 HTTP 客户端。
    """
    global _CLIENT
    if _CLIENT is None:
        _CLIENT = httpx.AsyncClient(
            base_url=ALCHEMIST_BACKEND_URL,
            timeout=httpx.Timeout(120.0),
        )
    return _CLIENT


def _filter_headers(headers: httpx.Headers | dict[str, str]) -> dict[str, str]:
    """过滤不应由代理透传的逐跳头部。

    Args:
        headers: 原始请求或响应头。

    Returns:
        可安全转发的头部字典。
    """
    return {
        key: value
        for key, value in dict(headers).items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


@router.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"])
async def proxy_alchemist_request(
    path: str,
    request: Request,
    current_user: dict | None = Depends(get_current_user),
):
    """代理转发 HTTP 请求到 ALchemist 后端。

    Args:
        path: ALchemist API 的相对路径。
        request: 原始请求对象。
        current_user: 当前登录用户（由认证中间件注入）。

    Returns:
        ALchemist 后端的原始响应。
    """
    client = _get_client()

    # 读取请求体
    body = await request.body()

    # 构建转发请求头，移除逐跳头部
    headers = _filter_headers(request.headers)

    logger.info(
        f"代理转发请求: {request.method} /alchemist/{path}",
        extra={"user": current_user.get("username") if current_user else "anonymous"},
    )

    try:
        response = await client.request(
            method=request.method,
            url=path,
            headers=headers,
            params=request.query_params,
            content=body,
        )
    except httpx.ConnectError:
        logger.error("无法连接到 ALchemist 后端，请确认 ALchemist 服务已启动")
        raise HTTPException(
            status_code=503,
            detail="ALchemist 服务未启动，请先启动 ALchemist 后端服务",
        )
    except httpx.TimeoutException:
        logger.error("ALchemist 后端请求超时")
        raise HTTPException(status_code=504, detail="ALchemist 服务响应超时")

    # 构建返回头，移除逐跳头部
    response_headers = _filter_headers(response.headers)
    content_type = response.headers.get("content-type", "")

    if response.content and "application/json" in content_type:
        return JSONResponse(
            content=response.json(),
            status_code=response.status_code,
            headers=response_headers,
        )

    if not response.content:
        return Response(status_code=response.status_code, headers=response_headers)

    return StreamingResponse(
        iter([response.content]),
        status_code=response.status_code,
        headers=response_headers,
        media_type=content_type or None,
    )
