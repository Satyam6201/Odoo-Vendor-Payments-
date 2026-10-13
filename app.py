import os
import sqlite3
from pathlib import Path
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
import requests

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "payments.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

ODOO_URL = os.environ.get("ODOO_URL", "https://takneekiinfocom.odoo.com").rstrip("/")
ODOO_MCP_KEY = os.environ.get("ODOO_MCP_KEY", "").strip()
ODOO_DB = os.environ.get("ODOO_DB", "takneekiinfocom")
PORT = int(os.environ.get("PORT", "5000"))

app = Flask(__name__)
app.secret_key = os.urandom(24)


def init_db():
    conn = sqlite3.connect(DB_PATH)
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                odoo_id INTEGER UNIQUE NOT NULL,
                name TEXT,
                vendor_name TEXT,
                amount REAL NOT NULL DEFAULT 0.0,
                currency TEXT NOT NULL DEFAULT 'INR',
                payment_date TEXT,
                journal TEXT,
                payment_method TEXT,
                state TEXT,
                synced_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
        """)
    conn.close()


def fetch_and_store_payments():
    if not ODOO_MCP_KEY:
        raise ValueError("ODOO_MCP_KEY is not set.")

    headers = {
        "Authorization": f"bearer {ODOO_MCP_KEY}",
        "Content-Type": "application/json",
        "X-Odoo-Database": ODOO_DB,
    }

    payload = {
        "domain": [["payment_type", "=", "outbound"], ["state", "=", "paid"]],
        "fields": [
            "id", "name", "partner_id", "amount", "currency_id",
            "date", "journal_id", "payment_method_line_id", "state", "payment_type"
        ],
        "order": "id desc",
    }

    url = f"{ODOO_URL}/json/2/account.payment/search_read"
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=25)
        res.raise_for_status()
    except requests.exceptions.ConnectionError as e:
        if "NameResolutionError" in str(e) or "Temporary failure in name resolution" in str(e):
            raise ConnectionError("DNS / Internet Error: Could not resolve takneekiinfocom.odoo.com.") from e
        raise ConnectionError(f"Failed to connect to Odoo server at {ODOO_URL}: {e}") from e
    except requests.exceptions.Timeout as e:
        raise TimeoutError(f"Connection timed out contacting Odoo server at {ODOO_URL}.") from e
    except requests.exceptions.HTTPError as e:
        if res.status_code == 401:
            raise PermissionError("Odoo Authentication Error (401): Invalid or expired API Key.") from e
        raise RuntimeError(f"Odoo HTTP Error {res.status_code}: {res.text[:200]}") from e

    records = res.json()

    conn = sqlite3.connect(DB_PATH)
    with conn:
        for r in records:
            if r.get("payment_type") != "outbound" or r.get("state") != "paid":
                continue

            vendor = r["partner_id"][1] if isinstance(r.get("partner_id"), (list, tuple)) else "Unknown Vendor"
            currency = r["currency_id"][1] if isinstance(r.get("currency_id"), (list, tuple)) else "INR"
            journal = r["journal_id"][1] if isinstance(r.get("journal_id"), (list, tuple)) else "—"
            method = r["payment_method_line_id"][1] if isinstance(r.get("payment_method_line_id"), (list, tuple)) else "Manual"

            conn.execute("""
                INSERT INTO payments (
                    odoo_id, name, vendor_name, amount, currency,
                    payment_date, journal, payment_method, state, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
                ON CONFLICT(odoo_id) DO UPDATE SET
                    name=excluded.name,
                    vendor_name=excluded.vendor_name,
                    amount=excluded.amount,
                    currency=excluded.currency,
                    payment_date=excluded.payment_date,
                    journal=excluded.journal,
                    payment_method=excluded.payment_method,
                    state=excluded.state,
                    synced_at=datetime('now');
            """, (
                r["id"],
                r.get("name") or "—",
                vendor,
                float(r.get("amount") or 0.0),
                currency,
                r.get("date") or "—",
                journal,
                method,
                r.get("state") or "paid"
            ))
    conn.close()
    return len(records)


@app.route("/", methods=["GET"])
def index():
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    count_row = conn.execute("SELECT COUNT(*) as cnt FROM payments").fetchone()
    if count_row["cnt"] == 0 and ODOO_MCP_KEY:
        try:
            fetch_and_store_payments()
        except Exception as e:
            flash(f"Error fetching from Odoo: {e}", "danger")

    search = request.args.get("q", "").strip()
    if search:
        query = """
            SELECT * FROM payments
            WHERE vendor_name LIKE ? OR name LIKE ? OR journal LIKE ?
            ORDER BY odoo_id DESC;
        """
        param = f"%{search}%"
        rows = conn.execute(query, (param, param, param)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM payments ORDER BY odoo_id DESC;").fetchall()

    payments = [dict(r) for r in rows]

    curr_rows = conn.execute("""
        SELECT currency, SUM(amount) as total, COUNT(*) as cnt
        FROM payments
        GROUP BY currency;
    """).fetchall()
    currency_totals = [{"currency": r["currency"], "total": r["total"], "count": r["cnt"]} for r in curr_rows]

    last_synced = payments[0].get("synced_at") if payments else None

    conn.close()
    return render_template(
        "index.html",
        payments=payments,
        currency_totals=currency_totals,
        total_count=len(payments),
        search=search,
        last_synced=last_synced,
        odoo_url=ODOO_URL,
    )


@app.route("/sync", methods=["POST", "GET"])
def sync():
    try:
        count = fetch_and_store_payments()
        flash(f"Successfully synchronized {count} paid vendor payments from Odoo Online!", "success")
    except Exception as e:
        flash(f"Sync failed: {e}", "danger")
    return redirect(url_for("index"))


@app.route("/api/payments", methods=["GET"])
def api_payments():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM payments ORDER BY odoo_id DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    print(f"Starting Odoo Payment Fetcher on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, debug=False)
