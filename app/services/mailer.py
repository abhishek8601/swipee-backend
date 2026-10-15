"""Outgoing email over SMTP (stdlib only).

MAIL_MAILER=log is a development driver like Laravel's: the message is written
to the server log and NOT delivered. Set MAIL_MAILER=smtp plus MAIL_HOST etc.
to actually send.
"""
import logging
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from app.core.config import settings

logger = logging.getLogger("swipee.mail")


class MailError(Exception):
    pass


def mailer() -> str:
    return settings.MAIL_MAILER.strip().lower()


def send_email(to: str, subject: str, text: str, html: Optional[str] = None) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((settings.MAIL_FROM_NAME, settings.MAIL_FROM_ADDRESS))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")

    if mailer() == "log":
        logger.warning("MAIL_MAILER=log, email NOT sent. To: %s | Subject: %s\n%s", to, subject, text)
        return
    if mailer() != "smtp":
        raise MailError(f"Unsupported MAIL_MAILER '{settings.MAIL_MAILER}' (use smtp or log).")
    if not settings.MAIL_HOST:
        raise MailError("MAIL_HOST is not set.")

    encryption = settings.MAIL_ENCRYPTION.strip().lower()
    try:
        if encryption == "ssl":
            server = smtplib.SMTP_SSL(settings.MAIL_HOST, settings.MAIL_PORT, timeout=20, context=ssl.create_default_context())
        else:
            server = smtplib.SMTP(settings.MAIL_HOST, settings.MAIL_PORT, timeout=20)
        with server:
            if encryption == "tls":
                server.starttls(context=ssl.create_default_context())
            if settings.MAIL_USERNAME:
                server.login(settings.MAIL_USERNAME, settings.MAIL_PASSWORD)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        # Never include credentials; the exception text from smtplib doesn't carry them.
        raise MailError(f"Could not send email via {settings.MAIL_HOST}:{settings.MAIL_PORT} ({e.__class__.__name__}: {e})")
