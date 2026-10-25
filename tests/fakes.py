"""An in-memory stand-in for the ms-markets row APIs, for service tests without a runtime.

`install_fake_rows` replaces the classmethods of one or more `MarketsMetaTableRow` subclasses with
dictionary-backed implementations that honour primary keys, upsert keys, Python column defaults and
exact-match filters, the subset the Hunch services use.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest


class FakeRowStore:
    def __init__(self) -> None:
        self.rows: dict[type, dict[str, dict[str, Any]]] = {}

    def table(self, row_cls: type) -> dict[str, dict[str, Any]]:
        return self.rows.setdefault(row_cls, {})

    @staticmethod
    def _primary_key(row_cls: type) -> str:
        return next(iter(row_cls.__table__.__table__.primary_key.columns)).name

    @staticmethod
    def _defaults(row_cls: type, values: dict[str, Any]) -> dict[str, Any]:
        row = dict(values)
        for column in row_cls.__table__.__table__.columns:
            if column.name in row or column.default is None:
                continue
            arg = column.default.arg
            if callable(arg):
                try:
                    row[column.name] = arg(None)
                except TypeError:
                    row[column.name] = arg()
            else:
                row[column.name] = arg
        return row

    def install(self, monkeypatch: pytest.MonkeyPatch, row_cls: type) -> None:
        store = self.table(row_cls)
        pk = self._primary_key(row_cls)

        def key(value: Any) -> str:
            return str(value)

        def create(payload=None, **values):
            row = self._defaults(row_cls, {**(payload or {}), **values})
            if row.get(pk) is None:
                row[pk] = uuid.uuid4()
            store[key(row[pk])] = row
            return row_cls.model_validate(row)

        def upsert(payload=None, **values):
            merged = {**(payload or {}), **values}
            conflict = tuple(row_cls.__upsert_keys__)
            for existing in store.values():
                if all(key(existing.get(c)) == key(merged.get(c)) for c in conflict):
                    existing.update(merged)
                    return row_cls.model_validate(existing)
            return create(**merged)

        def update(uid, payload=None, **values):
            row = store.get(key(uid))
            if row is None:
                raise LookupError(f"{row_cls.__name__} {uid} does not exist.")
            row.update({**(payload or {}), **values})
            return row_cls.model_validate(row)

        def delete(uid):
            removed = store.pop(key(uid), None)
            return {"ok": True, "row_count": 0 if removed is None else 1}

        def get_by_uid(uid):
            row = store.get(key(uid))
            return row_cls.model_validate(row) if row is not None else None

        def filter(*, limit=500, **filters):
            matched = []
            for row in store.values():
                ok = True
                for name, wanted in filters.items():
                    if wanted in (None, ""):
                        continue
                    if name.endswith("_contains"):
                        field = name.removesuffix("_contains")
                        ok = str(wanted).lower() in str(row.get(field, "")).lower()
                    else:
                        ok = key(row.get(name)) == key(wanted)
                    if not ok:
                        break
                if ok:
                    matched.append(row_cls.model_validate(row))
            return matched[:limit]

        for name, function in (
            ("create", create),
            ("upsert", upsert),
            ("update", update),
            ("delete", delete),
            ("get_by_uid", get_by_uid),
            ("filter", filter),
        ):
            monkeypatch.setattr(row_cls, name, function)


def install_fake_rows(monkeypatch: pytest.MonkeyPatch, *row_classes: type) -> FakeRowStore:
    store = FakeRowStore()
    for row_cls in row_classes:
        store.install(monkeypatch, row_cls)
    return store


__all__ = ["FakeRowStore", "install_fake_rows"]
