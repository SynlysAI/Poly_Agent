"""Deployment security configuration tests."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from app.core.config import Settings


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
            }
        )

        settings.validate_deployment_security()
