from __future__ import annotations

import logging
from email.message import EmailMessage

from task_worker.config import Settings
from task_worker.vikunja import CreatedTask

logger = logging.getLogger(__name__)


def _priority_label(priority: int) -> str:
    names = {
        0: "unset",
        1: "lowest",
        2: "low",
        3: "medium",
        4: "high",
        5: "urgent",
    }
    return names.get(priority, str(priority))


def build_ack_body(
    *,
    original_subject: str,
    created: CreatedTask,
) -> tuple[str, str]:
    """Return (subject, plain-text body) for the ack reply."""
    subject = f"Re: {original_subject}" if original_subject else "Task created"
    labels = ", ".join(created.label_names) if created.label_names else "(none)"
    due = created.due_date or "(none)"
    fallback_note = (
        "\nRouting used the Email Inbox fallback (low confidence or unknown project).\n"
        if created.used_fallback
        else ""
    )
    body = f"""Your email was turned into a Vikunja task.

Title:       {created.title}
Project:     {created.project_name}
Labels:      {labels}
Priority:    {_priority_label(created.priority)} ({created.priority})
Due date:    {due}
Confidence:  {created.confidence:.2f}
{fallback_note}
Open task:   {created.url}

This task is labeled needs-grooming — please review title, project, labels,
and due date before treating it as fully triaged.
"""
    return subject, body


async def send_ack_email(
    settings: Settings,
    *,
    to_address: str,
    original_subject: str,
    original_message_id: str | None,
    created: CreatedTask,
) -> None:
    subject, body = build_ack_body(
        original_subject=original_subject,
        created=created,
    )
    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to_address
    message["Subject"] = subject
    if original_message_id:
        message["In-Reply-To"] = original_message_id
        message["References"] = original_message_id
    message.set_content(body)

    use_tls = settings.smtp_use_tls
    # Port 465 typically expects implicit TLS; 587 uses STARTTLS.
    start_tls = use_tls and settings.smtp_port == 587
    implicit_tls = use_tls and settings.smtp_port != 587

    import aiosmtplib

    logger.info("Sending SMTP ack to %s for task %s", to_address, created.id)
    await aiosmtplib.send(
        message,
        hostname=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_user,
        password=settings.smtp_pass,
        start_tls=start_tls,
        use_tls=implicit_tls,
    )
