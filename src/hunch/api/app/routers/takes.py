"""Takes: the person's theses and their lifecycle."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query, Request, status

from ..errors import api_http_error
from ..identity import acting_user
from ..schemas import (
    ArchiveRequest,
    BuildRequest,
    BuildResponse,
    ExecutionModeRequest,
    ResourceCollection,
    ResourceDiscoveryResponse,
    RevisionResource,
    TakeCreateRequest,
    TakeResource,
    TakeUpdateRequest,
    WeightsResponse,
)
from ..services.portfolios import (
    activate_practice_resource,
    build_take_resource,
    refresh_take_resource,
    take_performance_frame,
    take_revision_resources,
    take_weights_resource,
)
from ..services.takes import (
    archive_take_resource,
    create_take_resource,
    fork_take_resource,
    get_take_resource,
    list_take_resources,
    publish_take_resource,
    set_execution_mode_resource,
    takes_discovery,
    unpublish_take_resource,
    update_take_resource,
)

router = APIRouter(prefix="/v1/takes", tags=["Takes"])


@router.get(
    "",
    response_model=ResourceCollection,
    response_model_by_alias=True,
    summary="List takes",
    description="One exact page of the acting user's takes, or of everyone's published takes.",
)
def list_takes(
    scope: Literal["mine", "public"] = Query(default="mine"),
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ResourceCollection:
    try:
        return list_take_resources(
            acting_user(),
            scope=scope,
            status=status_filter,
            search=search,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get(
    "/discovery",
    response_model=ResourceDiscoveryResponse,
    response_model_by_alias=True,
    summary="Takes collection discovery",
    description="Columns, search and filters of the takes collection (Command Center contract).",
)
def discovery(request: Request) -> ResourceDiscoveryResponse:
    try:
        discovered = takes_discovery(request.query_params.keys())
    except Exception as exc:
        raise api_http_error(exc) from exc
    return ResourceDiscoveryResponse.model_validate(discovered.model_dump(by_alias=True))


@router.post(
    "",
    response_model=TakeResource,
    status_code=status.HTTP_201_CREATED,
    summary="Create a take",
    description="Create a private draft take for the acting user.",
)
def create_take(payload: TakeCreateRequest) -> TakeResource:
    try:
        return create_take_resource(acting_user(), payload)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get("/{take_uid}", response_model=TakeResource, summary="Read a take")
def read_take(take_uid: str) -> TakeResource:
    try:
        return get_take_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.patch("/{take_uid}", response_model=TakeResource, summary="Edit a take")
def edit_take(take_uid: str, payload: TakeUpdateRequest) -> TakeResource:
    try:
        return update_take_resource(acting_user(), take_uid, payload)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/set-execution-mode",
    response_model=TakeResource,
    summary="Set the execution mode",
)
def set_mode(take_uid: str, payload: ExecutionModeRequest) -> TakeResource:
    try:
        return set_execution_mode_resource(acting_user(), take_uid, payload.execution_mode)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post("/{take_uid}/actions/publish", response_model=TakeResource, summary="Publish")
def publish(take_uid: str) -> TakeResource:
    try:
        return publish_take_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post("/{take_uid}/actions/unpublish", response_model=TakeResource, summary="Unpublish")
def unpublish(take_uid: str) -> TakeResource:
    try:
        return unpublish_take_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/fork",
    response_model=TakeResource,
    status_code=status.HTTP_201_CREATED,
    summary="Fork a take",
    description="Copy a published (or own) take into an independent private draft with lineage.",
)
def fork(take_uid: str) -> TakeResource:
    try:
        return fork_take_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/archive",
    response_model=TakeResource,
    summary="Archive a take",
    description="Archive after the exact confirmation `DELETE <take uid>`.",
)
def archive(take_uid: str, payload: ArchiveRequest) -> TakeResource:
    try:
        return archive_take_resource(acting_user(), take_uid, payload.confirmation)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/build",
    response_model=BuildResponse,
    summary="Build a take",
    description=(
        "Research the thesis, apply the take's constraints, publish the basket and (re)build the "
        "portfolio. Inline locally; a platform Job when hosted."
    ),
)
def build(take_uid: str, payload: BuildRequest | None = None) -> BuildResponse:
    try:
        return build_take_resource(
            acting_user(), take_uid, research_mode=payload.research_mode if payload else None
        )
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/activate-practice",
    response_model=TakeResource,
    summary="Activate as a practice take",
    description="Start the performance record without investing money.",
)
def activate(take_uid: str) -> TakeResource:
    try:
        return activate_practice_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.post(
    "/{take_uid}/actions/refresh",
    response_model=BuildResponse,
    summary="Refresh the portfolio",
    description="Bring prices up to date and extend the take's values.",
)
def refresh(take_uid: str) -> BuildResponse:
    try:
        return refresh_take_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get("/{take_uid}/revisions", response_model=list[RevisionResource], summary="Revisions")
def revisions(take_uid: str) -> list[RevisionResource]:
    try:
        return take_revision_resources(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get(
    "/{take_uid}/performance",
    summary="Performance since activation",
    description="Tabular frame of the take's values, rebased to 1 at activation.",
)
def performance(take_uid: str):
    try:
        return take_performance_frame(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get("/{take_uid}/weights", response_model=WeightsResponse, summary="Latest weights")
def weights(take_uid: str) -> WeightsResponse:
    try:
        return take_weights_resource(acting_user(), take_uid)
    except Exception as exc:
        raise api_http_error(exc) from exc
