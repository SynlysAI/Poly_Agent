"""Assistant provider 调用错误的结构化分类。"""

from __future__ import annotations

from typing import Any


MODEL_TOOL_CAPABILITY_UNAVAILABLE = "MODEL_TOOL_CAPABILITY_UNAVAILABLE"
PROVIDER_AUTH_FAILED = "PROVIDER_AUTH_FAILED"
PROVIDER_TIMEOUT = "PROVIDER_TIMEOUT"
MODEL_NOT_FOUND = "MODEL_NOT_FOUND"
TOOL_PROTOCOL_ERROR = "TOOL_PROTOCOL_ERROR"
TOOL_ARGUMENTS_INVALID = "TOOL_ARGUMENTS_INVALID"
UNKNOWN_TOOL_NAME = "UNKNOWN_TOOL_NAME"
PROVIDER_REQUEST_FAILED = "PROVIDER_REQUEST_FAILED"


def classify_provider_error(exc: Exception) -> dict[str, Any]:
    """将 provider 异常映射为稳定的错误码与用户可读信息。

    Args:
        exc: OpenAI 兼容客户端或网关抛出的异常。

    Returns:
        包含 code、message 和原始异常类名的结构化错误。
    """
    class_name = type(exc).__name__
    message = str(exc) or class_name
    status_code = getattr(exc, "status_code", None)
    lowered = message.lower()

    if "authentication" in class_name.lower() or status_code in {401, 403}:
        code = PROVIDER_AUTH_FAILED
        display = "模型服务鉴权失败，请检查 API Key 或 provider 配置。"
    elif "timeout" in class_name.lower() or "timed out" in lowered:
        code = PROVIDER_TIMEOUT
        display = "模型服务响应超时，请稍后重试。"
    elif "notfound" in class_name.lower() or (status_code == 404 and "model" in lowered):
        code = MODEL_NOT_FOUND
        display = "模型服务未找到指定模型，请检查路由配置。"
    elif (
        "badrequest" in class_name.lower()
        or (
            status_code == 400
            and any(token in lowered for token in ("tool", "function", "schema"))
        )
    ):
        code = TOOL_PROTOCOL_ERROR
        display = "模型服务拒绝当前工具协议，请检查模型 tool calling 配置。"
    else:
        code = PROVIDER_REQUEST_FAILED
        display = "模型服务请求失败，请稍后重试。"

    return {
        "code": code,
        "message": display,
        "provider_exception": class_name,
    }
