"""Prompt 50 - Type B "latest version only" (auto dedup by key).

Append-only versioned fixtures: each ``id_prod`` has >= 2 rows with different
``updated_at``; the newest (max updated_at) row wins. ``dm_sample_a`` is the base;
``dm_sample_b`` and ``dm_sample_c`` join on ``id_prod`` (both also versioned).
"""
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.services.outbound_service import query_type_b_record_by_key


def seed_versioned_tables(db_session: Session) -> None:
    for ddl in (
        "CREATE TABLE IF NOT EXISTS dm_sample_a (id INTEGER PRIMARY KEY, id_prod TEXT, name_a TEXT, updated_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS dm_sample_b (id INTEGER PRIMARY KEY, id_prod TEXT, name_b TEXT, updated_at TIMESTAMP)",
        "CREATE TABLE IF NOT EXISTS dm_sample_c (id INTEGER PRIMARY KEY, id_prod TEXT, name_c TEXT, updated_at TIMESTAMP)",
    ):
        db_session.execute(text(ddl))
    for table in ("dm_sample_a", "dm_sample_b", "dm_sample_c"):
        db_session.execute(text(f"DELETE FROM {table}"))
    db_session.execute(text(
        "INSERT INTO dm_sample_a (id, id_prod, name_a, updated_at) VALUES "
        "(1,'P-100','A-old','2026-01-01 00:00:00'),(2,'P-100','A-new','2026-02-01 00:00:00'),"
        "(3,'P-200','A2-old','2026-01-01 00:00:00'),(4,'P-200','A2-new','2026-03-01 00:00:00')"
    ))
    db_session.execute(text(
        "INSERT INTO dm_sample_b (id, id_prod, name_b, updated_at) VALUES "
        "(1,'P-100','b-old','2026-01-05 00:00:00'),(2,'P-100','b-new','2026-02-05 00:00:00'),"
        "(3,'P-200','b2-old','2026-01-05 00:00:00'),(4,'P-200','b2-new','2026-03-05 00:00:00')"
    ))
    db_session.execute(text(
        "INSERT INTO dm_sample_c (id, id_prod, name_c, updated_at) VALUES "
        "(1,'P-100','c-old','2026-01-09 00:00:00'),(2,'P-100','c-new','2026-02-09 00:00:00'),"
        "(3,'P-200','c2-old','2026-01-09 00:00:00'),(4,'P-200','c2-new','2026-03-09 00:00:00')"
    ))
    db_session.commit()


def _va(name, col, *, table, dtype="text", pk=False):
    return {
        "name": name, "data_type": dtype, "source_schema": "mdp_data",
        "source_table": table, "source_column": col, "is_primary_key": pk,
    }


def _latest_model(name, attributes, relationships=None, *, primary_key="id_prod",
                  latest_only=True, recency_column="updated_at"):
    payload = {
        "name": name, "display_name": name, "type": "B", "primary_key": primary_key,
        "attributes": attributes, "relationships": relationships or [],
    }
    if latest_only:
        payload["latest_only"] = True
        if recency_column is not None:
            payload["recency_column"] = recency_column
    return payload


def _base_attrs():
    return [_va("id_prod", "id_prod", table="dm_sample_a", pk=True),
            _va("name_a", "name_a", table="dm_sample_a")]


def test_p1_latest_off_keeps_pk_unique_error(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers,
                    json=_latest_model("p1", _base_attrs(), latest_only=False))
    assert r.status_code == 422
    assert "not unique" in str(r.json()["detail"])


def test_p2_latest_on_base_dedup_preview(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    valid = client.post("/data-models/type-b/validate-mapping", headers=auth_headers,
                        json=_latest_model("p2", _base_attrs()))
    assert valid.status_code == 200, valid.json()
    preview = client.post("/data-models/type-b/preview", headers=auth_headers,
                          json=_latest_model("p2", _base_attrs()))
    assert preview.status_code == 200, preview.json()
    body = preview.json()
    assert body["count"] == 2  # one row per id_prod
    by = {row["id_prod"]: row for row in body["data"]}
    assert by["P-100"]["name_a"] == "A-new"
    assert by["P-200"]["name_a"] == "A2-new"


def test_p3_latest_on_multitable_join_no_fanout(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    attrs = [_va("id_prod", "id_prod", table="dm_sample_a", pk=True),
             _va("name_a", "name_a", table="dm_sample_a"),
             _va("name_b", "name_b", table="dm_sample_b"),
             _va("name_c", "name_c", table="dm_sample_c")]
    joins = [
        {"type": "left", "left": {"table": "dm_sample_a", "column": "id_prod"},
         "right": {"schema": "mdp_data", "table": "dm_sample_b", "column": "id_prod"}},
        {"type": "left", "left": {"table": "dm_sample_a", "column": "id_prod"},
         "right": {"schema": "mdp_data", "table": "dm_sample_c", "column": "id_prod"}},
    ]
    preview = client.post("/data-models/type-b/preview", headers=auth_headers,
                          json=_latest_model("p3", attrs, joins))
    assert preview.status_code == 200, preview.json()
    body = preview.json()
    assert body["count"] == 2  # NO fan-out even though id_prod repeats in every table
    by = {row["id_prod"]: row for row in body["data"]}
    assert by["P-100"] == {"id_prod": "P-100", "name_a": "A-new", "name_b": "b-new", "name_c": "c-new"}
    assert by["P-200"]["name_b"] == "b2-new"
    assert by["P-200"]["name_c"] == "c2-new"


def test_p4_recency_missing_column_errors(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers,
                    json=_latest_model("p4a", _base_attrs(), recency_column="does_not_exist"))
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(e.get("field") == "recency_column" for e in detail), detail
    assert "not found" in str(detail)


def test_p4_recency_non_sortable_errors(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers,
                    json=_latest_model("p4b", _base_attrs(), recency_column="name_a"))  # text col
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert any(e.get("field") == "recency_column" for e in detail), detail
    assert "not sortable" in str(detail)


def test_p5_p6_save_reload_outbound_dedup(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    seed_versioned_tables(db_session)
    created = client.post("/data-models", headers=auth_headers,
                          json=_latest_model("p5", _base_attrs()))
    assert created.status_code == 201, created.json()
    body = created.json()
    # P6: config persisted + reloads on read.
    assert body["latest_only"] is True
    assert body["recency_column"] == "updated_at"
    got = client.get(f"/data-models/{body['id']}", headers=auth_headers)
    assert got.status_code == 200
    assert got.json()["latest_only"] is True
    assert got.json()["recency_column"] == "updated_at"
    # P5: outbound by-key uses the SAME builder -> returns the newest row.
    model = db_session.execute(select(DataModel).where(DataModel.name == "p5")).scalar_one()
    record = query_type_b_record_by_key(db_session, model=model, key="P-100")
    assert record is not None
    assert record["name_a"] == "A-new"


def test_stale_latest_config_does_not_bypass_pk_uniqueness_on_create(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # Guard-bypass regression (review finding 1): a CREATE payload with latest_only=False but a stale
    # latest_config entry in relationships must NOT resurrect dedup during validation, or the
    # PK-unique guard would be skipped for a model that persistence stores WITHOUT dedup.
    seed_versioned_tables(db_session)
    payload = _latest_model("stale_create", _base_attrs(), latest_only=False)
    payload["relationships"] = [{"type": "latest_config", "latest_only": True, "recency_column": "updated_at"}]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=payload)
    assert r.status_code == 422
    assert "not unique" in str(r.json()["detail"])


def test_toggle_off_update_re_enforces_pk_uniqueness(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # Guard-bypass regression (review finding 1): turning the toggle OFF via a partial PUT that omits
    # relationships must re-raise the PK-not-unique error (the base is non-unique without dedup) and
    # leave the saved model unchanged - validation and persistence agree.
    seed_versioned_tables(db_session)
    created = client.post("/data-models", headers=auth_headers, json=_latest_model("toggle_off", _base_attrs()))
    assert created.status_code == 201, created.json()
    model_id = created.json()["id"]
    upd = client.put(f"/data-models/{model_id}", headers=auth_headers, json={"latest_only": False})
    assert upd.status_code == 422, upd.json()
    assert "not unique" in str(upd.json()["detail"])
    got = client.get(f"/data-models/{model_id}", headers=auth_headers)
    assert got.json()["latest_only"] is True  # rejected update -> saved model still deduped


def test_latest_on_without_recency_persists_effective_default(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # Review finding 2: latest_only ON with recency_column omitted must persist + surface the
    # effective default (updated_at), not null.
    seed_versioned_tables(db_session)
    payload = _latest_model("default_recency", _base_attrs(), recency_column=None)
    created = client.post("/data-models", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["latest_only"] is True
    assert body["recency_column"] == "updated_at"


def test_p6_off_round_trip_leaves_relationships_clean(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    # latest_only OFF must not persist any latest_config entry (old behaviour unchanged). Use the
    # unique surrogate (column "id" -> attribute "row_id", since "id" is a reserved system name) as
    # PK so the model is valid WITHOUT dedup.
    seed_versioned_tables(db_session)
    attrs = [_va("row_id", "id", table="dm_sample_a", dtype="integer", pk=True),
             _va("name_a", "name_a", table="dm_sample_a")]
    created = client.post("/data-models", headers=auth_headers,
                          json=_latest_model("p6off", attrs, primary_key="row_id", latest_only=False))
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["latest_only"] is False
    assert body["recency_column"] is None
    assert all(rel.get("type") != "latest_config" for rel in (body["relationships"] or []))
