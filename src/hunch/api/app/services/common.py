"""Shared request helpers for the application services."""

from __future__ import annotations

MAX_PAGE_SIZE = 100


def validate_page_window(limit: int, offset: int, *, maximum: int = MAX_PAGE_SIZE) -> None:
    """Collections are exact pages: 1 to `maximum` items, offset aligned to the page size."""
    if not 1 <= limit <= maximum:
        raise ValueError(f"limit must be between 1 and {maximum}.")
    if offset < 0:
        raise ValueError("offset must be greater than or equal to 0.")
    if offset % limit:
        raise ValueError("offset must be an exact multiple of limit.")


__all__ = ["MAX_PAGE_SIZE", "validate_page_window"]
