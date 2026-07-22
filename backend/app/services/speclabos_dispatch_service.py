"""SpecLabOS 外部实验任务下发服务。"""

from typing import Any

import httpx

from app.core.config import settings


class SpecLabOSDispatchError(Exception):
    """SpecLabOS 下发失败错误。"""


class SpecLabOSDispatchService:
    """负责将标准化实验批次发送到 SpecLabOS。"""

    @staticmethod
    def dispatch(payload: dict[str, Any]) -> dict[str, str]:
        """下发外部实验任务批次。

        Args:
            payload: 符合 SpecLabOS 外部实验任务契约的请求体。

        Returns:
            SpecLabOS 返回的批次标识、状态和接收时间。

        Raises:
            SpecLabOSDispatchError: 配置错误或远程服务调用失败时抛出。
        """
        if not settings.speclabos_base_url:
            raise SpecLabOSDispatchError("未配置 SPECLABOS_BASE_URL，无法下发实验任务")
        if not settings.speclabos_api_key:
            raise SpecLabOSDispatchError("未配置 SPECLABOS_API_KEY，无法下发实验任务")

        try:
            response = httpx.post(
                f"{settings.speclabos_base_url}/api/external-experiment-dispatches",
                json=payload,
                headers={"Authorization": f"Bearer {settings.speclabos_api_key}"},
                timeout=settings.speclabos_timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
        except httpx.TimeoutException as exc:
            raise SpecLabOSDispatchError("SpecLabOS 响应超时，请稍后重试") from exc
        except httpx.RequestError as exc:
            raise SpecLabOSDispatchError("无法连接 SpecLabOS，请检查服务地址和网络") from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            message = f"SpecLabOS 下发失败（HTTP {exc.response.status_code}）"
            if detail:
                message = f"{message}: {detail[:300]}"
            raise SpecLabOSDispatchError(message) from exc
        except ValueError as exc:
            raise SpecLabOSDispatchError("SpecLabOS 返回了无法解析的响应") from exc

        required_fields = ("dispatch_id", "status", "received_at")
        if not isinstance(data, dict) or any(not data.get(field) for field in required_fields):
            raise SpecLabOSDispatchError("SpecLabOS 返回的任务接收结果不完整")

        return {
            "dispatch_id": str(data["dispatch_id"]),
            "status": str(data["status"]),
            "received_at": str(data["received_at"]),
        }


speclabos_dispatch_service = SpecLabOSDispatchService()
