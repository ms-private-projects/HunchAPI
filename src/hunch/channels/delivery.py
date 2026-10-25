"""Deliver one person's digest: compose, resolve the address, send, record delivery."""

from __future__ import annotations

from typing import Any

from hunch.channels.digest import compose_digest, email_preferences, mark_delivered
from hunch.channels.email import OutboundEmail, configured_sender
from hunch.profiles import HunchUserProfile


def recipient_address(profile: HunchUserProfile) -> str | None:
    """The address on the Hunch profile, else the platform user's email when known."""
    preferences = email_preferences(profile)
    if preferences["email_address"]:
        return str(preferences["email_address"])
    return platform_email(profile.user_uid)


def platform_email(user_uid: str) -> str | None:
    """The Main Sequence user's email address, when the platform exposes it to this workload."""
    try:
        from mainsequence.client import User

        user = User.get_by_uid(user_uid)  # type: ignore[attr-defined]
    except Exception:
        return None
    address = getattr(user, "email", None)
    return str(address) if address else None


def send_digest_for(
    profile: HunchUserProfile, *, site_url: str | None = None, dry_run: bool = False
) -> dict[str, Any]:
    preferences = email_preferences(profile)
    if not preferences["email_digest"]:
        return {"state": "opted_out"}
    digest = compose_digest(profile, site_url=site_url)
    if digest.empty:
        return {"state": "nothing_new"}
    address = recipient_address(profile)
    if not address:
        return {"state": "no_address", "notifications": len(digest.notification_uids)}
    if dry_run:
        return {
            "state": "dry_run",
            "to": address,
            "subject": digest.subject,
            "notifications": len(digest.notification_uids),
        }
    receipt = configured_sender().send(
        OutboundEmail(
            to=address,
            subject=digest.subject,
            body_md=digest.body_md,
            headers={"X-Hunch-User": profile.user_uid},
            user_uid=profile.user_uid,
        )
    )
    mark_delivered(digest.notification_uids)
    return {
        "state": "sent",
        "to": address,
        "subject": digest.subject,
        "sender": receipt.sender,
        "message_id": receipt.message_id,
        "detail": receipt.detail,
        "notifications": len(digest.notification_uids),
    }


__all__ = ["platform_email", "recipient_address", "send_digest_for"]
