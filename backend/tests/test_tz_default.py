"""Prompt 39 — dm_* business timestamps default to local (VN) wall-clock + tz anti-injection.

The actual `now() AT TIME ZONE` DDL + historical backfill run only on postgres (verified in the
on-VM acceptance, report 39). These unit tests cover the dialect-independent contract: the timezone
is validated (pattern + — on postgres — pg_timezone_names) BEFORE it reaches any DDL, so a toxic
APP_TIMEZONE is blocked (TZ4), and the DEFAULT clause uses the configured timezone.
"""
import pytest
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.table_generator import (
    TableGenerationError,
    create_generated_table_for_model,
    timestamp_default_clause,
    validate_timezone,
)


class _Model:
    def __init__(self, name: str, attributes: list[dict]) -> None:
        self.name = name
        self.attributes = attributes


def test_validate_timezone_rejects_injection_and_empty(db_session: Session) -> None:
    with pytest.raises(TableGenerationError):
        validate_timezone(db_session, "Asia/HCM'); DROP TABLE x; --")
    with pytest.raises(TableGenerationError):
        validate_timezone(db_session, "")
    with pytest.raises(TableGenerationError):
        validate_timezone(db_session, "Asia/Ho Chi Minh")  # space is not a tz char
    # A clean IANA name passes the pattern (the pg_timezone_names check is postgres-only).
    assert validate_timezone(db_session, "Asia/Ho_Chi_Minh") == "Asia/Ho_Chi_Minh"


def test_timestamp_default_clause_uses_app_timezone(db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "app_timezone", "Asia/Ho_Chi_Minh")
    assert timestamp_default_clause(db_session) == "(now() AT TIME ZONE 'Asia/Ho_Chi_Minh')"


def test_tz4_toxic_app_timezone_blocks_table_create(db_session: Session, monkeypatch) -> None:
    # TZ4: a toxic APP_TIMEZONE must be rejected BEFORE any DDL is built (on every dialect).
    monkeypatch.setattr(settings, "app_timezone", "evil'); DROP TABLE x; --")
    model = _Model("tz_toxic_demo", [{"name": "amount", "data_type": "float"}])
    with pytest.raises(TableGenerationError):
        create_generated_table_for_model(db_session, model)
