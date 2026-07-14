"""应用配置模块。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


BACKEND_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_ROOT / ".env")

LOCAL_APP_ENVS = {"dev", "development", "local", "test", "testing", "ci"}
DEFAULT_AUTH_USERNAME = "admin"
DEFAULT_AUTH_PASSWORD = "admin123456"
MIN_AUTH_SECRET_LENGTH = 32
DEFAULT_LOCAL_CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:5200",
    "http://localhost:5200",
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:5174",
    "http://localhost:5174",
]


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
        self.cors_allowed_origins: list[str] = self._parse_csv(
            os.getenv("CORS_ALLOWED_ORIGINS", ",".join(DEFAULT_LOCAL_CORS_ALLOWED_ORIGINS))
        )
        self.cors_allow_credentials: bool = os.getenv("CORS_ALLOW_CREDENTIALS", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.auth_enabled: bool = os.getenv("AUTH_ENABLED", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.auth_username: str = os.getenv("AUTH_USERNAME", DEFAULT_AUTH_USERNAME)
        self.auth_password: str = os.getenv("AUTH_PASSWORD", DEFAULT_AUTH_PASSWORD)
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

        # ALchemist 实验设计运行时目录
        self.alchemist_runtime_root: Path = self._resolve_project_path(
            os.getenv("ALCHEMIST_RUNTIME_ROOT", str(self.runtime_root / "alchemist"))
        )
        self.alchemist_backend_url: str = os.getenv("ALCHEMIST_BACKEND_URL", "http://127.0.0.1:5101")

        # Edison Scientific 文献搜索 API Key
        self.edison_api_key: str = os.getenv("EDISON_API_KEY", "")

        # LLM 配置（仅从环境变量读取，无默认值）
        self.llm_api_key: str = os.getenv("LLM_API_KEY", "")
        self.llm_base_url: str = os.getenv("LLM_BASE_URL", "")
        self.llm_model: str = os.getenv("LLM_MODEL", "")

        # Report generation 配置
        self.reports_enabled: bool = os.getenv("REPORTS_ENABLED", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.report_output_root: Path = self._resolve_project_path(
            os.getenv("REPORT_OUTPUT_ROOT", str(self.runtime_root / "reports"))
        )
        self.report_llm_provider: str = os.getenv("REPORT_LLM_PROVIDER", "openai_compatible").strip() or "openai_compatible"
        self.report_llm_fallback_providers: list[str] = [
            item.strip()
            for item in os.getenv("REPORT_LLM_FALLBACK_PROVIDERS", "").split(",")
            if item.strip()
        ]
        self.report_skill_pipeline_default: str = (
            os.getenv("REPORT_SKILL_PIPELINE_DEFAULT", "nature_research_report_zh").strip()
            or "nature_research_report_zh"
        )
        self.report_skill_allowlist: list[str] = [
            item.strip()
            for item in os.getenv(
                "REPORT_SKILL_ALLOWLIST",
                "nature-writing,nature-polishing,nature-data,nature-reviewer,nature-academic-search,nature-citation,nature-figure,nature-reader",
            ).split(",")
            if item.strip()
        ]
        self.report_skill_strict_mode: bool = os.getenv("REPORT_SKILL_STRICT_MODE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.report_llm_api_key: str = os.getenv("REPORT_LLM_API_KEY", self.llm_api_key or os.getenv("OPENAI_API_KEY", ""))
        self.report_llm_base_url: str = os.getenv("REPORT_LLM_BASE_URL", self.llm_base_url)
        self.report_llm_model: str = os.getenv("REPORT_LLM_MODEL", self.llm_model)
        self.report_llm_timeout_seconds: int = int(os.getenv("REPORT_LLM_TIMEOUT_SECONDS", "180"))
        self.report_llm_max_retries: int = int(os.getenv("REPORT_LLM_MAX_RETRIES", "2"))
        self.report_llm_store: bool = os.getenv("REPORT_LLM_STORE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.report_ollama_base_url: str = os.getenv("REPORT_OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        self.report_ollama_model: str = os.getenv("REPORT_OLLAMA_MODEL", "")
        self.report_codex_bin: str = os.getenv("REPORT_CODEX_BIN", "codex").strip() or "codex"
        self.report_codex_api_key: str = os.getenv("REPORT_CODEX_API_KEY", os.getenv("CODEX_API_KEY", ""))
        self.report_codex_model: str = os.getenv("REPORT_CODEX_MODEL", "")
        self.report_codex_timeout_seconds: int = int(os.getenv("REPORT_CODEX_TIMEOUT_SECONDS", "600"))
        self.report_codex_sandbox_workdir: Path = self._resolve_project_path(
            os.getenv("REPORT_CODEX_SANDBOX_WORKDIR", str(self.runtime_root / "reports"))
        )
        self.report_latex_engine: str = os.getenv("REPORT_LATEX_ENGINE", "xelatex").strip() or "xelatex"
        self.report_pdf_timeout_seconds: int = int(os.getenv("REPORT_PDF_TIMEOUT_SECONDS", "120"))
        self.report_keep_intermediate: bool = os.getenv("REPORT_KEEP_INTERMEDIATE", "true").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        # 统一认证（AI4MS）数据库配置
        self.auth_mongodb_uri: str = os.getenv("AUTH_MONGODB_URI", "")
        self.auth_database: str = os.getenv("AUTH_MONGODB_DATABASE", "ai4ms")

        # 只读材料数据资产 MongoDB 配置
        self.data_asset_mongodb_uri: str = os.getenv("DATA_ASSET_MONGODB_URI", "").strip()
        self.data_asset_mongodb_database: str = os.getenv("DATA_ASSET_MONGODB_DATABASE", "ai4ms").strip() or "ai4ms"

        # MinIO / S3 数据目录配置
        self.minio_endpoint: str = os.getenv("MINIO_ENDPOINT", "").strip()
        self.minio_access_key: str = os.getenv("MINIO_ACCESS_KEY", "").strip()
        self.minio_secret_key: str = os.getenv("MINIO_SECRET_KEY", "").strip()
        self.minio_bucket: str = os.getenv("MINIO_BUCKET", "polymer-data").strip() or "polymer-data"
        self.minio_secure: bool = os.getenv("MINIO_SECURE", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self.data_catalog_cache_ttl_seconds: int = int(os.getenv("DATA_CATALOG_CACHE_TTL_SECONDS", "900"))

        # Uploaded algorithm runtime. Production defaults to the subprocess sandbox.
        self.algorithm_runtime_backend: str = os.getenv(
            "ALGORITHM_RUNTIME_BACKEND",
            "local_sandbox_runtime",
        ).strip() or "local_sandbox_runtime"
        self.algorithm_runtime_max_output_bytes: int = int(
            os.getenv("ALGORITHM_RUNTIME_MAX_OUTPUT_BYTES", "65536")
        )
        self.algorithm_runtime_max_concurrency: int = int(
            os.getenv("ALGORITHM_RUNTIME_MAX_CONCURRENCY", "2")
        )

        self.upload_root.mkdir(parents=True, exist_ok=True)
        self.outputs_root.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)
        self.report_output_root.mkdir(parents=True, exist_ok=True)

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

    @staticmethod
    def _parse_csv(raw_value: str) -> list[str]:
        """Parse a comma-separated environment value into non-empty entries."""
        return [item.strip() for item in str(raw_value or "").split(",") if item.strip()]

    @property
    def is_local_env(self) -> bool:
        """Return whether the configured app environment is local/test-like."""
        return self.app_env.strip().lower() in LOCAL_APP_ENVS

    def validate_deployment_security(self) -> None:
        """Enforce authentication settings outside local/test environments."""
        if self.is_local_env:
            return

        errors: list[str] = []
        if not self.auth_enabled:
            errors.append("AUTH_ENABLED must be true")
        if self.auth_username == DEFAULT_AUTH_USERNAME:
            errors.append("AUTH_USERNAME must be changed from the default")
        if self.auth_password == DEFAULT_AUTH_PASSWORD:
            errors.append("AUTH_PASSWORD must be changed from the default")
        if len(self.auth_secret) < MIN_AUTH_SECRET_LENGTH:
            errors.append(f"AUTH_SECRET must be at least {MIN_AUTH_SECRET_LENGTH} characters")
        if self.auth_secret in {"", "change-me", "changeme", "secret", "default"}:
            errors.append("AUTH_SECRET must be a non-default random value")
        if not self.cors_allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS must include at least one production origin")
        if self.cors_allow_credentials and "*" in self.cors_allowed_origins:
            errors.append("CORS_ALLOWED_ORIGINS cannot include '*' when credentials are allowed")
        if errors:
            raise RuntimeError(
                "Unsafe deployment configuration for APP_ENV="
                f"{self.app_env!r}: "
                + "; ".join(errors)
            )

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
