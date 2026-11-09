from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from task_worker.config import Settings
from task_worker.llm import ExtractedTask

logger = logging.getLogger(__name__)


@dataclass
class CreatedTask:
    id: int
    title: str
    project_id: int
    project_name: str
    label_names: list[str]
    priority: int
    due_date: str | None
    confidence: float
    used_fallback: bool
    url: str


class VikunjaClient:
    def __init__(self, settings: Settings) -> None:
        self._base = settings.vikunja_base_url.rstrip("/")
        self._token = settings.vikunja_token
        self._ui_base = settings.vikunja_ui_base_url.rstrip("/")
        self._settings = settings
        self._projects = settings.projects

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def create_task_from_extraction(
        self,
        extracted: ExtractedTask,
        *,
        source_message_id: str,
        source_from: str,
        source_subject: str,
    ) -> CreatedTask:
        project_entry = self._projects.project_by_name(extracted.project)
        used_fallback = False

        if (
            project_entry is None
            or extracted.confidence < self._settings.confidence_threshold
        ):
            fallback = self._projects.project_by_name(
                self._settings.vikunja_fallback_project
            )
            if fallback is None:
                raise RuntimeError(
                    f"Fallback project {self._settings.vikunja_fallback_project!r} "
                    "not found in projects.yaml"
                )
            if project_entry is None:
                logger.info(
                    "Unknown project %r → fallback %r",
                    extracted.project,
                    fallback.name,
                )
            else:
                logger.info(
                    "Low confidence %.2f for project %r → fallback %r",
                    extracted.confidence,
                    extracted.project,
                    fallback.name,
                )
            project_entry = fallback
            used_fallback = True

        description_parts = [extracted.description.strip()]
        if extracted.attachment_notes:
            description_parts.append(
                f"\n\n---\nAttachment notes:\n{extracted.attachment_notes}"
            )
        description_parts.append(
            "\n\n---\n"
            f"Source email\n"
            f"- From: {source_from}\n"
            f"- Subject: {source_subject}\n"
            f"- Message-ID: {source_message_id}\n"
            f"- Extraction confidence: {extracted.confidence:.2f}\n"
            f"- Routed project (model): {extracted.project or '(none)'}\n"
        )
        description = "".join(description_parts).strip()

        payload: dict[str, Any] = {
            "title": extracted.title,
            "description": description,
            "priority": extracted.priority,
        }
        if extracted.due_date:
            payload["due_date"] = extracted.due_date

        with httpx.Client(timeout=30.0) as client:
            resp = client.put(
                f"{self._base}/projects/{project_entry.id}/tasks",
                headers=self._headers(),
                json=payload,
            )
            resp.raise_for_status()
            task = resp.json()
            task_id = int(task["id"])

            label_names = self._attach_labels(client, task_id, extracted.labels)

        url = f"{self._ui_base}/tasks/{task_id}"
        logger.info(
            "Created Vikunja task id=%s project=%s labels=%s",
            task_id,
            project_entry.name,
            label_names,
        )
        return CreatedTask(
            id=task_id,
            title=extracted.title,
            project_id=project_entry.id,
            project_name=project_entry.name,
            label_names=label_names,
            priority=extracted.priority,
            due_date=extracted.due_date,
            confidence=extracted.confidence,
            used_fallback=used_fallback,
            url=url,
        )

    def _attach_labels(
        self,
        client: httpx.Client,
        task_id: int,
        ai_labels: list[str],
    ) -> list[str]:
        """Always attach needs-grooming plus any AI-chosen labels that exist."""
        wanted: list[str] = []
        grooming = self._settings.vikunja_needs_grooming_label
        wanted.append(grooming)
        for name in ai_labels:
            if name.lower() == grooming.lower():
                continue
            if name not in wanted:
                wanted.append(name)

        attached: list[str] = []
        for name in wanted:
            entry = self._projects.label_by_name(name)
            if entry is None:
                logger.warning("Skipping unknown label %r", name)
                continue
            resp = client.put(
                f"{self._base}/tasks/{task_id}/labels",
                headers=self._headers(),
                json={"label_id": entry.id},
            )
            if resp.status_code >= 400:
                logger.error(
                    "Failed attaching label %r to task %s: %s %s",
                    name,
                    task_id,
                    resp.status_code,
                    resp.text,
                )
                continue
            attached.append(entry.name)
        return attached
