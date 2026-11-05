"""Tabele rekordow warstwy danych generowane z modeli pydantic (typer/ingest/core/records.py).
Jeden model = jedna tabela, klucz glowny = source_key (idempotentny zapis), available_at NOT NULL.
Dzieki temu schemat bazy i walidacja nie moga sie rozjechac."""
from __future__ import annotations

import types
import typing
from datetime import date, datetime

import sqlalchemy as sa
from pydantic import AwareDatetime, NaiveDatetime
from sqlalchemy import JSON, Boolean, Column, Date, DateTime, Float, Index, Integer, String, Table, Text

from typer.ingest.core.records import ALL_RECORD_TYPES, BaseRecord

TEXT_FIELDS = {"text", "reason", "url"}


def _base_type(ann):
    """(typ bazowy, czy dopuszcza None) z adnotacji pola (Optional, Annotated, Literal, list)."""
    origin = typing.get_origin(ann)
    if origin is typing.Annotated:
        return _base_type(typing.get_args(ann)[0])
    if origin in (typing.Union, types.UnionType):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        t, _ = _base_type(args[0])
        return t, True
    if origin is typing.Literal:
        vals = typing.get_args(ann)
        return (int if all(isinstance(v, int) for v in vals) else str), False
    if origin in (list, tuple):
        return list, False
    return ann, False


def _sa_type(name: str, t):
    if t is bool:
        return Boolean
    if t is int:
        return Integer
    if t is float:
        return Float
    if t is list:
        return JSON
    if t in (AwareDatetime, NaiveDatetime) or (isinstance(t, type) and issubclass(t, datetime)):
        return DateTime(timezone=True)
    if isinstance(t, type) and issubclass(t, date):
        return Date
    return Text if name in TEXT_FIELDS else String(300)


def table_for(model: type[BaseRecord], metadata: sa.MetaData) -> Table:
    cols = [Column("source_key", String(300), primary_key=True)]
    for name, f in model.model_fields.items():
        if name == "source_key":
            continue
        t, optional = _base_type(f.annotation)
        cols.append(Column(name, _sa_type(name, t), nullable=optional or not f.is_required()))
    t = Table(model.record_type, metadata, *cols)
    Index(f"ix_{model.record_type}_available_at", t.c.available_at)
    return t


def build(metadata: sa.MetaData) -> dict[str, Table]:
    return {m.record_type: table_for(m, metadata) for m in ALL_RECORD_TYPES}
