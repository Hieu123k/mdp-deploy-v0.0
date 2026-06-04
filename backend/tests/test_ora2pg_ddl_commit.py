"""Prove the ora2pg DDL fix: _apply_ddl commits so the target table persists, plus the
to_regclass guard. Requires a reachable PostgreSQL (no Oracle needed); skips otherwise."""
import pytest
from sqlalchemy import text

from app.db.session import engine
from app.services.ora2pg_runner import _apply_ddl


def _require_postgres():
    if engine.dialect.name != "postgresql":
        pytest.skip("DDL-commit test requires postgresql (to_regclass / schemas)")
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres not reachable for DDL-commit test")


def _regclass(schema: str, table: str):
    with engine.connect() as c:
        return c.execute(
            text("SELECT to_regclass(:q)"), {"q": f'"{schema}"."{table}"'}
        ).scalar()


def _drop(schema: str, table: str) -> None:
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as c:
        c.exec_driver_sql(f'DROP TABLE IF EXISTS "{schema}"."{table}"')


def test_apply_ddl_commits_and_table_persists():
    """After _apply_ddl returns, the table must really exist (i.e. it was committed,
    not rolled back when the connection closed) — the exact bug from .63 REPORT #4."""
    _require_postgres()
    schema, table = "mdp_staging", "t_ddl_commit_test"
    _drop(schema, table)
    try:
        _apply_ddl(schema, f'CREATE TABLE "{table}" (id int);', target_table=table)
        assert _regclass(schema, table) is not None  # persisted across the connection
    finally:
        _drop(schema, table)


def test_apply_ddl_guard_raises_when_target_missing():
    """If the generated DDL does not actually create the requested target, the guard
    raises a clear error instead of letting COPY fail later."""
    _require_postgres()
    schema = "mdp_staging"
    _drop(schema, "t_ddl_other")
    try:
        with pytest.raises(RuntimeError, match="target table .* is missing"):
            _apply_ddl(
                schema,
                'CREATE TABLE IF NOT EXISTS "t_ddl_other" (id int);',
                target_table="t_ddl_target_missing",
            )
    finally:
        _drop(schema, "t_ddl_other")
