"""Report context collection and sanitization."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any


SECRET_KEY_PARTS = ("api_key", "apikey", "secret", "token", "password")
PATH_KEY_PARTS = ("path", "uri", "storage_uri")
ABSOLUTE_PATH_RE = re.compile(r"^(?:/|~/|[A-Za-z]:[\\/])")


class ReportContextService:
    """Build sanitized report context packages from traceability services."""

    def __init__(self, *, research_engine_service: Any | None = None, max_string_length: int = 4000) -> None:
        self._research_engine_service = research_engine_service
        self.max_string_length = max_string_length

    @property
    def research_engine_service(self):
        if self._research_engine_service is None:
            from app.services.research_engine_service import ResearchEngineService

            self._research_engine_service = ResearchEngineService()
        return self._research_engine_service

    def collect_context(
        self,
        *,
        subject_type: str,
        subject_id: str,
        actor_user_id: str | None = None,
        is_admin: bool = False,
    ) -> dict[str, Any]:
        """Collect and sanitize report context for a supported subject."""
        if subject_type == "algorithm_run":
            raw = self.research_engine_service.get_algorithm_run_traceability(
                subject_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            context = self._build_algorithm_context(subject_id, raw)
        elif subject_type == "research_run":
            raw = self.research_engine_service.get_research_run_traceability(
                subject_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
            context = self._build_research_context(subject_id, raw)
        elif subject_type == "workflow_run":
            context = self._collect_workflow_context(
                subject_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
        elif subject_type == "computation_run":
            context = self._collect_computation_context(
                subject_id,
                actor_user_id=actor_user_id,
                is_admin=is_admin,
            )
        else:
            raise ValueError(f"Unsupported report subject_type: {subject_type}")

        truncation_notes: list[dict[str, Any]] = []
        sanitized = self._sanitize(context, path="$", truncation_notes=truncation_notes)
        sanitized["truncation_notes"] = truncation_notes
        sanitized["context_metadata"] = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "max_string_length": self.max_string_length,
            "redaction": {
                "secret_keys": list(SECRET_KEY_PARTS),
                "absolute_paths": True,
            },
        }
        return sanitized

    def _build_algorithm_context(self, subject_id: str, raw_traceability: Any) -> dict[str, Any]:
        raw = self._to_plain(raw_traceability)
        return {
            "subject": {
                "subject_type": "algorithm_run",
                "subject_id": subject_id,
            },
            "algorithm_run": raw.get("algorithm_run") or {},
            "linked_computation": raw.get("linked_computation"),
            "audit_events": raw.get("audit_events") or [],
            "artifacts": self._collect_artifact_refs(raw),
        }

    def _build_research_context(self, subject_id: str, raw_traceability: Any) -> dict[str, Any]:
        raw = self._to_plain(raw_traceability)
        research_run = raw.get("research_run") or {}
        return {
            "subject": {
                "subject_type": "research_run",
                "subject_id": subject_id,
                "status": research_run.get("status"),
            },
            "research_run": research_run,
            "stages": research_run.get("stage_runs") or [],
            "algorithm_runs": raw.get("linked_algorithm_runs") or [],
            "linked_algorithm_runs": raw.get("linked_algorithm_runs") or [],
            "computations": raw.get("linked_computations") or [],
            "linked_computations": raw.get("linked_computations") or [],
            "observations": raw.get("linked_observations") or [],
            "linked_observations": raw.get("linked_observations") or [],
            "audit_events": raw.get("audit_events") or [],
            "artifacts": self._collect_artifact_refs(raw),
        }

    def _collect_workflow_context(
        self,
        subject_id: str,
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> dict[str, Any]:
        workflow_run = self.research_engine_service.get_workflow_run(
            subject_id,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        )
        algorithm_runs = self.research_engine_service.list_algorithm_runs(
            workflow_run_id=subject_id,
            created_by=None if is_admin else actor_user_id,
            page=1,
            page_size=100,
        ).items
        audit_events = self.research_engine_service.query_audit_events(
            entity_type="workflow_run",
            entity_id=subject_id,
            page=1,
            page_size=100,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        ).items
        raw = {
            "subject": {
                "subject_type": "workflow_run",
                "subject_id": subject_id,
                "status": getattr(workflow_run, "status", None),
            },
            "workflow_run": self._to_plain(workflow_run),
            "algorithm_runs": self._to_plain(algorithm_runs),
            "linked_algorithm_runs": self._to_plain(algorithm_runs),
            "audit_events": self._to_plain(audit_events),
        }
        raw["artifacts"] = self._collect_artifact_refs(raw)
        return raw

    def _collect_computation_context(
        self,
        subject_id: str,
        *,
        actor_user_id: str | None,
        is_admin: bool,
    ) -> dict[str, Any]:
        from app.services.computation_service import ComputationService

        computation_service = ComputationService()
        run = computation_service.get_run(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
        artifacts = computation_service.list_artifacts(subject_id, actor_user_id=actor_user_id, is_admin=is_admin)
        audit_events = computation_service.list_audit_events(
            entity_type="computation_run",
            entity_id=subject_id,
            event_type=None,
            page=1,
            page_size=100,
            actor_user_id=actor_user_id,
            is_admin=is_admin,
        ).items
        return {
            "subject": {
                "subject_type": "computation_run",
                "subject_id": subject_id,
                "status": getattr(run, "status", None),
            },
            "computation_run": self._to_plain(run),
            "artifacts": self._to_plain(artifacts),
            "audit_events": self._to_plain(audit_events),
        }

    def _to_plain(self, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="python")
        if isinstance(value, dict):
            return {key: self._to_plain(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_plain(item) for item in value]
        return value

    def _sanitize(self, value: Any, *, path: str, truncation_notes: list[dict[str, Any]]) -> Any:
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, item in value.items():
                key_text = str(key)
                lowered = key_text.lower()
                child_path = f"{path}.{key_text}"
                if any(part in lowered for part in SECRET_KEY_PARTS):
                    cleaned[key] = "[REDACTED]"
                elif isinstance(item, str) and self._is_path_like_secret(lowered, item):
                    cleaned[key] = "[REDACTED_PATH]"
                else:
                    cleaned[key] = self._sanitize(item, path=child_path, truncation_notes=truncation_notes)
            return cleaned
        if isinstance(value, list):
            return [
                self._sanitize(item, path=f"{path}[{index}]", truncation_notes=truncation_notes)
                for index, item in enumerate(value)
            ]
        if isinstance(value, str):
            if ABSOLUTE_PATH_RE.match(value.strip()):
                return "[REDACTED_PATH]"
            if len(value) > self.max_string_length:
                truncation_notes.append(
                    {
                        "path": path,
                        "original_length": len(value),
                        "truncated_to": self.max_string_length,
                    }
                )
                return value[: self.max_string_length] + "...[TRUNCATED]"
        return value

    def _is_path_like_secret(self, key: str, value: str) -> bool:
        if not any(part in key for part in PATH_KEY_PARTS):
            return False
        return bool(ABSOLUTE_PATH_RE.match(value.strip()))

    def _collect_artifact_refs(self, raw: dict[str, Any]) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = []

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                artifact_refs = value.get("artifact_refs")
                if isinstance(artifact_refs, list):
                    refs.extend(ref for ref in artifact_refs if isinstance(ref, dict))
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(raw)
        return refs
