"""MQTT consumer — topic->model parsing, ingest via the reused inbound pipeline, error-skip,
and the status endpoint. No real broker needed (the network loop is exercised on .63)."""
import json

from sqlalchemy import text

from app.services.mqtt_consumer import derive_model_name, process_message
from tests.test_inbound import create_invoice_model, create_sqlite_generated_table


def test_derive_model_name_last_segment_and_override():
    assert derive_model_name("tipa/hcm/plant1/invoice") == "invoice"
    assert derive_model_name("tipa/hcm/plant1/invoice/") == "invoice"
    assert derive_model_name("invoice") == "invoice"
    assert derive_model_name("tipa/hcm/plant1/x", {"tipa/hcm/plant1/x": "invoice"}) == "invoice"


def test_process_message_ingests_into_type_a_model(client, auth_headers, db_session):
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)

    result = process_message(
        db_session, "tipa/hcm/plant1/invoice",
        json.dumps({"invoice_no": "MQTT-1", "amount": 50.0}).encode(),
    )
    assert result["status"] == "ingested" and result["model"] == "invoice"

    row = db_session.execute(text("SELECT invoice_no, amount FROM mdp_data.dm_invoice")).mappings().one()
    assert row["invoice_no"] == "MQTT-1" and row["amount"] == 50.0

    # a Transaction is logged, tagged as MQTT-sourced with the topic in the endpoint
    tx = db_session.execute(
        text("SELECT endpoint, source_system, direction, status FROM transactions ORDER BY created_at DESC LIMIT 1")
    ).mappings().one()
    assert tx["endpoint"] == "mqtt:tipa/hcm/plant1/invoice"
    assert tx["source_system"] == "mqtt"
    assert tx["direction"] == "inbound" and tx["status"] == "success"


def test_process_message_skips_bad_json(client, auth_headers, db_session):
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    r = process_message(db_session, "tipa/hcm/plant1/invoice", b"{not valid json")
    assert r["status"] == "skipped" and "JSON" in r["reason"]


def test_process_message_skips_non_object(client, auth_headers, db_session):
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    r = process_message(db_session, "tipa/hcm/plant1/invoice", json.dumps([1, 2, 3]).encode())
    assert r["status"] == "skipped" and "object" in r["reason"]


def test_process_message_skips_unknown_model(db_session):
    r = process_message(db_session, "tipa/hcm/plant1/does_not_exist", json.dumps({"x": 1}).encode())
    assert r["status"] == "skipped" and "unknown model" in r["reason"]


def test_process_message_skips_validation_failure(client, auth_headers, db_session):
    create_invoice_model(client, auth_headers)
    create_sqlite_generated_table(db_session)
    # invoice_no is required → missing → validation fail → skipped (not raised)
    r = process_message(db_session, "tipa/hcm/plant1/invoice", json.dumps({"amount": 1.0}).encode())
    assert r["status"] == "skipped" and r["reason"] == "validation failed"


def test_mqtt_status_endpoint_default_off(client, auth_headers):
    res = client.get("/mqtt/status", headers=auth_headers)
    assert res.status_code == 200
    body = res.json()
    assert body["configured_enabled"] is False  # default OFF
    assert body["connected"] is False
    assert "messages_received" in body and "configured_topics" in body


def test_mqtt_status_requires_auth(client):
    assert client.get("/mqtt/status").status_code == 401
