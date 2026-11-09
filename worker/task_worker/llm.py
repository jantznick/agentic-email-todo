from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from task_worker.config import ProjectsConfig, Settings

logger = logging.getLogger(__name__)

EXTRACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "title": {"type": "string", "description": "Concise task title"},
        "description": {
            "type": "string",
            "description": "Task description with relevant context from the email",
        },
        "project": {
            "type": "string",
            "description": "Exact project name from the allowed list",
        },
        "labels": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Zero or more labels from the allowed list (exclude needs-grooming)",
        },
        "priority": {
            "type": "integer",
            "minimum": 0,
            "maximum": 5,
            "description": "0=unset, 1=lowest ... 5=highest",
        },
        "due_date": {
            "type": ["string", "null"],
            "description": "ISO-8601 date or datetime if clear, else null",
        },
        "confidence": {
            "type": "number",
            "minimum": 0,
            "maximum": 1,
            "description": "Confidence in project/label routing",
        },
        "attachment_notes": {
            "type": "string",
            "description": "Brief notes on attachment relevance; empty if none",
        },
    },
    "required": [
        "title",
        "description",
        "project",
        "labels",
        "priority",
        "due_date",
        "confidence",
        "attachment_notes",
    ],
}


@dataclass
class ExtractedTask:
    title: str
    description: str
    project: str
    labels: list[str]
    priority: int
    due_date: str | None
    confidence: float
    attachment_notes: str


def _build_system_prompt(projects: ProjectsConfig) -> str:
    project_list = ", ".join(projects.project_names())
    label_list = ", ".join(
        name
        for name in projects.label_names()
        if name.lower() != "needs-grooming"
    )
    hints = projects.routing_hints or "(none)"
    return f"""You convert inbound emails into Vikunja todo tasks.

Return ONLY structured JSON matching the schema. Do not invent projects or labels.

Allowed projects (choose exactly one by name): {project_list}
Allowed labels (optional, from this list only; do NOT include needs-grooming — it is added automatically): {label_list or "(none)"}

Routing hints:
{hints}

Rules:
- title: short actionable summary (not the raw subject unless it already is)
- description: useful context from the email body; include key details
- If attachments have text extracts, summarize relevance into description and attachment_notes
- priority: 0 if unclear; otherwise 1 (low) to 5 (urgent)
- due_date: only when explicitly stated or strongly implied; else null
- confidence: how sure you are about project routing (0-1)
- If unsure which project, prefer "Email Inbox" and lower confidence
"""


def _build_user_payload(job: dict[str, Any]) -> str:
    attachments = job.get("attachments") or []
    att_lines: list[str] = []
    for att in attachments:
        extract = (att.get("text_extract") or "").strip()
        preview = extract[:1500] if extract else "(no text extract)"
        att_lines.append(
            f"- {att.get('filename')} ({att.get('content_type')}, "
            f"{att.get('size_bytes')} bytes)\n  extract: {preview}"
        )
    att_block = "\n".join(att_lines) if att_lines else "(none)"

    body = (job.get("text_body") or "").strip()
    if not body:
        body = (job.get("html_body") or "").strip()
        # Cheap HTML strip for the model when only HTML is present
        if body:
            import re

            body = re.sub(r"<[^>]+>", " ", body)
            body = re.sub(r"\s+", " ", body).strip()

    return f"""From: {job.get('from_header') or job.get('from')}
To: {', '.join(job.get('to') or [])}
Subject: {job.get('subject') or ''}
Date: {job.get('date') or ''}
Message-ID: {job.get('message_id') or ''}

Body:
{body[:12000]}

Attachments:
{att_block}
"""


def _parse_extraction(data: dict[str, Any]) -> ExtractedTask:
    labels_raw = data.get("labels") or []
    if not isinstance(labels_raw, list):
        labels_raw = []
    due = data.get("due_date")
    if due is not None:
        due = str(due).strip() or None
    return ExtractedTask(
        title=str(data.get("title") or "Untitled email task").strip()[:250],
        description=str(data.get("description") or "").strip(),
        project=str(data.get("project") or "").strip(),
        labels=[str(label).strip() for label in labels_raw if str(label).strip()],
        priority=max(0, min(5, int(data.get("priority") or 0))),
        due_date=due,
        confidence=float(data.get("confidence") or 0.0),
        attachment_notes=str(data.get("attachment_notes") or "").strip(),
    )


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
        if settings.openai_base_url:
            kwargs["base_url"] = settings.openai_base_url
        self._client = OpenAI(**kwargs)
        self._model = settings.openai_model
        self._provider = settings.llm_provider
        self._projects = settings.projects

    def extract_task(self, job: dict[str, Any]) -> ExtractedTask:
        system = _build_system_prompt(self._projects)
        user = _build_user_payload(job)
        logger.info(
            "Calling LLM provider=%s model=%s message_id=%s",
            self._provider,
            self._model,
            job.get("message_id"),
        )

        # Prefer structured outputs when available; fall back to JSON mode.
        try:
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.2,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vikunja_task_extract",
                        "strict": True,
                        "schema": EXTRACT_SCHEMA,
                    },
                },
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
        except Exception as schema_exc:
            logger.warning(
                "json_schema response_format failed (%s); retrying with json_object",
                schema_exc,
            )
            response = self._client.chat.completions.create(
                model=self._model,
                temperature=0.2,
                response_format={"type": "json_object"},
                messages=[
                    {
                        "role": "system",
                        "content": system
                        + "\n\nRespond with a single JSON object matching this schema:\n"
                        + json.dumps(EXTRACT_SCHEMA),
                    },
                    {"role": "user", "content": user},
                ],
            )

        content = response.choices[0].message.content or "{}"
        data = json.loads(content)
        return _parse_extraction(data)
