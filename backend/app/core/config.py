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

        # ALchemist 主动学习工具后端地址
        self.alchemist_backend_url: str = os.getenv(
            "ALCHEMIST_BACKEND_URL", "http://127.0.0.1:8004/api/v1"
        )

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
        return f"mongodb://{credential}{self.mongodb_host}:{self.mongodb_port}"


settings = Settings()
