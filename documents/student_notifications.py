from __future__ import annotations

import logging
from typing import Iterable

import requests
from django.conf import settings
from django.contrib.auth.models import User

from documents.models import StudentRecord

logger = logging.getLogger(__name__)


def _brevo_api_key() -> str:
    return (
        getattr(settings, "BREVO_API_KEY", "")
        or getattr(settings, "PAPERLESS_BREVO_API_KEY", "")
        or ""
    )


def _sender() -> dict[str, str]:
    email = getattr(settings, "BREVO_SENDER_EMAIL", "") or getattr(
        settings,
        "DEFAULT_FROM_EMAIL",
        "",
    )
    name = getattr(settings, "BREVO_SENDER_NAME", "") or "UB Record Management"
    return {"email": email, "name": name}


def send_brevo_email(
    *,
    to: Iterable[dict[str, str]],
    subject: str,
    text: str,
) -> bool:
    api_key = _brevo_api_key()
    sender = _sender()
    recipients = [recipient for recipient in to if recipient.get("email")]
    if not api_key or not sender.get("email") or not recipients:
        logger.info(
            "Brevo email skipped because sender, API key, or recipients are missing.",
        )
        return False

    response = requests.post(
        getattr(
            settings,
            "BREVO_SMTP_ENDPOINT",
            "https://api.brevo.com/v3/smtp/email",
        ),
        headers={
            "accept": "application/json",
            "api-key": api_key,
            "content-type": "application/json",
        },
        json={
            "sender": sender,
            "to": recipients,
            "subject": subject,
            "textContent": text,
        },
        timeout=getattr(settings, "BREVO_TIMEOUT_SECONDS", 20),
    )
    response.raise_for_status()
    return True


def send_student_credentials_email(user: User, password: str) -> None:
    matricule = getattr(
        getattr(user, "student_profile", None),
        "matricule",
        user.username,
    )
    try:
        send_brevo_email(
            to=[{"email": user.email, "name": user.get_full_name() or user.username}],
            subject="Your UB Record Management account",
            text=(
                "Your UB Record Management student account has been created.\n\n"
                f"Matricule: {matricule}\n"
                f"Temporary password: {password}\n\n"
                "Please log in and change your password before submitting records."
            ),
        )
    except Exception:
        logger.exception(
            "Unable to send student credentials email for user %s",
            user.pk,
        )


def send_pending_record_email(record: StudentRecord) -> None:
    admins = User.objects.filter(is_active=True, is_staff=True).exclude(email="")
    student_name = ""
    if record.student:
        student_name = record.student.get_full_name() or record.student.username
    try:
        send_brevo_email(
            to=[
                {"email": admin.email, "name": admin.get_full_name() or admin.username}
                for admin in admins
            ],
            subject="Student record pending review",
            text=(
                "A student record has been submitted and is pending review.\n\n"
                f"Student: {student_name or 'Unknown'}\n"
                f"Document ID: {record.document_id}\n"
            ),
        )
    except Exception:
        logger.exception(
            "Unable to send pending student record email for record %s",
            record.pk,
        )
