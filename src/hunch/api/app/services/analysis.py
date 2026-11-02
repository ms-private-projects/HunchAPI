"""Analysis-only answers about a take: no change to Hunch state, one bounded model call."""

from __future__ import annotations

from hunch.analysis.services import critique_thesis
from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import ThesisCritiqueResource
from hunch.takes.services import get_take_for


def critique_thesis_resource(
    user: ActingUser, take_uid: str, *, mode: str | None = None
) -> ThesisCritiqueResource:
    """Critique the thesis of a take the person owns or a published one."""
    take = get_take_for(user.uid, take_uid)
    critique = critique_thesis(take, mode=mode)
    return ThesisCritiqueResource(take_uid=str(take.uid), **critique.model_dump())


__all__ = ["critique_thesis_resource"]
