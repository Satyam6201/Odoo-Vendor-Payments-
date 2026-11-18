# Odoo Paid Vendor Payment Fetcher

Fetches completed vendor payments from Odoo Online and displays them on a local dashboard.

## Setup

```bash
cd /home/ubuntu/Desktop/odoo/odoo-payment-fetcher
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuration

Create `.env`:

```env
ODOO_MCP_KEY=your_odoo_api_key_here
ODOO_URL=https://takneekiinfocom.odoo.com
ODOO_DB=takneekiinfocom
PORT=5000
```

## Run

```bash
python app.py
```

Open: http://127.0.0.1:5000

## Tests

```bash
pytest -v
