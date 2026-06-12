"""Prompt 52 - Type B SQL <-> plan two-way bridge (parse-sql / generate-sql). READ-ONLY: the SQL
box never executes; every non-subset / non-SELECT input is rejected without touching the DB."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

PARSE = "/data-models/type-b/parse-sql"
GENERATE = "/data-models/type-b/generate-sql"

VALID_SQL = (
    "SELECT a.id_prod AS prod, a.name_a, b.name_b\n"
    "FROM mdp_data.dm_sql_a a\n"
    "LEFT JOIN mdp_data.dm_sql_b b ON a.id_prod = b.id_prod"
)


def seed(db: Session) -> None:
    for ddl in (
        "CREATE TABLE IF NOT EXISTS dm_sql_a (id INTEGER PRIMARY KEY, id_prod TEXT, name_a TEXT, updated_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS dm_sql_b (id INTEGER PRIMARY KEY, id_prod TEXT, name_b TEXT)",
    ):
        db.execute(text(ddl))
    db.execute(text("DELETE FROM dm_sql_a"))
    db.execute(text("DELETE FROM dm_sql_b"))
    db.execute(text(
        "INSERT INTO dm_sql_a (id, id_prod, name_a, updated_at) VALUES "
        "(1,'P-100','A-old','2026-01-01 00:00:00'),(2,'P-100','A-new','2026-02-01 00:00:00'),"
        "(3,'P-200','A2','2026-01-01 00:00:00')"
    ))
    db.execute(text(
        "INSERT INTO dm_sql_b (id, id_prod, name_b) VALUES (1,'P-100','b1'),(2,'P-200','b2')"
    ))
    db.commit()


def test_x1_parse_valid_returns_plan(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed(db_session)
    r = client.post(PARSE, headers=auth_headers, json={"sql": VALID_SQL})
    assert r.status_code == 200, r.json()
    plan = r.json()
    assert plan["base"] == {"schema": "mdp_data", "table": "dm_sql_a"}
    assert {(t["schema"], t["table"]) for t in plan["selected_tables"]} == {
        ("mdp_data", "dm_sql_a"), ("mdp_data", "dm_sql_b"),
    }
    assert plan["relationships"] == [{
        "type": "left",
        "left": {"table": "dm_sql_a", "column": "id_prod"},
        "right": {"schema": "mdp_data", "table": "dm_sql_b", "column": "id_prod"},
    }]
    by_name = {a["name"]: a for a in plan["attributes"]}
    assert by_name["prod"]["source_table"] == "dm_sql_a"
    assert by_name["prod"]["source_column"] == "id_prod"
    assert by_name["prod"]["data_type"] == "text"
    assert set(by_name) == {"prod", "name_a", "name_b"}


@pytest.mark.parametrize("sql", [
    "SELECT * FROM mdp_data.dm_sql_a a",                                          # star
    "SELECT count(a.id_prod) FROM mdp_data.dm_sql_a a",                           # function
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a WHERE a.id_prod = 'x'",            # WHERE
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a GROUP BY a.id_prod",               # GROUP BY
    "SELECT DISTINCT a.id_prod FROM mdp_data.dm_sql_a a",                         # DISTINCT
    "SELECT a.id_prod + 1 AS x FROM mdp_data.dm_sql_a a",                         # expression
    "SELECT a.id_prod FROM (SELECT id_prod FROM mdp_data.dm_sql_a) a",            # subquery
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a "
    "JOIN mdp_data.dm_sql_b b ON a.id_prod = b.id_prod AND a.name_a = b.name_b",  # multi-cond ON
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a "
    "RIGHT JOIN mdp_data.dm_sql_b b ON a.id_prod = b.id_prod",                    # RIGHT join
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a, mdp_data.dm_sql_b b",             # comma/cross
    "SELECT a.id_prod FROM secret.dm_sql_a a",                                    # schema not allowed
    "SELECT id_prod FROM mdp_data.dm_sql_a a",                                    # unqualified column
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a UNION SELECT b.id_prod FROM mdp_data.dm_sql_b b",  # union
])
def test_x2_out_of_subset_rejected(
    client: TestClient, auth_headers: dict[str, str], db_session: Session, sql: str
) -> None:
    seed(db_session)
    r = client.post(PARSE, headers=auth_headers, json={"sql": sql})
    assert r.status_code == 422, r.json()
    assert isinstance(r.json()["detail"], list)


@pytest.mark.parametrize("sql", [
    "DROP TABLE mdp_data.dm_sql_a",
    "DELETE FROM mdp_data.dm_sql_a",
    "UPDATE mdp_data.dm_sql_a SET name_a = 'x'",
    "INSERT INTO mdp_data.dm_sql_a (id) VALUES (99)",
    "TRUNCATE mdp_data.dm_sql_a",
    "ALTER TABLE mdp_data.dm_sql_a ADD COLUMN z TEXT",
    "GRANT SELECT ON mdp_data.dm_sql_a TO public",
    "SELECT a.id_prod FROM mdp_data.dm_sql_a a; DROP TABLE dm_sql_a",  # statement stacking
])
def test_x2b_non_select_rejected_db_untouched(
    client: TestClient, auth_headers: dict[str, str], db_session: Session, sql: str
) -> None:
    seed(db_session)
    before = db_session.execute(text("SELECT COUNT(*) FROM dm_sql_a")).scalar()
    r = client.post(PARSE, headers=auth_headers, json={"sql": sql})
    assert r.status_code == 422, r.json()
    # The table and its rows are completely untouched (nothing was executed).
    still_there = db_session.execute(
        text("SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='dm_sql_a'")
    ).scalar()
    assert still_there == 1
    assert db_session.execute(text("SELECT COUNT(*) FROM dm_sql_a")).scalar() == before


def test_x3_generate_sql_round_trips(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed(db_session)
    plan = client.post(PARSE, headers=auth_headers, json={"sql": VALID_SQL}).json()
    gen = client.post(GENERATE, headers=auth_headers, json={
        "base": plan["base"],
        "attributes": plan["attributes"],
        "relationships": plan["relationships"],
    })
    assert gen.status_code == 200, gen.json()
    sql2 = gen.json()["sql"]
    plan2 = client.post(PARSE, headers=auth_headers, json={"sql": sql2}).json()
    assert plan2["base"] == plan["base"]
    assert plan2["relationships"] == plan["relationships"]
    shape = lambda p: [(a["source_table"], a["source_column"], a["name"]) for a in p["attributes"]]
    assert shape(plan2) == shape(plan)


def test_x3_generate_latest_only_adds_comment_and_still_round_trips(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed(db_session)
    plan = client.post(PARSE, headers=auth_headers, json={"sql": VALID_SQL}).json()
    gen = client.post(GENERATE, headers=auth_headers, json={
        "base": plan["base"],
        "attributes": plan["attributes"],
        "relationships": plan["relationships"],
        "latest_only": True,
        "recency_column": "updated_at",
    }).json()
    assert "-- latest_only is ON" in gen["sql"]
    assert "DISTINCT ON" in gen["sql"]
    # The leading comment is ignored by the parser -> the join/projection still round-trips.
    plan2 = client.post(PARSE, headers=auth_headers, json={"sql": gen["sql"]}).json()
    assert plan2["base"] == plan["base"]
    assert plan2["relationships"] == plan["relationships"]


def test_generate_rejects_non_whitelisted_schema(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # Review fix A: generate must enforce the schema whitelist like parse does (no pg_catalog etc).
    r = client.post(GENERATE, headers=auth_headers, json={
        "base": {"schema": "pg_catalog", "table": "pg_user"},
        "attributes": [{"name": "u", "source_schema": "pg_catalog", "source_table": "pg_user",
                        "source_column": "usename", "data_type": "text"}],
    })
    assert r.status_code == 422, r.json()
    assert "not allowed" in str(r.json()["detail"])


def test_generate_recency_column_is_identifier_validated(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # Review fix B: a malicious recency_column must NOT be interpolated raw into the comment; it
    # falls back to updated_at so the generated text can never contain injected multi-line content.
    seed(db_session)
    r = client.post(GENERATE, headers=auth_headers, json={
        "base": {"schema": "mdp_data", "table": "dm_sql_a"},
        "attributes": [{"name": "id_prod", "source_schema": "mdp_data", "source_table": "dm_sql_a",
                        "source_column": "id_prod", "data_type": "text"}],
        "latest_only": True,
        "recency_column": "u'); DROP TABLE foo; --\n-- ",
    })
    assert r.status_code == 200, r.json()
    sql = r.json()["sql"]
    assert "DROP TABLE" not in sql
    assert "recency column 'updated_at'" in sql


def test_parse_runs_through_validate_and_surfaces_warnings(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # id_prod repeats in dm_sql_a; choosing it as PK without latest_only fails the existing validator,
    # surfaced as non-blocking warnings (the plan is still returned so the builder updates).
    seed(db_session)
    r = client.post(PARSE, headers=auth_headers, json={"sql": VALID_SQL, "primary_key": "prod"})
    assert r.status_code == 200, r.json()
    assert any("not unique" in w["message"] for w in r.json()["warnings"])
