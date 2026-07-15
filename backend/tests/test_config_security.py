"""Deployment security configuration tests."""

from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.core.config import Settings
from app.core.config import settings
from app.main import unhandled_exception_handler


class DeploymentSecurityConfigTest(unittest.TestCase):
    """Cover non-local auth hard gates without affecting local defaults."""

    def _settings_with_env(self, env: dict[str, str]) -> Settings:
        with tempfile.TemporaryDirectory(prefix="poly-agent-config-test-") as runtime_root:
            merged = {
                "POLY_AGENT_RUNTIME_ROOT": runtime_root,
                "POLY_AGENT_UPLOAD_ROOT": os.path.join(runtime_root, "uploads"),
                "POLY_AGENT_OUTPUT_ROOT": os.path.join(runtime_root, "outputs"),
                "POLY_AGENT_LOG_ROOT": os.path.join(runtime_root, "logs"),
                **env,
            }
            with patch.dict(os.environ, merged, clear=False):
                return Settings()

    def test_local_dev_allows_demo_auth_defaults(self) -> None:
        settings = self._settings_with_env(
            {
                "APP_ENV": "dev",
                "AUTH_ENABLED": "false",
                "AUTH_USERNAME": "admin",
                "AUTH_PASSWORD": "admin123456",
                "AUTH_SECRET": "",
            }
        )

        settings.validate_deployment_security()

    def test_production_requires_auth_and_non_default_secret(self) -> None:
        settings = self._settings_with_env(
            {
                "APP_ENV": "production",
                "AUTH_ENABLED": "false",
                "AUTH_USERNAME": "admin",
                "AUTH_PASSWORD": "admin123456",
                "AUTH_SECRET": "short",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "AUTH_ENABLED.*AUTH_USERNAME.*AUTH_PASSWORD.*AUTH_SECRET"):
            settings.validate_deployment_security()

    def test_production_accepts_hardened_auth_settings(self) -> None:
        settings = self._settings_with_env(
            {
                "APP_ENV": "production",
                "AUTH_ENABLED": "true",
                "AUTH_USERNAME": "poly-admin",
                "AUTH_PASSWORD": "not-the-default-password",
                "AUTH_SECRET": "0123456789abcdef0123456789abcdef",
                "CORS_ALLOWED_ORIGINS": "https://polyagent.example.com",
            }
        )

        settings.validate_deployment_security()

    def test_production_rejects_credentialed_wildcard_cors(self) -> None:
        settings = self._settings_with_env(
            {
                "APP_ENV": "production",
                "AUTH_ENABLED": "true",
                "AUTH_USERNAME": "poly-admin",
                "AUTH_PASSWORD": "not-the-default-password",
                "AUTH_SECRET": "0123456789abcdef0123456789abcdef",
                "CORS_ALLOWED_ORIGINS": "*",
                "CORS_ALLOW_CREDENTIALS": "true",
            }
        )

        with self.assertRaisesRegex(RuntimeError, "CORS_ALLOWED_ORIGINS cannot include"):
            settings.validate_deployment_security()

    def test_assistant_web_search_defaults_are_safe_and_enabled(self) -> None:
        settings = self._settings_with_env(
            {
                "APP_ENV": "dev",
            }
        )

        self.assertTrue(settings.assistant_web_search_enabled)
        self.assertEqual(settings.assistant_web_search_provider, "searxng")
        self.assertEqual(settings.assistant_web_search_max_results, 6)
        self.assertEqual(settings.assistant_web_fetch_max_pages, 3)

    def test_production_unhandled_errors_do_not_expose_exception_detail(self) -> None:
        original_app_env = settings.app_env
        settings.app_env = "production"
        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/explodes",
                "headers": [],
                "query_string": b"",
                "server": ("testserver", 80),
                "scheme": "http",
                "client": ("testclient", 50000),
            }
        )

        try:
            response = asyncio.run(
                unhandled_exception_handler(request, RuntimeError("database password leaked"))
            )
        finally:
            settings.app_env = original_app_env

        body = response.body.decode("utf-8")
        self.assertIn("internal server error", body)
        self.assertNotIn("database password leaked", body)
