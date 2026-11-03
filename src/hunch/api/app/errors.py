"""Stable, user-safe HTTP error construction."""

from __future__ import annotations

import logging

from fastapi import HTTPException

from msm.api.http import api_error
from msm.api.http import api_http_error as markets_api_http_error
from msm.api.http import not_found as not_found

logger = logging.getLogger(__name__)


def bad_request(message: str) -> HTTPException:
    return api_error(status_code=400, code="invalid_request", message=message)


def api_http_error(exc: Exception) -> HTTPException:
    """Translate a service exception into the shared `{code, message, retryable}` error body."""
    from hunch.connectors.base import ConnectorCapabilityUnavailable, ConnectorError
    from hunch.funding.services import FundingError
    from hunch.operations.builds import JobStartUnconfirmed
    from hunch.profiles.accounts import LinkError
    from hunch.research.guardrails import GuardrailError
    from hunch.research.models import ResearchError

    if isinstance(exc, ConnectorCapabilityUnavailable):
        return api_error(status_code=409, code="capability_unavailable", message=str(exc))
    if isinstance(exc, ConnectorError):
        logger.warning("Connector failure (%s): %s", exc.code, exc)
        status = 503 if exc.retryable else 502
        return api_error(
            status_code=status,
            code=f"connector_{exc.code}",
            message=str(exc),
            retryable=exc.retryable,
        )
    if isinstance(exc, FundingError):
        return api_error(status_code=409, code="funding_rule", message=str(exc))
    if isinstance(exc, LinkError):
        return api_error(status_code=409, code="link_rule", message=str(exc))
    if isinstance(exc, GuardrailError):
        return api_error(status_code=409, code="basket_not_investable", message=str(exc))
    if isinstance(exc, JobStartUnconfirmed):
        # Not a failure: the run may still start, and starting again could run it twice.
        logger.warning("Job start unconfirmed: %s", exc)
        return api_error(status_code=504, code="job_start_unconfirmed", message=str(exc))
    if isinstance(exc, ResearchError):
        logger.warning("Research unavailable: %s", exc)
        return api_error(
            status_code=502, code="research_unavailable", message=str(exc), retryable=True
        )
    if isinstance(exc, ValueError):
        return api_error(status_code=409, code="action_conflict", message=str(exc))
    if not isinstance(exc, (HTTPException, LookupError, TypeError)):
        logger.exception("Unhandled API dependency failure")
    return markets_api_http_error(exc)


__all__ = ["api_http_error", "bad_request", "not_found"]
