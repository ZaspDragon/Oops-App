# app.py
import os
import re
import io
import csv
import sqlite3
from datetime import datetime, date

from flask import Flask, request, redirect, url_for, send_file, Response

# PDF (labels)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

app = Flask(__name__)

# ---------- Config ----------
DB_PATH = os.environ.get("DB_PATH", "ops.db")

# ---------- Simple HTML (KISS, blue/white) ----------
BASE_CSS = """
<style>
  :root{
    --blue:#1A5CCC;
    --blue2:#2B7BFF;
    --bg:#F5F8FF;
    --border:#D2DCF5;
    --text:#141923;
    --muted:#5A6478;
    --card:#FFFFFF;
  }
  body{margin:0;font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);}
  .top{background:var(--card);border-bottom:2px solid var(--border);padding:16px 18px;}
  .brand{font-weight:900;color:var(--blue);font-size:22px;letter-spacing:.2px;}
  .sub{color:var(--muted);font-size:13px;margin-top:4px;}
  .wrap{max-width:980px;margin:0 auto;padding:18px;}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px;}
  .card{background:var(--card);border:2px solid var(--border);border-radius:18px;padding:14px;}
  a.btn{display:inline-block;background:var(--blue);color:#fff;text-decoration:none;font-weight:800;padding:10px 12px;border-radius:14px;}
  a.btn2{display:inline-block;background:#fff;color:var(--blue);text-decoration:none;font-weight:800;padding:10px 12px;border-radius:14px;border:2px solid var(--border);}
  .row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
  h2{margin:0 0 10px 0}
  label{font-weight:800;font-size:13px}
  input,select,textarea{
    width:100%;
    padding:10px 12px;
    border-radius:14px;
    border:2px solid var(--border);
    outline:none;
    background:#fff;
    box-sizing:border-box;
    font-size:15px;
  }
  input:focus,select:focus,textarea:focus{border-color:var(--blue2)}
  .muted{color:var(--muted);font-size:13px}
  .pill{display:inline-block;padding:5px 10px;border-radius:999px;border:2px solid var(--border);background:#fff;font-weight:800;color:var(--blue);font-size:12px;}
  table{width:100%;border-collapse:collapse;background:#fff;border:2px solid var(--border);border-radius:18px;overflow:hidden}
  th,td{padding:10px;border-bottom:1px solid var(--border);font-size:13px;text-align:left}
  th{background:#EEF4FF;color:#1a2a55}
  .err{background:#fff;border:2px solid #ffd1d1;border-radius:18px;padding:14px}
  .err b{color:#b00020}
</style>
"""

def page(title, body_html):
    return f"""
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  {BASE_CSS}
</head>
<body>
  <div class="top">
    <div class="brand">Oops-App</div>
    <div class="sub">Warehouse Suite (KISS) — Ops Forms + Labels (no barcodes, 6-digit item #)</div>
  </div>
  <div class="wrap">
    {body_html}
  </div>
</body>
</html>
"""

# ---------- DB ----------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    cur = conn.cursor()
    cur.execute("""
      CREATE TABLE IF NOT EXISTS ops_entries (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        department TEXT NOT NULL,
        person TEXT NOT NULL,
        item_no TEXT NOT NULL,
        qty INTEGER NOT NULL,
        location TEXT NOT NULL,
        date_received TEXT,
        checked_by TEXT,
        notes TEXT
      )
    """)
    conn.commit()
    conn.close()

init_db()

# ---------- Validators ----------
ITEM_RE = re.compile(r"^\d{6}$")  # exactly 6 digits
LOC_RE  = re.compile(r"^(XA|XG|[A-L])-\d{1,2}-\d{1,2}$", re.IGNORECASE)  # A-10-1 etc + XA/XG

DEPARTMENTS = [
    ("receiving", "Receiving"),
    ("putaway", "Putaway"),
    ("picking", "Picking"),
    ("packing", "Packing"),
    ("shipping", "Shipping"),
    ("inventory", "Inventory"),
    ("returns_osd", "Returns / OSD"),
]

def safe_head_ok():
    # Render / load balancers often do HEAD to check service health.
    # If your route throws on HEAD, you'll see "/ [HEAD]" errors.
    if request.method == "HEAD":
        return True
    return False

# ---------- Routes ----------
@app.route("/", methods=["GET", "HEAD"])
def home():
    if safe_head_ok():
        return ("", 200)

    cards = []
    for key, name in DEPARTMENTS:
        cards.append(f"""
          <div class="card">
            <div class="pill">{name}</div>
            <p class="muted" style="margin:8px 0 12px 0;">Fast log entry to ops DB.</p>
            <a class="btn" href="{url_for('dept_form', dept=key)}">Open Form</a>
          </div>
        """)

    html = f"""
    <div class="card">
      <h2>Quick Actions</h2>
      <div class="row">
        <a class="btn" href="{url_for('labels')}">Print Labels (PDF)</a>
        <a class="btn2" href="{url_for('entries')}">View Entries</a>
        <a class="btn2" href="{url_for('export_today')}">Export Today (CSV)</a>
      </div>
      <p class="muted" style="margin-top:10px;">
        Location format: <b>A-10-1</b> (A–L) + custom zones <b>XA</b>, <b>XG</b>. Item # is <b>6 digits</b> (example: 607529).
      </p>
    </div>

    <div style="height:10px"></div>

    <div class="grid">
      {''.join(cards)}
    </div>
    """
    return page("Oops-App", html)

@app.route("/dept/<dept>", methods=["GET", "POST", "HEAD"])
def dept_form(dept):
    if safe_head_ok():
        return ("", 200)

    dept_map = dict(DEPARTMENTS)
    if dept not in dept_map:
        return page("Not found", "<div class='err'><b>Error:</b> Unknown department.</div>"), 404

    error = ""
    if request.method == "POST":
        person = (request.form.get("person") or "").strip()
        item_no = (request.form.get("item_no") or "").strip()
        qty_raw = (request.form.get("qty") or "").strip()
        location = (request.form.get("location") or "").strip().upper()
        date_received = (request.form.get("date_received") or "").strip()
        checked_by = (request.form.get("checked_by") or "").strip()
        notes = (request.form.get("notes") or "").strip()

        # Validate
        if not person:
            error = "Person name is required."
        elif not ITEM_RE.match(item_no):
            error = "Item # must be exactly 6 digits (example: 607529)."
        else:
            try:
                qty = int(qty_raw)
                if qty <= 0:
                    raise ValueError()
            except Exception:
                error = "Quantity must be a positive number."
        if not error and not LOC_RE.match(location):
            error = "Location must look like A-10-1 (A–L) or XA-10-1 / XG-10-1."

        if not error:
            conn = db()
            conn.execute("""
              INSERT INTO ops_entries (ts, department, person, item_no, qty, location, date_received, checked_by, notes)
              VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.utcnow().isoformat(timespec="seconds"),
                dept,
                person,
                item_no,
                qty,
                location,
                date_received,
                checked_by,
                notes
            ))
            conn.commit()
            conn.close()
            return redirect(url_for("entries"))

    title = dept_map[dept]
    html = f"""
    <div class="card">
      <h2>{title} Entry</h2>
      <p class="muted">KISS logging. One row = one action.</p>
      {"<div class='err'><b>Error:</b> "+error+"</div><div style='height:10px'></div>" if error else ""}

      <form method="POST">
        <div class="grid">
          <div>
            <label>Person</label>
            <input name="person" placeholder="e.g., Brandon" required />
          </div>

          <div>
            <label>Item # (6 digits)</label>
            <input name="item_no" inputmode="numeric" placeholder="607529" maxlength="6" required />
          </div>

          <div>
            <label>Quantity</label>
            <input name="qty" inputmode="numeric" placeholder="e.g., 24" required />
          </div>

          <div>
            <label>Location (A-10-1 / XA / XG)</label>
            <input name="location" placeholder="A-10-1" required />
          </div>

          <div>
            <label>Date received</label>
            <input name="date_received" type="date" />
          </div>

          <div>
            <label>Checked by</label>
            <input name="checked_by" placeholder="Name" />
          </div>
        </div>

        <div style="height:10px"></div>
        <label>Notes</label>
        <textarea name="notes" rows="3" placeholder="Optional..."></textarea>

        <div style="height:12px"></div>
        <div class="row">
          <button class="btn" type="submit" style="border:none;cursor:pointer">Save Entry</button>
          <a class="btn2" href="{url_for('home')}">Back</a>
        </div>
      </form>
    </div>
    """
    return page(f"{title} - Oops-App", html)

@app.route("/entries", methods=["GET", "HEAD"])
def entries():
    if safe_head_ok():
        return ("", 200)

    conn = db()
    rows = conn.execute("""
      SELECT id, ts, department, person, item_no, qty, location, date_received, checked_by, notes
      FROM ops_entries
      ORDER BY id DESC
      LIMIT 200
    """).fetchall()
    conn.close()

    def fmt_ts(ts):
        # stored UTC ISO
        try:
            return ts.replace("T", " ") + " UTC"
        except:
            return ts

    trs = []
    for r in rows:
        trs.append(f"""
          <tr>
            <td>{r['id']}</td>
            <td>{fmt_ts(r['ts'])}</td>
            <td>{r['department']}</td>
            <td>{r['person']}</td>
            <td>{r['item_no']}</td>
            <td>{r['qty']}</td>
            <td>{r['location']}</td>
            <td>{r['date_received'] or ""}</td>
            <td>{r['checked_by'] or ""}</td>
            <td>{(r['notes'] or "")[:60]}</td>
          </tr>
        """)

    html = f"""
    <div class="card">
      <div class="row" style="justify-content:space-between">
        <h2 style="margin:0">Recent Entries</h2>
        <div class="row">
          <a class="btn2" href="{url_for('export_today')}">Export Today CSV</a>
          <a class="btn" href="{url_for('home')}">Home</a>
        </div>
      </div>
      <p class="muted">Showing last 200 rows.</p>

      <table>
        <thead>
          <tr>
            <th>ID</th><th>Time</th><th>Dept</th><th>Person</th><th>Item #</th><th>Qty</th><th>Loc</th><th>Date recv</th><th>Checked</th><th>Notes</th>
          </tr>
        </thead>
        <tbody>
          {''.join(trs) if trs else "<tr><td colspan='10'>No entries yet.</td></tr>"}
        </tbody>
      </table>
    </div>
    """
    return page("Entries - Oops-App", html)

@app.route("/export/today.csv", methods=["GET", "HEAD"])
def export_today():
    if safe_head_ok():
        return ("", 200)

    today = date.today().isoformat()
    conn = db()
    rows = conn.execute("""
      SELECT ts, department, person, item_no, qty, location, date_received, checked_by, notes
      FROM ops_entries
      WHERE substr(ts, 1, 10) = ?
      ORDER BY id ASC
    """, (today,)).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ts_utc", "department", "person", "item_no", "qty", "location", "date_received", "checked_by", "notes"])
    for r in rows:
        writer.writerow([r["ts"], r["department"], r["person"], r["item_no"], r["qty"], r["location"], r["date_received"], r["checked_by"], r["notes"]])

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="ops_{today}.csv"'}
    )

# ---------- Labels ----------
def draw_label(c, x, y, w, h, item_no, qty, location, date_received, checked_by):
    # KISS 4x6 label layout: Item # first (big), Qty second, Location third
    pad = 0.20 * inch
    c.rect(x, y, w, h)

    c.setFont("Helvetica-Bold", 26)
    c.drawString(x + pad, y + h - 0.90*inch, f"ITEM # {item_no}")

    c.setFont("Helvetica-Bold", 22)
    c.drawString(x + pad, y + h - 1.55*inch, f"QTY: {qty}")

    c.setFont("Helvetica-Bold", 20)
    c.drawString(x + pad, y + h - 2.15*inch, f"LOC: {location}")

    c.setFont("Helvetica", 12)
    if date_received:
        c.drawString(x + pad, y + 0.65*inch, f"Date received: {date_received}")
    if checked_by:
        c.drawString(x + pad, y + 0.40*inch, f"Checked by: {checked_by}")

@app.route("/labels", methods=["GET", "POST", "HEAD"])
def labels():
    if safe_head_ok():
        return ("", 200)

    error = ""
    if request.method == "POST":
        item_no = (request.form.get("item_no") or "").strip()
        qty_raw = (request.form.get("qty") or "").strip()
        location = (request.form.get("location") or "").strip().upper()
        date_received = (request.form.get("date_received") or "").strip()
        checked_by = (request.form.get("checked_by") or "").strip()

        label_mode = (request.form.get("label_mode") or "bulk").strip()  # bulk = 1 label per pallet, nonbulk = 1 per item
        try:
            qty = int(qty_raw)
            if qty <= 0:
                raise ValueError()
        except Exception:
            qty = None

        if not ITEM_RE.match(item_no):
            error = "Item # must be exactly 6 digits (example: 607529)."
        elif qty is None:
            error = "Quantity must be a positive number."
        elif not LOC_RE.match(location):
            error = "Location must look like A-10-1 (A–L) or XA-10-1 / XG-10-1."
        else:
            # how many labels?
            num_labels = 1 if label_mode == "bulk" else qty

            # Generate PDF in-memory
            buf = io.BytesIO()
            c = canvas.Canvas(buf, pagesize=letter)

            # 4x6 label on letter page (top-left), one per page to keep it simple
            label_w = 4 * inch
            label_h = 6 * inch
            x = 0.75 * inch
            y = 2.25 * inch  # centers nicely

            for _ in range(num_labels):
                draw_label(c, x, y, label_w, label_h, item_no, qty, location, date_received, checked_by)
                c.showPage()

            c.save()
            buf.seek(0)

            fname = f"labels_{item_no}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
            return send_file(buf, as_attachment=True, download_name=fname, mimetype="application/pdf")

    html = f"""
    <div class="card">
      <h2>Print Labels (PDF)</h2>
      <p class="muted">
        Labels show: <b>Item #</b> first, <b>Quantity</b> second, <b>Location</b> third, then Date received + Checked by.
        <br/>Bulk = <b>1 label per pallet</b>. Non-bulk = <b>1 label per item</b>. (No barcodes.)
      </p>

      {"<div class='err'><b>Error:</b> "+error+"</div><div style='height:10px'></div>" if error else ""}

      <form method="POST">
        <div class="grid">
          <div>
            <label>Item # (6 digits)</label>
            <input name="item_no" inputmode="numeric" maxlength="6" placeholder="607529" required />
          </div>

          <div>
            <label>Quantity</label>
            <input name="qty" inputmode="numeric" placeholder="e.g., 24" required />
          </div>

          <div>
            <label>Location (A-10-1 / XA / XG)</label>
            <input name="location" placeholder="A-10-1" required />
          </div>

          <div>
            <label>Label type</label>
            <select name="label_mode">
              <option value="bulk">Bulk (1 label per pallet)</option>
              <option value="nonbulk">Non-bulk (1 label per item)</option>
            </select>
          </div>

          <div>
            <label>Date received</label>
            <input name="date_received" type="date" />
          </div>

          <div>
            <label>Checked by</label>
            <input name="checked_by" placeholder="Name" />
          </div>
        </div>

        <div style="height:12px"></div>
        <div class="row">
          <button class="btn" type="submit" style="border:none;cursor:pointer">Generate PDF</button>
          <a class="btn2" href="{url_for('home')}">Back</a>
        </div>
      </form>
    </div>
    """
    return page("Labels - Oops-App", html)

# ---------- Basic health ----------
@app.route("/health", methods=["GET", "HEAD"])
def health():
    return ("ok", 200)

# ---------- Run locally (Render uses gunicorn) ----------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="0.0.0.0", port=port, debug=True)
