"""Takes as the REST routes and the MCP tools present them.

Authorisation lives in ``hunch.takes.services``; this module shapes resources, collections and
discovery for the Command Center contracts and resolves owner handles for attribution.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from hunch.api.app.identity import ActingUser
from hunch.api.app.schemas import ResourceCollection, TakeResource
from hunch.api.app.services.common import validate_page_window
from hunch.profiles.services import profiles_by_uid
from hunch.settings import EXECUTION_MODES, TAKE_STATUSES
from hunch.takes import Take
from hunch.takes.services import (
    ListScope,
    TakeConstraints,
    TakeCreate,
    TakeUpdate,
    archive_take,
    create_take,
    fork_take,
    get_take_for,
    list_takes,
    publish_take,
    set_execution_mode,
    unpublish_take,
    update_take,
)
from msm.api.http import (
    ResourceColumn,
    ResourceDiscovery,
    ResourceFilterOption,
    ResourceSelectFilter,
    build_resource_collection,
    build_resource_discovery_spec,
    resolve_resource_discovery,
)

TAKES_DISCOVERY = build_resource_discovery_spec(
    resource_id="takes",
    label="Takes",
    item_label="Take",
    identity_fields=("uid",),
    columns=(
        ResourceColumn(
            id="title", header="Title", value_path="title", data_type="text", importance="primary"
        ),
        ResourceColumn(id="status", header="Status", value_path="status", data_type="badge"),
        ResourceColumn(
            id="execution-mode",
            header="Mode",
            value_path="execution_mode",
            data_type="badge",
        ),
        ResourceColumn(
            id="visibility", header="Visibility", value_path="visibility", data_type="badge"
        ),
        ResourceColumn(id="owner", header="Owner", value_path="owner_handle", data_type="text"),
        ResourceColumn(
            id="activated-at",
            header="Active since",
            value_path="activated_at",
            data_type="datetime",
            default_visible=False,
        ),
        ResourceColumn(
            id="created-at", header="Created", value_path="created_at", data_type="datetime"
        ),
    ),
    search=True,
    filters=(
        ResourceSelectFilter(
            key="scope",
            label="Scope",
            type="select",
            options=(
                ResourceFilterOption(value="mine", label="My takes"),
                ResourceFilterOption(value="public", label="Published by everyone"),
            ),
        ),
        ResourceSelectFilter(
            key="status",
            label="Status",
            type="select",
            options=tuple(ResourceFilterOption(value=s, label=s) for s in TAKE_STATUSES),
        ),
    ),
)
DISCOVERY_SPECS = {"takes": TAKES_DISCOVERY}


def takes_discovery(query_keys: Iterable[str]) -> ResourceDiscovery:
    return resolve_resource_discovery("takes", query_keys, specs=DISCOVERY_SPECS)


def take_resources(rows: Sequence[Take]) -> list[TakeResource]:
    """Resources with owner handles resolved once per page."""
    handles = {uid: p.handle for uid, p in profiles_by_uid(r.owner_user_uid for r in rows).items()}
    return [take_resource(row, owner_handle=handles.get(row.owner_user_uid)) for row in rows]


def take_resource(row: Take, *, owner_handle: str | None = None) -> TakeResource:
    return TakeResource(
        uid=str(row.uid),
        owner_user_uid=row.owner_user_uid,
        owner_handle=owner_handle,
        title=row.title,
        thesis_text=row.thesis_text,
        constraints=TakeConstraints.model_validate(row.constraints_json or {}),
        status=row.status,
        execution_mode=row.execution_mode,
        visibility=row.visibility,
        forked_from_take_uid=str(row.forked_from_take_uid) if row.forked_from_take_uid else None,
        origin_take_uid=str(row.origin_take_uid) if row.origin_take_uid else None,
        signal_uid=row.signal_uid,
        activated_at=row.activated_at,
        published_at=row.published_at,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_take_resources(
    user: ActingUser,
    *,
    scope: ListScope = "mine",
    status: str | None = None,
    search: str | None = None,
    limit: int = 25,
    offset: int = 0,
) -> ResourceCollection:
    validate_page_window(limit, offset)
    rows, total = list_takes(
        user.uid, scope=scope, status=status, search=search, limit=limit, offset=offset
    )
    collection = build_resource_collection(
        items=[item.model_dump(mode="json") for item in take_resources(rows)],
        limit=limit,
        offset=offset,
        total_items=total,
    )
    return ResourceCollection.model_validate(collection.model_dump(by_alias=True))


def get_take_resource(user: ActingUser, take_uid: str) -> TakeResource:
    return take_resources([get_take_for(user.uid, take_uid)])[0]


def create_take_resource(user: ActingUser, payload: TakeCreate) -> TakeResource:
    return take_resources([create_take(user.uid, payload, username=user.username)])[0]


def update_take_resource(user: ActingUser, take_uid: str, payload: TakeUpdate) -> TakeResource:
    return take_resources([update_take(user.uid, take_uid, payload)])[0]


def set_execution_mode_resource(user: ActingUser, take_uid: str, mode: str) -> TakeResource:
    if mode not in EXECUTION_MODES:
        raise ValueError(f"execution_mode must be one of: {', '.join(EXECUTION_MODES)}.")
    return take_resources([set_execution_mode(user.uid, take_uid, mode)])[0]


def publish_take_resource(user: ActingUser, take_uid: str) -> TakeResource:
    return take_resources([publish_take(user.uid, take_uid)])[0]


def unpublish_take_resource(user: ActingUser, take_uid: str) -> TakeResource:
    return take_resources([unpublish_take(user.uid, take_uid)])[0]


def archive_take_resource(user: ActingUser, take_uid: str, confirmation: str) -> TakeResource:
    return take_resources([archive_take(user.uid, take_uid, confirmation)])[0]


def fork_take_resource(user: ActingUser, take_uid: str) -> TakeResource:
    return take_resources([fork_take(user.uid, take_uid, username=user.username)])[0]


__all__ = [
    "DISCOVERY_SPECS",
    "TAKES_DISCOVERY",
    "archive_take_resource",
    "create_take_resource",
    "fork_take_resource",
    "get_take_resource",
    "list_take_resources",
    "publish_take_resource",
    "set_execution_mode_resource",
    "take_resource",
    "take_resources",
    "takes_discovery",
    "unpublish_take_resource",
    "update_take_resource",
]
