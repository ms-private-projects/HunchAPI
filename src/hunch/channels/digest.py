"""The daily email digest: one message per person from their undelivered notifications.

Composition is deterministic (no model): a greeting, a section per take with its latest review,
executions and funding events, the proposals still waiting for a decision, and the disclaimers.
Delivery marks the notifications as delivered by email so a rerun never repeats them.
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from hunch.api.app.schemas import DISCLAIMERS
from hunch.community import HunchNotification
from hunch.community.notifications import list_notifications
from hunch.funding.services import list_proposals
from hunch.profiles import HunchUserProfile, utc_now
from hunch.takes import Take

EMAIL_CHANNEL = "email"
SECTION_ORDER = (
    "proposal_awaiting_approval",
    "proposal_executed",
    "proposal_failed",
    "funding_active",
    "funding_closed",
    "review_proposed",
    "review_hold",
    "take_built",
    "take_forked",
    "account_linked",
)


@dataclass
class Digest:
    user_uid: str
    subject: str
    body_md: str
    notification_uids: list[uuid.UUID] = field(default_factory=list)
    pending_proposals: int = 0

    @property
    def empty(self) -> bool:
        return not self.notification_uids and not self.pending_proposals


def email_preferences(profile: HunchUserProfile) -> dict[str, Any]:
    metadata = profile.metadata_json or {}
    return {
        "email_digest": bool(metadata.get("email_digest", False)),
        "email_address": metadata.get("email_address"),
    }


def undelivered(user_uid: str, *, since: dt.datetime | None = None) -> list[HunchNotification]:
    rows = list_notifications(user_uid)
    out = []
    for row in rows:
        if EMAIL_CHANNEL in (row.delivered_channels_json or []):
            continue
        if since is not None and row.created_at is not None and row.created_at < since:
            continue
        out.append(row)
    return out


def compose_digest(
    profile: HunchUserProfile,
    *,
    site_url: str | None = None,
    since: dt.datetime | None = None,
    today: dt.date | None = None,
) -> Digest:
    """A Markdown digest of what happened since the last email, grouped by take."""
    date = today or utc_now().date()
    rows = undelivered(profile.user_uid, since=since)
    pending = list_proposals(profile.user_uid, status="proposed")
    by_take: dict[str, list[HunchNotification]] = defaultdict(list)
    for row in rows:
        by_take[str(row.take_uid) if row.take_uid else ""].append(row)
    takes = {str(t.uid): t for t in Take.filter(owner_user_uid=profile.user_uid, limit=5000)}
    name = profile.display_name or f"@{profile.handle}"
    lines = [f"# Hunch daily update, {date.isoformat()}", "", f"Hello {name},", ""]
    if pending:
        lines.append(
            f"## {len(pending)} proposal{'s' if len(pending) != 1 else ''} waiting for you"
        )
        lines.append("")
        for proposal in pending:
            take = takes.get(str(proposal.take_uid))
            total = sum(float(leg.get("estimated_notional") or 0.0) for leg in proposal.legs_json)
            link = f" ({site_url}/proposals)" if site_url else ""
            lines.append(
                f"- **{take.title if take else 'A take'}**: {len(proposal.legs_json)} trades, "
                f"about {total:,.0f} estimated, expires "
                f"{proposal.expires_at.strftime('%b %d %H:%M UTC') if proposal.expires_at else 'soon'}{link}"
            )
        lines.append("")
    for take_uid, items in sorted(by_take.items(), key=lambda kv: kv[0]):
        take = takes.get(take_uid)
        lines.append(f"## {take.title if take else 'Your account'}")
        lines.append("")
        ordered = sorted(
            items,
            key=lambda r: (
                SECTION_ORDER.index(r.kind) if r.kind in SECTION_ORDER else 99,
                r.created_at or dt.datetime.min.replace(tzinfo=dt.timezone.utc),
            ),
        )
        for row in ordered:
            when = row.created_at.strftime("%b %d %H:%M UTC") if row.created_at else ""
            lines.append(f"- **{row.title}** ({when})")
            body = (row.body_md or "").strip()
            if body and row.kind in ("review_hold", "review_proposed"):
                summary = next(
                    (ln for ln in body.splitlines() if ln.strip() and not ln.startswith("#")), ""
                )
                if summary:
                    lines.append(f"  {summary.strip()}")
        if take and site_url:
            lines.append(f"  Open: {site_url}/takes/{take_uid}")
        lines.append("")
    if not rows and not pending:
        lines.append("Nothing new since your last update.")
        lines.append("")
    lines.append("---")
    lines.extend(f"_{text}_" for text in DISCLAIMERS)
    lines.append("")
    lines.append(
        "Reply to this email to ask the Hunch Agent about any of this, or open the Assistant."
    )
    subject = (
        f"Hunch: {len(pending)} proposal{'s' if len(pending) != 1 else ''} waiting"
        if pending
        else f"Hunch daily update for {date.isoformat()}"
    )
    return Digest(
        user_uid=profile.user_uid,
        subject=subject,
        body_md="\n".join(lines),
        notification_uids=[row.uid for row in rows],
        pending_proposals=len(pending),
    )


def mark_delivered(notification_uids: list[uuid.UUID], *, channel: str = EMAIL_CHANNEL) -> None:
    for uid in notification_uids:
        row = HunchNotification.get_by_uid(uid)
        if row is None:
            continue
        channels = list(row.delivered_channels_json or [])
        if channel not in channels:
            channels.append(channel)
            HunchNotification.update(uid, delivered_channels_json=channels)


__all__ = [
    "Digest",
    "EMAIL_CHANNEL",
    "compose_digest",
    "email_preferences",
    "mark_delivered",
    "undelivered",
]
