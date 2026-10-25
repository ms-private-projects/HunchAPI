"""The instrument universe."""

from __future__ import annotations

from fastapi import APIRouter, Query, Request

from ..errors import api_http_error, not_found
from ..identity import acting_user
from ..schemas import InstrumentResource, ResourceCollection, ResourceDiscoveryResponse
from ..services.instruments import (
    get_instrument_resource,
    instruments_discovery,
    list_instrument_resources,
    seed_instruments,
)

router = APIRouter(prefix="/v1/instruments", tags=["Instruments"])


@router.get(
    "",
    response_model=ResourceCollection,
    response_model_by_alias=True,
    summary="List instruments",
    description="One exact page of the instruments Hunch can hold.",
)
def list_instruments(
    search: str | None = Query(default=None, max_length=100),
    sector: str | None = Query(default=None, max_length=128),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> ResourceCollection:
    acting_user()
    try:
        return list_instrument_resources(search=search, sector=sector, limit=limit, offset=offset)
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get(
    "/discovery",
    response_model=ResourceDiscoveryResponse,
    response_model_by_alias=True,
    summary="Instruments collection discovery",
)
def discovery(request: Request) -> ResourceDiscoveryResponse:
    acting_user()
    try:
        discovered = instruments_discovery(request.query_params.keys())
    except Exception as exc:
        raise api_http_error(exc) from exc
    return ResourceDiscoveryResponse.model_validate(discovered.model_dump(by_alias=True))


@router.post(
    "/actions/seed",
    summary="Seed the universe",
    description="Register every fixture instrument that is missing; idempotent.",
)
def seed() -> dict[str, int]:
    acting_user()
    try:
        return {"instruments": seed_instruments()}
    except Exception as exc:
        raise api_http_error(exc) from exc


@router.get("/{identifier}", response_model=InstrumentResource, summary="Read an instrument")
def read_instrument(identifier: str) -> InstrumentResource:
    acting_user()
    try:
        resource = get_instrument_resource(identifier)
    except Exception as exc:
        raise api_http_error(exc) from exc
    if resource is None:
        raise not_found(f"Instrument {identifier} does not exist.")
    return resource
