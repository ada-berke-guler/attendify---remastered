from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

logger = logging.getLogger("attendify.mail")


def send_reset_code(email: str, code: str) -> None:
    """Send the reset code, or log it when SMTP is not configured (demo mode)."""
    if not settings.mail_enabled:
        logger.warning("SMTP not configured. Password reset code for %s: %s", email, code)
        return
    msg = EmailMessage()
    msg["Subject"] = "Attendify - Password Reset Code"
    msg["From"] = settings.MAIL_FROM
    msg["To"] = email
    msg.set_content(f"Your password reset code is: {code}\n\nThis code expires in 15 minutes.")
    try:
        with smtplib.SMTP(settings.MAIL_SERVER, settings.MAIL_PORT, timeout=15) as smtp:
            if settings.MAIL_STARTTLS:
                smtp.starttls()
            if settings.MAIL_USERNAME:
                smtp.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            smtp.send_message(msg)
    except (smtplib.SMTPException, OSError):
        logger.exception("Could not send reset email to %s", email)
