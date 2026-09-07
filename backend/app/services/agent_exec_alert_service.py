"""Agent 连接器外部告警服务。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import settings
from app.core.time import utc_now


LOGGER = logging.getLogger(__name__)


class AgentExecAlertService:
    """把关键 agent_exec 异常转发到日志或可选 webhook。"""

    @staticmethod
    def emit(
        *,
        level: str,
        title: str,
        reasons: list[str],
        context: dict[str, Any],
    ) -> None:
        """发送结构化告警，失败时不影响业务 run。

        Args:
            level: none / warning / critical 级别。
            title: 告警标题。
            reasons: 告警原因列表。
            context: 不含 secret 的上下文。
        """
        if level not in {"warning", "critical"}:
            return
        payload = {
            "source": "poly_agent.agent_exec",
            "level": level,
            "title": title,
            "reasons": reasons,
            "context": context,
            "created_at": utc_now().isoformat(),
        }
        log_method = LOGGER.critical if level == "critical" else LOGGER.warning
        log_method("agent_exec alert: %s %s %s", title, reasons, context)
        webhook = settings.agent_exec_alert_webhook_url
        if not webhook:
            return
        try:
            response = httpx.post(webhook, json=payload, timeout=3)
            response.raise_for_status()
        except Exception:
            LOGGER.exception("agent_exec alert webhook failed")
