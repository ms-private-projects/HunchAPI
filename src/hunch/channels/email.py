"""Outbound email: a sender port with a local outbox and an SMTP implementation.

The digest Job composes one message per person and hands it to the configured sender.
``HUNCH_EMAIL_SENDER`` selects ``outbox`` (writes `.eml` files under ``HUNCH_EMAIL_OUTBOX_DIR``,
the local default), ``platform`` (a Main Sequence ``Notification`` to the person with
``include_email=True``, so the platform delivers the email; the hosted default), ``smtp``
(``HUNCH_SMTP_HOST``, ``HUNCH_SMTP_PORT``, ``HUNCH_SMTP_USERNAME``, ``HUNCH_SMTP_PASSWORD``,
``HUNCH_SMTP_STARTTLS``, ``HUNCH_EMAIL_FROM``; hosted deployments map these from Secrets) or
``none``. Credentials are read from the environment at send time only.
"""

from __future__ import annotations

import datetime as dt
import os
import re
import smtplib
import uuid
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Protocol

DEFAULT_OUTBOX = Path(".hunch-outbox")
DEFAULT_FROM = "Hunch <no-reply@hunch.local>"
SENDERS: tuple[str, ...] = ("outbox", "platform", "smtp", "none")
PLATFORM_NOTIFICATION_TYPE = "IN"


@dataclass(frozen=True)
class OutboundEmail:
    to: str
    subject: str
    body_md: str
    body_html: str | None = None
    headers: dict[str, str] = field(default_factory=dict)
    message_id: str = field(default_factory=lambda: f"<{uuid.uuid4().hex}@hunch>")
    user_uid: str | None = None


@dataclass(frozen=True)
class DeliveryReceipt:
    sender: str
    message_id: str
    detail: str | None = None


class EmailSender(Protocol):
    name: str

    def send(self, message: OutboundEmail) -> DeliveryReceipt: ...


def _build(message: OutboundEmail, sender: str) -> EmailMessage:
    email = EmailMessage()
    email["From"] = sender
    email["To"] = message.to
    email["Subject"] = message.subject
    email["Message-ID"] = message.message_id
    email["Date"] = dt.datetime.now(dt.timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")
    for key, value in message.headers.items():
        email[key] = value
    email.set_content(message.body_md)
    if message.body_html:
        email.add_alternative(message.body_html, subtype="html")
    return email


class OutboxSender:
    """Writes each message as an `.eml` file; the local stand-in for a mail server."""

    name = "outbox"

    def __init__(self, directory: Path | None = None, *, sender: str = DEFAULT_FROM) -> None:
        self.directory = directory or Path(os.environ.get("HUNCH_EMAIL_OUTBOX_DIR", DEFAULT_OUTBOX))
        self.sender = sender

    def send(self, message: OutboundEmail) -> DeliveryReceipt:
        self.directory.mkdir(parents=True, exist_ok=True)
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        safe_to = re.sub(r"[^A-Za-z0-9@._-]", "_", message.to)[:64]
        path = self.directory / f"{stamp}-{safe_to}-{uuid.uuid4().hex[:6]}.eml"
        path.write_bytes(bytes(_build(message, self.sender)))
        return DeliveryReceipt(sender=self.name, message_id=message.message_id, detail=str(path))


class SMTPSender:
    name = "smtp"

    def __init__(
        self,
        *,
        host: str,
        port: int = 587,
        username: str | None = None,
        password: str | None = None,
        starttls: bool = True,
        sender: str = DEFAULT_FROM,
        timeout: float = 20.0,
    ) -> None:
        self.host, self.port = host, port
        self._username, self._password = username, password
        self.starttls, self.sender, self.timeout = starttls, sender, timeout

    def send(self, message: OutboundEmail) -> DeliveryReceipt:
        email = _build(message, self.sender)
        with smtplib.SMTP(self.host, self.port, timeout=self.timeout) as smtp:
            if self.starttls:
                smtp.starttls()
            if self._username:
                smtp.login(self._username, self._password or "")
            smtp.send_message(email)
        return DeliveryReceipt(sender=self.name, message_id=message.message_id)


class PlatformNotificationSender:
    """A Main Sequence platform notification to the person, with the email flag set."""

    name = "platform"

    def __init__(self, notification_model: Any | None = None) -> None:
        self._model = notification_model

    def _notification(self) -> Any:
        if self._model is not None:
            return self._model
        from mainsequence.client import Notification

        return Notification

    def send(self, message: OutboundEmail) -> DeliveryReceipt:
        if not message.user_uid:
            raise ValueError("The platform sender needs the recipient's user uid.")
        result = self._notification().send(
            type=PLATFORM_NOTIFICATION_TYPE,
            title=message.subject,
            description=message.body_md,
            meta_data={"hunch": {"message_id": message.message_id, **message.headers}},
            include_email=True,
            target_user_uid=message.user_uid,
        )
        uid = getattr(result, "uid", None) if not isinstance(result, list) else None
        return DeliveryReceipt(
            sender=self.name, message_id=message.message_id, detail=str(uid) if uid else None
        )


class NullSender:
    name = "none"

    def send(self, message: OutboundEmail) -> DeliveryReceipt:
        return DeliveryReceipt(sender=self.name, message_id=message.message_id, detail="not sent")


def email_sender_name() -> str:
    value = os.environ.get("HUNCH_EMAIL_SENDER", "outbox").strip().lower() or "outbox"
    if value not in SENDERS:
        raise ValueError(f"HUNCH_EMAIL_SENDER must be one of: {', '.join(SENDERS)}.")
    return value


def configured_sender() -> EmailSender:
    name = email_sender_name()
    sender_address = os.environ.get("HUNCH_EMAIL_FROM", DEFAULT_FROM)
    if name == "smtp":
        host = os.environ.get("HUNCH_SMTP_HOST", "").strip()
        if not host:
            raise ValueError("HUNCH_EMAIL_SENDER=smtp needs HUNCH_SMTP_HOST.")
        return SMTPSender(
            host=host,
            port=int(os.environ.get("HUNCH_SMTP_PORT", "587")),
            username=os.environ.get("HUNCH_SMTP_USERNAME") or None,
            password=os.environ.get("HUNCH_SMTP_PASSWORD") or None,
            starttls=os.environ.get("HUNCH_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"},
            sender=sender_address,
        )
    if name == "platform":
        return PlatformNotificationSender()
    if name == "none":
        return NullSender()
    return OutboxSender(sender=sender_address)


__all__ = [
    "DeliveryReceipt",
    "EmailSender",
    "NullSender",
    "OutboundEmail",
    "OutboxSender",
    "PlatformNotificationSender",
    "SENDERS",
    "SMTPSender",
    "configured_sender",
    "email_sender_name",
]
