"""应用配置模块。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")


class Settings:
    """配置对象。"""

    def __init__(self) -> None:
        self.project_root: Path = Path(__file__).resolve().parents[3]
        self.backend_root: Path = self.project_root / "backend"
        self.runtime_root: Path = self._resolve_project_path(
            os.getenv("POLY_AGENT_RUNTIME_ROOT", str(self.project_root / ".runtime"))
        )
        self.upload_root: Path = self._resolve_project_path(
            os.getenv("POLY_AGENT_UPLOAD_ROOT", str(self.runtime_root / "uploads"))
        )
        self.outputs_root: Path = self._resolve_project_path(
            os.getenv("POLY_AGENT_OUTPUT_ROOT", str(self.runtime_root / "outputs"))
        )
        self.logs_root: Path = self._resolve_project_path(
            os.getenv("POLY_AGENT_LOG_ROOT", str(self.runtime_root / "logs"))
        )
        self.orca_execution_mode: str = os.getenv(
            "ORCA_EXECUTION_MODE",
            os.getenv("ORCA_COMPUTE_ENGINE_EXECUTION_MODE", "disabled"),
        ).strip().lower()
        self.orca_compute_engine_execution_mode: str = self.orca_execution_mode
        self.orca_license_available: bool = os.getenv("ORCA_LICENSE_AVAILABLE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.hpc_queue_available: bool = os.getenv("HPC_QUEUE_AVAILABLE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.hpc_queue_name: str = os.getenv("HPC_QUEUE_NAME", "default")
        self.crest_executable: str = os.getenv("CREST_EXECUTABLE", "crest").strip() or "crest"
        self.xtb_executable: str = os.getenv("XTB_EXECUTABLE", "xtb").strip() or "xtb"
        self.orca_executable: str = os.getenv("ORCA_EXECUTABLE", "orca").strip() or "orca"
        self.max_upload_size_mb: int = 100
        self.api_prefix: str = "/api/v1"
        self.app_env: str = os.getenv("APP_ENV", "dev")
        self.auth_enabled: bool = os.getenv("AUTH_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.auth_username: str = os.getenv("AUTH_USERNAME", "admin")
        self.auth_password: str = os.getenv("AUTH_PASSWORD", "admin123456")
        self.auth_secret: str = os.getenv("AUTH_SECRET", "")
        self.auth_token_expire_hours: int = int(os.getenv("AUTH_TOKEN_EXPIRE_HOURS", "12"))
        self.auth_bootstrap_enabled: bool = os.getenv("AUTH_BOOTSTRAP_ENABLED", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.auth_invite_default_hours: int = int(os.getenv("AUTH_INVITE_DEFAULT_HOURS", "72"))

        # MongoDB 配置
        self.mongodb_host: str = os.getenv("MONGODB_HOST", "127.0.0.1")
        self.mongodb_port: int = int(os.getenv("MONGODB_PORT", "27017"))
        self.mongodb_username: str = os.getenv("MONGODB_USERNAME", "")
        self.mongodb_password: str = os.getenv("MONGODB_PASSWORD", "")
        self.mongodb_database: str = os.getenv("MONGODB_DATABASE", "poly_agent")
        self.mongodb_auth_source: str = os.getenv("MONGODB_AUTH_SOURCE", "admin")
        self.require_mongodb: bool = os.getenv("REQUIRE_MONGODB", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # Stale-run reaper 配置
        self.stale_run_heartbeat_seconds: int = int(os.getenv("STALE_RUN_HEARTBEAT_SECONDS", "60"))
        # running 任务的 heartbeat 超过此秒数未更新则判定为过期
        # 必须 > heartbeat 间隔（5s）；60s 提供 12 个 heartbeat 周期的容错
        self.stale_run_wallclock_safety_factor: float = float(
            os.getenv("STALE_RUN_WALLCLOCK_SAFETY_FACTOR", "3.0")
        )
        # 整体 wallclock 超时 = max_wallclock_seconds * safety_factor
        # 默认 1800s max_wallclock × 3.0 = 90 分钟后强制失败
        self.stale_reaper_interval_seconds: int = int(os.getenv("STALE_REAPER_INTERVAL_SECONDS", "60"))
        # 后台 reaper 任务运行间隔

        # ALchemist 主动学习工具后端地址
        self.alchemist_backend_url: str = os.getenv(
            "ALCHEMIST_BACKEND_URL", "http://127.0.0.1:8004/api/v1"
        )

        # LLM 配置（仅从环境变量读取，无默认值）
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "")

        # 统一认证（AI4MS）数据库配置
        self.auth_mongodb_uri: str = os.getenv("AUTH_MONGODB_URI", "")
        self.auth_database: str = os.getenv("AUTH_MONGODB_DATABASE", "ai4ms")

        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def _resolve_project_path(self, raw_path: str) -> Path:
        """按项目根目录解析路径配置。

        Args:
            raw_path: 环境变量中的原始路径值。

        Returns:
            解析后的绝对路径对象。
        """
        target_path = Path(str(raw_path)).expanduser()
        if target_path.is_absolute():
            return target_path
        return (self.project_root / target_path).resolve()

    @property
    def mongodb_uri(self) -> str:
        """生成 MongoDB 连接 URI。"""
        credential = ""
        if self.mongodb_username:
            credential = self.mongodb_username
            if self.mongodb_password:
                credential = f"{credential}:{self.mongodb_password}"
            credential = f"{credential}@"
        uri = f"mongodb://{credential}{self.mongodb_host}:{self.mongodb_port}"
        if self.mongodb_auth_source:
            uri = f"{uri}/?authSource={self.mongodb_auth_source}"
        return uri


settings = Settings()
