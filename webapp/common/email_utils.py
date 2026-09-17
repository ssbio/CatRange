"""Optional job-complete email notifications.

Inert (logs and returns) until `email.enabled: true` and real SMTP
credentials are set in `webapp/config/settings.yaml`.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import get_settings

logger = logging.getLogger("catrange.email")


def send_job_notification(to_address: str, job_id: str, status: str) -> None:
    settings = get_settings()
    if not settings.email.enabled:
        logger.info(
            "Email notifications disabled; skipping notification for job %s to %s",
            job_id,
            to_address,
        )
        return

    job_url = f"{settings.site.base_url.rstrip('/')}/job.html?id={job_id}"
    message = EmailMessage()
    message["Subject"] = f"CatRange job {status}: {job_id[:8]}"
    message["From"] = settings.email.from_address
    message["To"] = to_address
    if status == "done":
        body = (
            f"Your CatRange job finished.\n\nResults: {job_url}\n\n"
            "This link stays valid as long as the job's files are retained "
            f"(see the hosted-service retention policy for how long)."
        )
    else:
        body = (
            f"Your CatRange job did not finish successfully (status: {status}).\n\n"
            f"Details: {job_url}\n"
        )
    message.set_content(body)

    try:
        with smtplib.SMTP(settings.email.smtp_host, settings.email.smtp_port, timeout=30) as smtp:
            smtp.starttls()
            if settings.email.smtp_username:
                smtp.login(settings.email.smtp_username, settings.email.smtp_password)
            smtp.send_message(message)
    except Exception:  # noqa: BLE001 - notification failures must never fail the job
        logger.exception("Failed to send job notification email for job %s", job_id)
