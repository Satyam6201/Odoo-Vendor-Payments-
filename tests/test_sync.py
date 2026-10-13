import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from app import app, init_db, fetch_and_store_payments


@pytest.fixture
def temp_db(monkeypatch):
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    monkeypatch.setattr("app.DB_PATH", db_path)
    init_db()
    yield db_path
    if db_path.exists():
        db_path.unlink()


def test_init_db(temp_db):
    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='payments';")
    assert cursor.fetchone() is not None
    conn.close()


def test_fetch_and_store_strictly_paid_outbound(temp_db, monkeypatch):
    monkeypatch.setattr("app.ODOO_MCP_KEY", "mock_key")

    mock_records = [
        {
            "id": 1,
            "name": "PAY00001",
            "partner_id": [3, "Ankush Bisht"],
            "amount": 1234567.0,
            "currency_id": [20, "INR"],
            "date": "2026-10-13",
            "journal_id": [30, "icici Bank"],
            "payment_method_line_id": [11, "Manual Payment"],
            "payment_type": "outbound",
            "state": "paid",
        },
        {
            "id": 7,
            "name": "PAY00006",
            "partner_id": [33, "David Miller"],
            "amount": 55.0,
            "currency_id": [20, "INR"],
            "date": "2026-10-13",
            "journal_id": [30, "icici Bank"],
            "payment_method_line_id": [11, "Manual Payment"],
            "payment_type": "outbound",
            "state": "paid",
        },
        {
            "id": 6,
            "name": "PAY00006_CANCEL",
            "partner_id": False,
            "amount": 0.0,
            "currency_id": [20, "INR"],
            "date": "2026-10-13",
            "journal_id": [30, "icici Bank"],
            "payment_method_line_id": [11, "Manual Payment"],
            "payment_type": "outbound",
            "state": "canceled",
        },
        {
            "id": 10,
            "name": "CUST00001",
            "partner_id": [5, "Customer One"],
            "amount": 500.0,
            "currency_id": [20, "INR"],
            "date": "2026-10-13",
            "journal_id": [30, "icici Bank"],
            "payment_method_line_id": [11, "Manual Payment"],
            "payment_type": "inbound",
            "state": "paid",
        },
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_records

    with patch("requests.post", return_value=mock_resp):
        count = fetch_and_store_payments()

    assert count == 4

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT odoo_id, name, amount, state FROM payments ORDER BY odoo_id;")
    rows = cursor.fetchall()
    conn.close()

    assert len(rows) == 2
    assert rows[0][0] == 1
    assert rows[0][3] == "paid"
    assert rows[1][0] == 7
    assert rows[1][3] == "paid"


def test_duplicate_prevention(temp_db, monkeypatch):
    monkeypatch.setattr("app.ODOO_MCP_KEY", "mock_key")

    mock_records = [
        {
            "id": 5,
            "name": "PAY00005",
            "partner_id": [3, "Ankush Bisht"],
            "amount": 23.0,
            "currency_id": [20, "INR"],
            "date": "2026-10-13",
            "journal_id": [30, "icici Bank"],
            "payment_method_line_id": [11, "Manual Payment"],
            "payment_type": "outbound",
            "state": "paid",
        }
    ]

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_records

    with patch("requests.post", return_value=mock_resp):
        fetch_and_store_payments()
        fetch_and_store_payments()

    conn = sqlite3.connect(temp_db)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM payments WHERE odoo_id = 5;")
    count = cursor.fetchone()[0]
    conn.close()

    assert count == 1


def test_web_routes(temp_db):
    client = app.test_client()

    res = client.get("/")
    assert res.status_code == 200
    assert b"Vendor Payments" in res.data

    api_res = client.get("/api/payments")
    assert api_res.status_code == 200
    data = api_res.get_json()
    assert isinstance(data, list)
