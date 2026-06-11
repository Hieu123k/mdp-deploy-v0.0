from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.data_model import DataModel
from app.services.outbound_service import query_type_b_record_by_key
from tests.test_data_models import type_b_payload


def seed_staging(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post("/admin/demo/seed-procurement-staging", headers=auth_headers)
    assert response.status_code == 200


def purchase_order_summary_payload() -> dict:
    return {
        "name": "purchase_order_summary",
        "display_name": "Purchase Order Summary",
        "type": "B",
        "category": "procurement",
        "description": "Curated purchase order summary from JDE staging data",
        "source_system": "JDE ERP",
        "primary_key": "po_no",
        "attributes": [
            {
                "name": "po_no",
                "display_name": "Purchase Order Number",
                "data_type": "text",
                "required": True,
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "po_no",
                "is_primary_key": True,
            },
            {
                "name": "supplier_name",
                "display_name": "Supplier Name",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "supplier_name",
            },
            {
                "name": "line_count",
                "display_name": "Line Count",
                "data_type": "integer",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "line_count",
            },
            {
                "name": "payment_status_summary",
                "display_name": "Payment Status Summary",
                "data_type": "text",
                "source_schema": "mdp_staging",
                "source_table": "vw_jde_purchase_order_summary",
                "source_column": "payment_status_summary",
            },
        ],
    }


def test_create_valid_type_b_supplier_model(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post("/data-models", headers=auth_headers, json=type_b_payload())

    assert response.status_code == 201
    body = response.json()
    assert body["type"] == "B"
    assert body["generated_table"] is None
    assert body["source_schema"] == "mdp_staging"
    assert body["source_table"] == "stg_jde_supplier"


def test_validate_mapping_success(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=type_b_payload(),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["mapped_columns"][0]["source_column"] == "supplier_code"


def test_attribute_name_can_differ_from_source_column(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["name"] = "supplier_alias"
    payload["primary_key"] = "supplier_no"
    payload["attributes"][0]["name"] = "supplier_no"

    validate_response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )
    preview_response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=payload,
    )

    assert validate_response.status_code == 200
    assert validate_response.json()["mapped_columns"][0]["attribute"] == "supplier_no"
    assert validate_response.json()["mapped_columns"][0]["source_column"] == "supplier_code"
    assert preview_response.status_code == 200
    assert preview_response.json()["data"][0]["supplier_no"] == "SUP-1001"
    assert "supplier_code" not in preview_response.json()["data"][0]


def test_validate_mapping_fails_when_source_table_missing(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_table"] = "missing_table"
    payload["attributes"][1]["source_table"] = "missing_table"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Table not found" in str(response.json()["detail"])


def test_validate_mapping_fails_when_source_column_missing(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_column"] = "missing_column"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Source column not found" in str(response.json()["detail"])


def test_validate_mapping_fails_when_source_column_not_configured(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0].pop("source_column")

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "Type B attributes require source_column" in str(response.json()["detail"])


def test_validate_mapping_fails_for_invalid_identifier(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    payload = type_b_payload()
    payload["attributes"][0]["source_schema"] = "mdp_staging;"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422


def test_validate_mapping_fails_for_multiple_source_tables_without_join(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    # Prompt 38: multiple source tables are now allowed — but only when joined. A second table with
    # no relationship to the base is an ORPHAN and must be rejected.
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][1]["source_table"] = "stg_jde_po_header"
    payload["attributes"][1]["source_column"] = "po_no"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "not joined to the base" in str(response.json()["detail"])


def test_validate_mapping_fails_for_incompatible_data_type(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["data_type"] = "integer"

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "incompatible" in str(response.json()["detail"])


def test_preview_unsaved_type_b_mapping_returns_supplier_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=type_b_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert body["data"][0]["supplier_code"] == "SUP-1001"


def test_preview_saved_type_b_model_returns_supplier_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    create_response = client.post("/data-models", headers=auth_headers, json=type_b_payload())
    data_model_id = create_response.json()["id"]

    response = client.get(
        f"/data-models/{data_model_id}/mapped-preview",
        headers=auth_headers,
    )

    assert response.status_code == 200
    assert response.json()["data"][0]["supplier_name"] == "ABC Industrial Supplies"


def test_type_b_requires_primary_key(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["primary_key"] = None
    payload["attributes"][0]["is_primary_key"] = False

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422
    assert "primary_key" in str(response.json()["detail"])


def test_type_b_primary_key_must_reference_valid_mapping(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["attributes"][0]["source_column"] = "missing_column"

    response = client.post("/data-models", headers=auth_headers, json=payload)

    assert response.status_code == 422
    assert "Primary key attribute must map to an existing compatible source_column" in str(
        response.json()["detail"]
    )


def test_type_b_primary_key_non_unique_column_rejected(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    # Prompt 38 (MT6): the primary key must uniquely identify a row. `country` repeats across
    # suppliers, so it is now a hard error (previously only a nullable warning). The nullable-PK
    # WARNING path remains covered by test_validate_mapping_view_primary_key_nullable_returns_warning.
    seed_staging(client, auth_headers)
    payload = type_b_payload()
    payload["primary_key"] = "country"
    payload["attributes"][0]["is_primary_key"] = False
    payload["attributes"][1] = {
        "name": "country",
        "display_name": "Country",
        "data_type": "text",
        "source_schema": "mdp_staging",
        "source_table": "stg_jde_supplier",
        "source_column": "country",
    }

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=payload,
    )

    assert response.status_code == 422
    assert "not unique" in str(response.json()["detail"])


def test_validate_mapping_view_primary_key_nullable_returns_warning(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=purchase_order_summary_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_table"] == "vw_jde_purchase_order_summary"
    assert {
        "field": "primary_key",
        "message": (
            "Primary key source column is from a view. Nullability cannot be reliably "
            "enforced by information_schema."
        ),
    } in body["warnings"]


def test_purchase_order_summary_view_preview_returns_rows(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    seed_staging(client, auth_headers)

    response = client.post(
        "/data-models/type-b/preview",
        headers=auth_headers,
        json=purchase_order_summary_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 5
    assert body["warnings"]
    first_po = next(row for row in body["data"] if row["po_no"] == "PO-2026-0001")
    assert first_po["supplier_name"] == "ABC Industrial Supplies"
    assert first_po["line_count"] == 2


def test_type_b_requests_require_authentication(client: TestClient) -> None:
    validate_response = client.post(
        "/data-models/type-b/validate-mapping",
        json=type_b_payload(),
    )
    preview_response = client.post(
        "/data-models/type-b/preview",
        json=type_b_payload(),
    )

    assert validate_response.status_code == 401
    assert preview_response.status_code == 401


# --- Prompt 38: multi-table Type B mapping (MT1–MT8) ----------------------------------------------

def seed_mt_tables(db_session: Session) -> None:
    """Three joinable fixtures: dm_t_head (base, UNIQUE head_id) → dm_t_lookup (N:1, UNIQUE
    lookup_code) and dm_t_lines (1:N, head_id REPEATS → fan-out). Created unqualified in the test DB
    (schema is nominal on sqlite); attributes reference them via source_schema='mdp_staging'."""
    for ddl in (
        "CREATE TABLE IF NOT EXISTS dm_t_head (head_id TEXT PRIMARY KEY, lookup_code TEXT, title TEXT)",
        "CREATE TABLE IF NOT EXISTS dm_t_lookup (lookup_code TEXT, lookup_name TEXT, ref_num INTEGER)",
        "CREATE TABLE IF NOT EXISTS dm_t_lines (head_id TEXT, line_no INTEGER, qty INTEGER)",
    ):
        db_session.execute(text(ddl))
    db_session.execute(text("DELETE FROM dm_t_head"))
    db_session.execute(text("DELETE FROM dm_t_lookup"))
    db_session.execute(text("DELETE FROM dm_t_lines"))
    db_session.execute(text("INSERT INTO dm_t_head VALUES ('h1','lc1','Head One'),('h2','lc2','Head Two')"))
    db_session.execute(text("INSERT INTO dm_t_lookup VALUES ('lc1','Alpha',1),('lc2','Beta',2)"))
    db_session.execute(text("INSERT INTO dm_t_lines VALUES ('h1',1,10),('h1',2,20),('h2',1,5)"))
    db_session.commit()


def _attr(name, col, *, table="dm_t_head", dtype="text", pk=False, schema="mdp_staging"):
    return {
        "name": name, "data_type": dtype, "source_schema": schema,
        "source_table": table, "source_column": col, "is_primary_key": pk,
    }


def _mt_model(name, attributes, relationships=None, primary_key="head_id"):
    return {
        "name": name, "display_name": name, "type": "B", "primary_key": primary_key,
        "attributes": attributes, "relationships": relationships or [],
    }


JOIN_HEAD_LOOKUP = {
    "type": "left",
    "left": {"table": "dm_t_head", "column": "lookup_code"},
    "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "lookup_code"},
}


def test_mt1_n_to_1_join_ok(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    payload = _mt_model("mt1_head", [
        _attr("head_id", "head_id", pk=True),
        _attr("title", "title"),
        _attr("lookup_name", "lookup_name", table="dm_t_lookup"),
    ], [JOIN_HEAD_LOOKUP])
    r = client.post("/data-models/type-b/preview", headers=auth_headers, json=payload)
    assert r.status_code == 200, r.json()
    body = r.json()
    assert body["count"] == 2
    by_id = {row["head_id"]: row for row in body["data"]}
    assert by_id["h1"]["lookup_name"] == "Alpha"
    assert by_id["h2"]["lookup_name"] == "Beta"


def test_mt2_outbound_by_key(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    payload = _mt_model("mt2_head", [
        _attr("head_id", "head_id", pk=True),
        _attr("lookup_name", "lookup_name", table="dm_t_lookup"),
    ], [JOIN_HEAD_LOOKUP])
    created = client.post("/data-models", headers=auth_headers, json=payload)
    assert created.status_code == 201, created.json()
    model = db_session.execute(select(DataModel).where(DataModel.name == "mt2_head")).scalar_one()
    record = query_type_b_record_by_key(db_session, model=model, key="h1")
    assert record is not None
    assert record["lookup_name"] == "Alpha"


def test_mt3_fanout_blocked_then_allowed(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    join_lines = {
        "type": "left",
        "left": {"table": "dm_t_head", "column": "head_id"},
        "right": {"schema": "mdp_staging", "table": "dm_t_lines", "column": "head_id"},
    }
    attrs = [_attr("head_id", "head_id", pk=True), _attr("qty", "qty", table="dm_t_lines", dtype="integer")]
    blocked = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt3b", attrs, [join_lines]))
    assert blocked.status_code == 422
    assert "fan out" in str(blocked.json()["detail"])

    allowed = client.post(
        "/data-models/type-b/preview", headers=auth_headers,
        json=_mt_model("mt3a", attrs, [{**join_lines, "allow_fanout": True}]),
    )
    assert allowed.status_code == 200, allowed.json()
    assert allowed.json()["count"] == 3  # h1 x2 lines + h2 x1
    assert any(w["field"].startswith("relationships") for w in allowed.json()["warnings"])


def test_mt4_orphan_table_rejected(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    attrs = [_attr("head_id", "head_id", pk=True), _attr("lookup_name", "lookup_name", table="dm_t_lookup")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt4", attrs, []))
    assert r.status_code == 422
    assert "not joined to the base" in str(r.json()["detail"])


def test_mt5_join_type_mismatch_rejected(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    bad_join = {
        "type": "left",
        "left": {"table": "dm_t_head", "column": "lookup_code"},      # text
        "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "ref_num"},  # integer
    }
    attrs = [_attr("head_id", "head_id", pk=True), _attr("lookup_name", "lookup_name", table="dm_t_lookup")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt5", attrs, [bad_join]))
    assert r.status_code == 422
    assert "type mismatch" in str(r.json()["detail"])


def test_mt6_non_unique_primary_key_rejected(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    # base = dm_t_lines, PK head_id repeats → not unique
    attrs = [_attr("head_id", "head_id", table="dm_t_lines", pk=True), _attr("qty", "qty", table="dm_t_lines", dtype="integer")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt6", attrs, []))
    assert r.status_code == 422
    assert "not unique" in str(r.json()["detail"])


def test_mt7_single_table_non_regression(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    attrs = [_attr("head_id", "head_id", pk=True), _attr("title", "title")]
    r = client.post("/data-models/type-b/preview", headers=auth_headers, json=_mt_model("mt7", attrs, []))
    assert r.status_code == 200, r.json()
    assert r.json()["count"] == 2


def test_mt8_injection_in_join_rejected(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    seed_mt_tables(db_session)
    evil = {
        "type": "left",
        "left": {"table": "dm_t_head", "column": "lookup_code"},
        "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "lookup_code; drop table dm_t_head"},
    }
    attrs = [_attr("head_id", "head_id", pk=True), _attr("lookup_name", "lookup_name", table="dm_t_lookup")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt8", attrs, [evil]))
    assert r.status_code == 422
    # the injection never executed — the table is intact
    assert db_session.execute(text("SELECT count(*) FROM dm_t_head")).scalar() == 2


def test_mt9_conflicting_duplicate_join_rejected(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    # Prompt 38 review fix: two edges to the same table that DIFFER (type/ON) must be a hard error,
    # not a silently-dropped edge (which would change which rows the query returns).
    seed_mt_tables(db_session)
    j1 = {"type": "left", "left": {"table": "dm_t_head", "column": "lookup_code"},
          "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "lookup_code"}}
    j2 = {"type": "inner", "left": {"table": "dm_t_head", "column": "lookup_code"},
          "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "lookup_code"}}
    attrs = [_attr("head_id", "head_id", pk=True), _attr("lookup_name", "lookup_name", table="dm_t_lookup")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt9", attrs, [j1, j2]))
    assert r.status_code == 422
    assert "conflicting join" in str(r.json()["detail"])


def test_mt10_inner_join_warns(client: TestClient, auth_headers: dict[str, str], db_session: Session) -> None:
    # Prompt 38 review fix: an INNER join (which can drop base rows) is no longer silent — it warns.
    seed_mt_tables(db_session)
    j = {"type": "inner", "left": {"table": "dm_t_head", "column": "lookup_code"},
         "right": {"schema": "mdp_staging", "table": "dm_t_lookup", "column": "lookup_code"}}
    attrs = [_attr("head_id", "head_id", pk=True), _attr("lookup_name", "lookup_name", table="dm_t_lookup")]
    r = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=_mt_model("mt10", attrs, [j]))
    assert r.status_code == 200, r.json()
    assert any("INNER JOIN" in w["message"] for w in r.json()["warnings"])


# --- Prompt 42: uuid→text mapping (D) + multi-table uuid join E2E (U5, U6) -----------------------

def seed_uuid_tables(db_session: Session) -> None:
    """Two joinable fixtures with uuid keys: dm_id_mount (UNIQUE id_mount) ← dm_id_name (id_mount FK).
    Mirrors the prompt-42 U6 scenario (join dm_id_name → dm_id_mount via id_mount)."""
    db_session.execute(text("CREATE TABLE IF NOT EXISTS dm_id_mount (id_mount uuid PRIMARY KEY, mount_name text)"))
    db_session.execute(text("CREATE TABLE IF NOT EXISTS dm_id_name (id_name uuid PRIMARY KEY, id_mount uuid, full_name text)"))
    db_session.execute(text("DELETE FROM dm_id_mount"))
    db_session.execute(text("DELETE FROM dm_id_name"))
    db_session.execute(text(
        "INSERT INTO dm_id_mount VALUES "
        "('11111111-1111-1111-1111-111111111111','Mount A'),"
        "('22222222-2222-2222-2222-222222222222','Mount B')"
    ))
    db_session.execute(text(
        "INSERT INTO dm_id_name VALUES "
        "('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa','11111111-1111-1111-1111-111111111111','Alice'),"
        "('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb','22222222-2222-2222-2222-222222222222','Bob')"
    ))
    db_session.commit()


def test_u5_uuid_column_maps_to_text(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    """D: a uuid source column (e.g. surrogate `id`) links as a text attribute — validation no longer
    fails with 'Unsupported source data type: uuid'."""
    seed_uuid_tables(db_session)
    attrs = [
        _attr("id_mount", "id_mount", table="dm_id_mount", dtype="text", pk=True),
        _attr("mount_name", "mount_name", table="dm_id_mount", dtype="text"),
    ]
    r = client.post(
        "/data-models/type-b/validate-mapping",
        headers=auth_headers,
        json=_mt_model("u5_uuid", attrs, primary_key="id_mount"),
    )
    assert r.status_code == 200, r.json()
    assert r.json()["status"] == "success"
    assert "id_mount" in {m["attribute"] for m in r.json()["mapped_columns"]}


def test_u6_uuid_multitable_join_validate_preview_save(
    client: TestClient, auth_headers: dict[str, str], db_session: Session
) -> None:
    """U6 (backend twin of the dropdown E2E): join dm_id_name → dm_id_mount via id_mount (uuid keys),
    then Validate → Preview → Save all succeed."""
    seed_uuid_tables(db_session)
    join = {
        "type": "left",
        "left": {"table": "dm_id_name", "column": "id_mount"},
        "right": {"schema": "mdp_staging", "table": "dm_id_mount", "column": "id_mount"},
    }
    attrs = [
        _attr("id_name", "id_name", table="dm_id_name", dtype="text", pk=True),
        _attr("full_name", "full_name", table="dm_id_name", dtype="text"),
        _attr("mount_name", "mount_name", table="dm_id_mount", dtype="text"),
    ]
    payload = _mt_model("u6_id_name", attrs, [join], primary_key="id_name")

    validate = client.post("/data-models/type-b/validate-mapping", headers=auth_headers, json=payload)
    assert validate.status_code == 200, validate.json()
    assert validate.json()["status"] == "success"

    preview = client.post("/data-models/type-b/preview", headers=auth_headers, json=payload)
    assert preview.status_code == 200, preview.json()
    by_name = {row["full_name"]: row for row in preview.json()["data"]}
    assert by_name["Alice"]["mount_name"] == "Mount A"
    assert by_name["Bob"]["mount_name"] == "Mount B"

    save = client.post("/data-models", headers=auth_headers, json=payload)
    assert save.status_code == 201, save.json()
    assert save.json()["primary_key"] == "id_name"
