"""
Regression tests for the smart-garage API.
Runs in mock + test mode (no GPIO, no real ntfy calls).
"""
import os
import sqlite3
import tempfile
import pathlib

# Must be set before importing the app so env vars are read correctly
os.environ["MOCK"] = "true"
os.environ["TEST"] = "true"
os.environ["API_TOKEN"] = "testtoken"
# NTFY_TOPIC not required when TEST=true

import pytest
from fastapi.testclient import TestClient

import src.api as api_module
from src.api import app

TOKEN = "testtoken"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
BAD_AUTH = {"Authorization": "Bearer wrongtoken"}


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    """Each test gets its own in-memory token map and a fresh temp DB."""
    monkeypatch.setattr(api_module, "USERS", {TOKEN: "TestUser"})
    db = tmp_path / "test.db"
    monkeypatch.setattr(api_module, "DB_PATH", db)
    api_module._init_db()
    # Reset shared state between tests
    api_module._mock_state["status"] = "closed"
    api_module._trigger_time["at"] = None
    api_module._snooze["until"] = None
    yield


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------

class TestHealth:
    def test_returns_ok(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200

    def test_mock_flag_true(self, client):
        assert client.get("/api/health").json()["mock"] is True

    def test_no_auth_required(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

class TestAuth:
    def test_valid_token_accepted(self, client):
        r = client.get("/api/status", headers=AUTH)
        assert r.status_code == 200

    def test_invalid_token_rejected(self, client):
        r = client.get("/api/status", headers=BAD_AUTH)
        assert r.status_code == 401

    def test_missing_token_rejected(self, client):
        r = client.get("/api/status")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

class TestStatus:
    def test_initial_state_is_closed(self, client):
        r = client.get("/api/status", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["state"] == "closed"

    def test_reflects_mock_state(self, client):
        api_module._mock_state["status"] = "open"
        r = client.get("/api/status", headers=AUTH)
        assert r.json()["state"] == "open"


# ---------------------------------------------------------------------------
# Trigger
# ---------------------------------------------------------------------------

class TestTrigger:
    def test_returns_triggered_true(self, client):
        r = client.post("/api/trigger", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["triggered"] is True

    def test_requires_auth(self, client):
        assert client.post("/api/trigger").status_code == 401
        assert client.post("/api/trigger", headers=BAD_AUTH).status_code == 401

    def test_logs_event_to_db(self, client):
        client.post("/api/trigger", headers=AUTH)
        con = sqlite3.connect(api_module.DB_PATH)
        rows = con.execute("SELECT user, action FROM events").fetchall()
        con.close()
        assert len(rows) == 1
        assert rows[0] == ("TestUser", "trigger")

    def test_updates_trigger_time(self, client):
        assert api_module._trigger_time["at"] is None
        client.post("/api/trigger", headers=AUTH)
        assert api_module._trigger_time["at"] is not None


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

class TestHistory:
    def test_empty_initially(self, client):
        r = client.get("/api/history", headers=AUTH)
        assert r.status_code == 200
        assert r.json() == []

    def test_requires_auth(self, client):
        assert client.get("/api/history").status_code == 401

    def test_records_appear_after_trigger(self, client):
        client.post("/api/trigger", headers=AUTH)
        events = client.get("/api/history", headers=AUTH).json()
        assert len(events) == 1
        assert events[0]["action"] == "trigger"
        assert events[0]["user"] == "TestUser"

    def test_returned_newest_first(self, client):
        api_module._log_event("TestUser", "trigger", "closed")
        api_module._log_event("physical", "state_change", "open")
        events = client.get("/api/history", headers=AUTH).json()
        assert events[0]["action"] == "state_change"
        assert events[1]["action"] == "trigger"

    def test_limit_param(self, client):
        for _ in range(5):
            api_module._log_event("TestUser", "trigger", "closed")
        events = client.get("/api/history?limit=3", headers=AUTH).json()
        assert len(events) == 3

    def test_event_fields_present(self, client):
        client.post("/api/trigger", headers=AUTH)
        event = client.get("/api/history", headers=AUTH).json()[0]
        assert {"timestamp", "user", "action", "state"} == set(event.keys())


# ---------------------------------------------------------------------------
# Snooze
# ---------------------------------------------------------------------------

from datetime import datetime, timedelta


class TestSnooze:
    def test_requires_auth(self, client):
        assert client.post("/api/snooze?minutes=60").status_code == 401
        assert client.post("/api/snooze?minutes=60", headers=BAD_AUTH).status_code == 401
        assert client.delete("/api/snooze").status_code == 401

    def test_snooze_sets_state(self, client):
        assert api_module.is_snoozed() is False
        r = client.post("/api/snooze?minutes=120", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["minutes"] == 120
        assert api_module.is_snoozed() is True

    def test_status_reflects_snooze(self, client):
        assert client.get("/api/status", headers=AUTH).json()["snoozed_until"] is None
        client.post("/api/snooze?minutes=60", headers=AUTH)
        assert client.get("/api/status", headers=AUTH).json()["snoozed_until"] is not None

    def test_minutes_required(self, client):
        assert client.post("/api/snooze", headers=AUTH).status_code == 422

    def test_minutes_out_of_range_rejected(self, client):
        assert client.post("/api/snooze?minutes=0", headers=AUTH).status_code == 422
        assert client.post("/api/snooze?minutes=721", headers=AUTH).status_code == 422
        assert api_module.is_snoozed() is False

    def test_cancel_clears_snooze(self, client):
        client.post("/api/snooze?minutes=60", headers=AUTH)
        assert api_module.is_snoozed() is True
        r = client.delete("/api/snooze", headers=AUTH)
        assert r.status_code == 200
        assert r.json()["snoozed_until"] is None
        assert api_module.is_snoozed() is False

    def test_snooze_logged_to_history(self, client):
        client.post("/api/snooze?minutes=90", headers=AUTH)
        event = client.get("/api/history", headers=AUTH).json()[0]
        assert event["action"] == "snooze"
        assert event["user"] == "TestUser"
        assert event["state"] == "90"

    def test_expired_snooze_reads_as_inactive(self, client):
        api_module._snooze["until"] = datetime.utcnow() - timedelta(minutes=1)
        assert api_module.is_snoozed() is False
        assert client.get("/api/status", headers=AUTH).json()["snoozed_until"] is None

    def test_state_change_to_closed_clears_snooze(self, client):
        """A confirmed close (GPIO callback path) should drop an active snooze."""
        client.post("/api/snooze?minutes=60", headers=AUTH)
        assert api_module.is_snoozed() is True
        api_module._on_state_change("closed")
        assert api_module.is_snoozed() is False

    def test_state_change_to_open_keeps_snooze(self, client):
        client.post("/api/snooze?minutes=60", headers=AUTH)
        api_module._on_state_change("open")
        assert api_module.is_snoozed() is True
