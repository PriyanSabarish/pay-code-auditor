"""End-to-end tests for the FastAPI contract, run against the fake-data server
(FAKE_DATA=1, the default) so they need no LLM key and no network access.
"""

from __future__ import annotations

import io
import time

import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.config import FAKE_STEP_DELAY_SECONDS

PAYCODES_CSV = (
    "code,name,description,counts_for_super,payroll_category\n"
    "ORD HRS,Ordinary Hours,,Y,Wages\n"
    "SITE ALLOW,Site Allowance,,N,Allowance\n"
)

PAYRUNS_CSV = (
    "pay_date,code,total_amount,employees_paid,overtime_hours\n"
    "2026-07-03,ORD HRS,10000,25,\n"
    "2026-07-17,ORD HRS,10000,25,\n"
    "2026-07-03,SITE ALLOW,1125.00,25,\n"
    "2026-07-17,SITE ALLOW,1125.00,25,\n"
)


@pytest.fixture()
def client():
    return TestClient(app)


def _upload(client, paycodes=PAYCODES_CSV, payruns=PAYRUNS_CSV, award_id="general_retail_2020", mode="full"):
    return client.post(
        "/api/audits",
        files={
            "paycodes": ("paycodes.csv", io.BytesIO(paycodes.encode()), "text/csv"),
            "payruns": ("payruns.csv", io.BytesIO(payruns.encode()), "text/csv"),
        },
        data={"award_id": award_id, "mode": mode},
    )


def _wait_for_status(client, audit_id, statuses, timeout=5.0):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        resp = client.get(f"/api/audits/{audit_id}")
        last = resp.json()
        if last["status"] in statuses:
            return last
        time.sleep(FAKE_STEP_DELAY_SECONDS / 2)
    raise AssertionError(f"timed out waiting for status in {statuses}, last seen: {last}")


def test_list_awards(client):
    resp = client.get("/api/awards")
    assert resp.status_code == 200
    ids = {a["id"] for a in resp.json()}
    assert "general_retail_2020" in ids


def test_create_audit_rejects_bad_paycodes(client):
    resp = _upload(client, paycodes="code,name\nA,B\n")
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"][0]["loc"][-1] == "paycodes"


def test_create_audit_rejects_unknown_award(client):
    resp = _upload(client, award_id="not_a_real_award")
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["loc"][-1] == "award_id"


def test_full_fake_audit_flow_pauses_and_resumes(client):
    resp = _upload(client)
    assert resp.status_code == 202
    audit_id = resp.json()["audit_id"]

    state = _wait_for_status(client, audit_id, {"awaiting_input", "complete"})
    assert state["status"] == "awaiting_input"
    question = state["pending_question"]
    assert question is not None
    assert question["code"] == "RDO PAYOUT"

    answer_resp = client.post(
        f"/api/audits/{audit_id}/answer",
        json={"question_id": question["id"], "answer": "No, generated in lieu of overtime."},
    )
    assert answer_resp.status_code == 200

    state = _wait_for_status(client, audit_id, {"complete"})
    codes = {v["code"] for v in state["verdicts"]}
    assert {"ORD HRS", "SITE ALLOW", "RDO PAYOUT", "COMM Q3"}.issubset(codes)

    site_allow = next(v for v in state["verdicts"] if v["code"] == "SITE ALLOW")
    assert site_allow["status"] == "should_count"
    assert len(site_allow["investigation"]) == 5
    assert site_allow["impact"]["super_amount"] == 3510.0


def test_answer_before_awaiting_input_is_rejected(client):
    resp = _upload(client)
    audit_id = resp.json()["audit_id"]
    resp = client.post(
        f"/api/audits/{audit_id}/answer",
        json={"question_id": "bogus", "answer": "no"},
    )
    assert resp.status_code == 409


def test_verdict_and_report_and_letter_endpoints(client):
    resp = _upload(client)
    audit_id = resp.json()["audit_id"]
    state = _wait_for_status(client, audit_id, {"awaiting_input"})
    client.post(
        f"/api/audits/{audit_id}/answer",
        json={"question_id": state["pending_question"]["id"], "answer": "ordinary time"},
    )
    _wait_for_status(client, audit_id, {"complete"})

    verdict_resp = client.post(
        f"/api/audits/{audit_id}/verdicts/SITE ALLOW",
        json={"decision": "approved", "note": "Confirmed with the bookkeeper."},
    )
    assert verdict_resp.status_code == 200
    assert verdict_resp.json()["reviewer_decision"] == "approved"

    report_resp = client.get(f"/api/audits/{audit_id}/report.csv")
    assert report_resp.status_code == 200
    assert "SITE ALLOW" in report_resp.text

    letter_resp = client.get(f"/api/audits/{audit_id}/letter/SITE ALLOW")
    assert letter_resp.status_code == 200
    assert letter_resp.json()["code"] == "SITE ALLOW"


def test_get_unknown_audit_is_404(client):
    resp = client.get("/api/audits/does-not-exist")
    assert resp.status_code == 404
