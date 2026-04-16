import logging
import os
import smtplib
from email.message import EmailMessage

logger = logging.getLogger(__name__)

SMTP_HOST = os.environ.get("SMTP_HOST", "localhost")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "25"))
ALERT_SENDER = os.environ.get("ALERT_EMAIL_SENDER", "mailsub-alert@csie.ntu.edu.tw")


def send_alert_email(recipients: list[str], body: str, subject: str = "System Alert") -> None:
    """Send a plain-text alert email to a list of recipients via raw SMTP.

    This function is intentionally fire-and-forget: errors are logged but never
    raised, so a mail failure never masks the original exception that triggered
    the alert.

    Args:
        recipients: List of recipient email addresses.
        body: Plain-text email body.
        subject: Email subject line (default: "System Alert").
    """
    if not recipients:
        logger.warning("send_alert_email: recipients list is empty, skipping")
        return

    msg = EmailMessage()
    msg["From"] = ALERT_SENDER
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=10) as smtp:
            smtp.sendmail(ALERT_SENDER, recipients, msg.as_string())
        logger.info(
            "send_alert_email: sent '%s' to %s", subject, recipients
        )
    except Exception:
        logger.exception(
            "send_alert_email: failed to send '%s' to %s", subject, recipients
        )
