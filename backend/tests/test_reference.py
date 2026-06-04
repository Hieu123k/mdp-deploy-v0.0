"""Editable reference lists — CRUD, admin gating, soft-delete/reactivate, ora2pg overlay."""
from app.schemas.user import UserCreate
from app.services.reference_service import seed_reference_options
from app.services.user_service import create_user


def _seed(db):
    seed_reference_options(db)


def test_reference_seeded_and_readable(client, auth_headers, db_session):
    _seed(db_session)
    res = client.get("/reference/domains", headers=auth_headers)
    assert res.status_code == 200
    values = [o["value"] for o in res.json()["options"]]
    assert "procurement" in values and "master_data" in values


def test_reference_admin_crud_and_soft_delete(client, auth_headers, db_session):
    _seed(db_session)
    created = client.post("/reference/domains", headers=auth_headers, json={"value": "robotics"})
    assert created.status_code == 201
    oid = created.json()["id"]
    assert "robotics" in [o["value"] for o in client.get("/reference/domains", headers=auth_headers).json()["options"]]

    upd = client.patch(f"/reference/domains/{oid}", headers=auth_headers, json={"label": "Robotics & Automation"})
    assert upd.status_code == 200 and upd.json()["label"] == "Robotics & Automation"

    # soft delete → gone from the active list
    assert client.delete(f"/reference/domains/{oid}", headers=auth_headers).status_code == 204
    assert "robotics" not in [o["value"] for o in client.get("/reference/domains", headers=auth_headers).json()["options"]]

    # re-adding the same value reactivates it (no 409, no duplicate)
    again = client.post("/reference/domains", headers=auth_headers, json={"value": "robotics"})
    assert again.status_code == 201


def test_reference_duplicate_active_is_409(client, auth_headers, db_session):
    _seed(db_session)
    assert client.post("/reference/domains", headers=auth_headers, json={"value": "procurement"}).status_code == 409


def test_reference_unmanaged_list_is_400(client, auth_headers):
    # behavioural enums (run statuses, roles, …) are not admin-managed
    assert client.post("/reference/run_statuses", headers=auth_headers, json={"value": "x"}).status_code == 400


def test_reference_write_requires_admin(client, db_session):
    create_user(db_session, UserCreate(username="viewer1", email="viewer1@mdp.local", password="viewer123", role="viewer"))
    db_session.commit()
    token = client.post("/auth/login", json={"username": "viewer1", "password": "viewer123"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.get("/reference/domains", headers=headers).status_code == 200  # read ok
    assert client.post("/reference/domains", headers=headers, json={"value": "x"}).status_code == 403  # write blocked


def test_ora2pg_catalog_overlay_add_and_resolve(client, auth_headers, db_session):
    _seed(db_session)
    # base catalog still 40
    assert len(client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]) == 40

    add = client.post(
        "/reference/ora2pg_tables", headers=auth_headers,
        json={"value": "V2_PRO_F9999", "extra": {"target_table": "v2_pro_f9999", "module": "Custom", "ts_col": None}},
    )
    assert add.status_code == 201

    tables = client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]
    names = [t["table"] for t in tables]
    assert "V2_PRO_F9999" in names and len(tables) == 41
    # the overlaid table resolves through the normal dashboard path
    assert client.get("/ora2pg/tables/V2_PRO_F9999/config-preview", headers=auth_headers).status_code == 200


def test_ora2pg_catalog_overlay_hide_base_table(client, auth_headers, db_session):
    _seed(db_session)
    # soft-deleting a seeded base table hides it from the dropdown
    options = client.get("/reference/ora2pg_tables", headers=auth_headers).json()["options"]
    f4101 = next(o for o in options if o["value"] == "V2_PRO_F4101")
    assert client.delete(f"/reference/ora2pg_tables/{f4101['id']}", headers=auth_headers).status_code == 204
    names = [t["table"] for t in client.get("/ora2pg/tables", headers=auth_headers).json()["tables"]]
    assert "V2_PRO_F4101" not in names and len(names) == 39
