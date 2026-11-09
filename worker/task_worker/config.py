from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ProjectEntry:
    name: str
    id: int


@dataclass(frozen=True)
class LabelEntry:
    name: str
    id: int


@dataclass(frozen=True)
class ProjectsConfig:
    projects: list[ProjectEntry]
    labels: list[LabelEntry]
    routing_hints: str

    def project_by_name(self, name: str) -> ProjectEntry | None:
        needle = name.strip().lower()
        for entry in self.projects:
            if entry.name.lower() == needle:
                return entry
        return None

    def label_by_name(self, name: str) -> LabelEntry | None:
        needle = name.strip().lower()
        for entry in self.labels:
            if entry.name.lower() == needle:
                return entry
        return None

    def project_names(self) -> list[str]:
        return [p.name for p in self.projects]

    def label_names(self) -> list[str]:
        return [label.name for label in self.labels]


@dataclass(frozen=True)
class Settings:
    redis_url: str
    redis_queue_key: str
    redis_processed_key: str
    llm_provider: str
    openai_api_key: str
    openai_model: str
    openai_base_url: str | None
    vikunja_base_url: str
    vikunja_token: str
    vikunja_fallback_project: str
    vikunja_needs_grooming_label: str
    vikunja_ui_base_url: str
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_pass: str
    smtp_from: str
    smtp_use_tls: bool
    projects_config_path: str
    confidence_threshold: float
    log_level: str
    projects: ProjectsConfig


def load_projects_config(path: str) -> ProjectsConfig:
    raw: dict[str, Any] = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    projects = [
        ProjectEntry(name=str(item["name"]), id=int(item["id"]))
        for item in raw.get("projects") or []
    ]
    labels = [
        LabelEntry(name=str(item["name"]), id=int(item["id"]))
        for item in raw.get("labels") or []
    ]
    if not projects:
        raise RuntimeError(f"No projects defined in {path}")
    if not labels:
        raise RuntimeError(f"No labels defined in {path}")
    return ProjectsConfig(
        projects=projects,
        labels=labels,
        routing_hints=str(raw.get("routing_hints") or "").strip(),
    )


def load_settings() -> Settings:
    config_path = os.getenv("PROJECTS_CONFIG", "/app/config/projects.yaml").strip()
    projects = load_projects_config(config_path)

    provider = os.getenv("LLM_PROVIDER", "openai").strip().lower() or "openai"
    if provider not in {"openai", "openai_compatible"}:
        raise RuntimeError(
            f"Unsupported LLM_PROVIDER={provider!r}; use openai|openai_compatible"
        )

    base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
    if provider == "openai_compatible" and not base_url:
        raise RuntimeError("OPENAI_BASE_URL is required when LLM_PROVIDER=openai_compatible")

    ui_base = os.getenv("VIKUNJA_UI_BASE_URL", "").strip()
    if not ui_base:
        # Derive from API base by stripping /api/v1
        api_base = _require("VIKUNJA_BASE_URL").rstrip("/")
        if api_base.endswith("/api/v1"):
            ui_base = api_base[: -len("/api/v1")]
        else:
            ui_base = api_base

    return Settings(
        redis_url=os.getenv("REDIS_URL", "redis://localhost:6379/0").strip(),
        redis_queue_key=os.getenv("REDIS_QUEUE_KEY", "email_todo:jobs").strip(),
        redis_processed_key=os.getenv(
            "REDIS_PROCESSED_KEY", "email_todo:processed_message_ids"
        ).strip(),
        llm_provider=provider,
        openai_api_key=_require("OPENAI_API_KEY"),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        openai_base_url=base_url,
        vikunja_base_url=_require("VIKUNJA_BASE_URL").rstrip("/"),
        vikunja_token=_require("VIKUNJA_TOKEN"),
        vikunja_fallback_project=os.getenv(
            "VIKUNJA_FALLBACK_PROJECT", "Email Inbox"
        ).strip()
        or "Email Inbox",
        vikunja_needs_grooming_label=os.getenv(
            "VIKUNJA_NEEDS_GROOMING_LABEL", "needs-grooming"
        ).strip()
        or "needs-grooming",
        vikunja_ui_base_url=ui_base.rstrip("/"),
        smtp_host=_require("SMTP_HOST"),
        smtp_port=int(os.getenv("SMTP_PORT", "465")),
        smtp_user=_require("SMTP_USER"),
        smtp_pass=_require("SMTP_PASS"),
        smtp_from=os.getenv("SMTP_FROM", "").strip() or _require("SMTP_USER"),
        smtp_use_tls=_bool("SMTP_USE_TLS", True),
        projects_config_path=config_path,
        confidence_threshold=float(os.getenv("CONFIDENCE_THRESHOLD", "0.6")),
        log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        projects=projects,
    )
