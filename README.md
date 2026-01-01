# Warehouse Suite (KISS) — Ops Forms + Labels + KPI Tracker

Two small Flask apps you can deploy/run separately.

## 1) Ops + Department Forms + Labels (port 5000)
- Department tabs (Receiving/Putaway/Picking/Packing/Shipping/Inventory/Returns-OSD)
- Fast logging into SQLite (`ops.db`)
- Export today's entries as CSV
- Label PDF generator (4x6), **no barcodes**
  - Item # (6 digits) first
  - Quantity second
  - Location third (A–L + XA + XG)
  - Date received, Checked by
  - Bulk: 1 label per pallet
  - Non-bulk: 1 label per item (prints `quantity` copies)

Run:
```bash
cd ops_app
pip install -r requirements.txt
python app.py
```

## 2) KPI Tracker (port 5001)
- Log work quantities + log shift start/end
- Computes per-person daily totals and hourly rate
- Sets target as **median items/hour** for that department/day
- Shows who meets/surpasses the target

Run:
```bash
cd kpi_app
pip install -r requirements.txt
python app.py
```

## Deploy (simple)
- Works on Render/Railway/Fly/Heroku-like platforms
- Each app has its own `requirements.txt`
