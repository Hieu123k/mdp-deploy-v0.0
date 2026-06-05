"""Bug 2 — data-model edits must persist to the DB and keep the Type A generated table in
sync (so inbound keeps working with new attributes)."""
import pytest
from sqlalchemy import text

from app.services import table_generator
from tests.test_data_models import type_a_payload


def test_update_persists_attribute_changes(client, auth_headers):
    created = client.post("/data-models", headers=auth_headers, json=type_a_payload("inv_edit")).json()
    model_id = created["id"]

    payload = type_a_payload("inv_edit")
    payload["attributes"].append({"name": "currency", "data_type": "text", "required": False})
    # flip `amount` from required True -> False
    for attr in payload["attributes"]:
        if attr["name"] == "amount":
            attr["required"] = False
    res = client.put(f"/data-models/{model_id}", headers=auth_headers, json=payload)
    assert res.status_code == 200, res.text

    # re-read from the API (reads the DB) — the edit must be there
    got = client.get(f"/data-models/{model_id}", headers=auth_headers).json()
    names = [a["name"] for a in got["attributes"]]
    assert "currency" in names
    amount = next(a for a in got["attributes"] if a["name"] == "amount")
    assert amount["required"] is False


# --------------------------------------------------- generated-table sync (postgres)
class _FakeModel:
    def __init__(self, name, attributes):
        self.name = name
        self.attributes = attributes


def _require_pg():
    from app.db.session import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("generated-table sync test requires postgresql")
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        pytest.skip("postgres not reachable")


def test_sync_generated_table_adds_missing_columns_non_destructively():
    _require_pg()
    from app.db.session import SessionLocal

    name = "synctest_dm"
    with SessionLocal() as db:
        db.execute(text('CREATE SCHEMA IF NOT EXISTS "mdp_data"'))
        db.execute(text('DROP TABLE IF EXISTS "mdp_data"."dm_synctest_dm"'))
        db.execute(text('CREATE TABLE "mdp_data"."dm_synctest_dm" ("id" uuid, "raw_payload" jsonb, "f1" text)'))
        db.commit()
        try:
            model = _FakeModel("synctest_dm", [
                {"name": "f1", "data_type": "text"},
                {"name": "f2", "data_type": "float"},
            ])
            added = table_generator.sync_generated_table_columns(db, model)
            db.commit()
            assert added == ["f2"]

            # idempotent — running again adds nothing
            assert table_generator.sync_generated_table_columns(db, model) == []
            db.commit()

            cols = {
                r[0]
                for r in db.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema='mdp_data' AND table_name='dm_synctest_dm'"
                    )
                )
            }
            assert {"f1", "f2"} <= cols  # f1 kept, f2 added
        finally:
            db.execute(text('DROP TABLE IF EXISTS "mdp_data"."dm_synctest_dm"'))
            db.commit()
