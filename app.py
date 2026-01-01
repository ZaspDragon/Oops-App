\
from flask import Flask, request, redirect, url_for, render_template_string, send_file
import os, sqlite3, csv
from datetime import datetime
from io import StringIO, BytesIO
from label_pdf import generate_labels_pdf

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "ops.db")

ALLOWED_AREAS = {chr(c) for c in range(ord("A"), ord("L")+1)} | {"XA", "XG"}

DEPTS = [
    ("Receiving", ["Pallet received", "Unload complete", "Damage found", "Paperwork complete"]),
    ("Putaway", ["Putaway to location", "Re-slot", "Overflow putaway"]),
    ("Picking", ["Pick completed", "Short pick", "Substitution"]),
    ("Packing", ["Packed order", "Repack", "Void fill issue"]),
    ("Shipping", ["Loaded", "BOL signed", "Carrier pickup"]),
    ("Inventory", ["Cycle count", "Adjustment", "Bin audit"]),
    ("Returns/OSD", ["OSD logged", "Return received", "Dispose/RTV"]),
]

CSS = open(os.path.join(APP_DIR, "static.css"), "r", encoding="utf-8").read()

BASE_HTML = """
<!doctype html>
<html>
<head>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{{title}}</title>
  <style>{{css}}</style>
</head>
<body>
  <div class="topbar">
    <div>
      <span class="brand">WarehouseOps</span>
      <span class="subtle">•</span>
      <span class="title">{{title}}</span>
    </div>
    <div class="subtle">Today: <b>{{today}}</b></div>
  </div>

  <div class="wrap">
    <div class="nav">
      <a class="{{'active' if active=='Home' else ''}}" href="{{url_for('home')}}">Home</a>
      {% for d,_ in depts %}
        <a class="{{'active' if active==d else ''}}" href="{{url_for('dept', dept=d)}}">{{d}}</a>
      {% endfor %}
      <a class="{{'active' if active=='Labels' else ''}}" href="{{url_for('labels')}}">Labels</a>
      <a class="{{'active' if active=='Admin' else ''}}" href="{{url_for('admin_users')}}">Admin</a>
      <a class="{{'active' if active=='Export' else ''}}" href="{{url_for('export_today')}}">Export</a>
    </div>

    {% block body %}{% endblock %}
  </div>
</body>
</html>
"""

app = Flask(__name__)

def db():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    with db() as con:
        con.executescript(open(os.path.join(APP_DIR, "schema.sql"), "r", encoding="utf-8").read())
        if con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"] == 0:
            con.execute("INSERT OR IGNORE INTO users(name) VALUES(?)", ("Operator",))
        con.commit()

def allowed_location(loc: str) -> bool:
    if not loc:
        return True
    loc = loc.strip().upper()
    parts = loc.split("-")
    if len(parts) < 2:
        return False
    return parts[0] in ALLOWED_AREAS

def valid_item_no(item_no: str) -> bool:
    item_no = (item_no or "").strip()
    if not item_no:
        return True  # optional for general logs
    return item_no.isdigit() and len(item_no) == 6

def get_users(con):
    return [r["name"] for r in con.execute("SELECT name FROM users ORDER BY name").fetchall()]

def insert_entry(con, user_name, department, action, item_no, quantity, location, notes):
    now = datetime.now()
    work_date = now.strftime("%Y-%m-%d")
    hour = now.hour
    con.execute("""
        INSERT INTO entries(ts, work_date, hour, user_name, department, action, item_no, quantity, location, notes)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (now.isoformat(timespec="seconds"), work_date, hour, user_name, department, action,
          (item_no or "").strip(), int(quantity or 1), (location or "").strip().upper(), notes or ""))

@app.route("/")
def home():
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as con:
        rows = con.execute("""
            SELECT department, COUNT(*) as lines, SUM(quantity) as qty
            FROM entries WHERE work_date=?
            GROUP BY department ORDER BY department
        """, (today,)).fetchall()

    tpl = """
    {% extends base %}
    {% block body %}
      <div class="card">
        <h2>Warehouse Ops</h2>
        <div class="subtle">Fast logging + clean labels. No barcodes.</div>
      </div>

      <div class="card">
        <h3>Today Summary</h3>
        <table>
          <thead><tr><th>Department</th><th>Entries</th><th>Total Qty</th></tr></thead>
          <tbody>
            {% for r in rows %}
              <tr><td>{{r['department']}}</td><td>{{r['lines']}}</td><td>{{r['qty'] or 0}}</td></tr>
            {% endfor %}
            {% if rows|length == 0 %}
              <tr><td colspan="3" class="subtle">No entries yet.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    {% endblock %}
    """
    return render_template_string(tpl, base=BASE_HTML, css=CSS, depts=DEPTS, title="Home", active="Home", today=today, rows=rows)

@app.route("/dept/<dept>", methods=["GET","POST"])
def dept(dept):
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    dept_names = [d for d,_ in DEPTS]
    if dept not in dept_names:
        return "Unknown department", 404
    actions = dict(DEPTS)[dept]

    with db() as con:
        users = get_users(con)

        if request.method == "POST":
            user_name = request.form.get("user_name","").strip()
            action = request.form.get("action","").strip()
            item_no = request.form.get("item_no","").strip()
            quantity = request.form.get("quantity","1").strip() or "1"
            location = request.form.get("location","").strip().upper()
            notes = request.form.get("notes","").strip()

            if user_name not in users:
                return "Pick a valid user", 400
            if action not in actions:
                return "Pick a valid action", 400
            if item_no and (not valid_item_no(item_no)):
                return "Item # must be 6 digits (numbers only).", 400
            try:
                q = int(quantity)
                if q < 1: raise ValueError()
            except Exception:
                return "Quantity must be a positive integer", 400
            if location and not allowed_location(location):
                return "Location must start with A–L, XA, or XG (e.g., A-10-1).", 400

            insert_entry(con, user_name, dept, action, item_no, q, location, notes)
            con.commit()
            return redirect(url_for("dept", dept=dept))

        recent = con.execute("""
            SELECT ts, user_name, action, item_no, quantity, location, notes
            FROM entries
            WHERE work_date=? AND department=?
            ORDER BY id DESC
            LIMIT 20
        """, (today, dept)).fetchall()

        totals = con.execute("""
            SELECT user_name, SUM(quantity) as total_qty, COUNT(*) as lines
            FROM entries
            WHERE work_date=? AND department=?
            GROUP BY user_name
            ORDER BY total_qty DESC
        """, (today, dept)).fetchall()

    tpl = """
    {% extends base %}
    {% block body %}
      <div class="card">
        <h2>{{dept}}</h2>
        <div class="subtle">Log what you did. Done in seconds.</div>

        <form method="post" style="margin-top:10px;">
          <div class="row">
            <div>
              <label>Person</label>
              <select name="user_name" required>
                {% for u in users %}<option value="{{u}}">{{u}}</option>{% endfor %}
              </select>
            </div>
            <div>
              <label>Action</label>
              <select name="action" required>
                {% for a in actions %}<option value="{{a}}">{{a}}</option>{% endfor %}
              </select>
            </div>
          </div>

          <div class="row">
            <div>
              <label>Item # (6 digits, optional)</label>
              <input name="item_no" placeholder="607529" />
            </div>
            <div>
              <label>Quantity</label>
              <input name="quantity" inputmode="numeric" value="1" />
            </div>
          </div>

          <div class="row">
            <div>
              <label>Location (optional) — e.g., A-10-1</label>
              <input name="location" placeholder="A-10-1" />
            </div>
            <div>
              <label>Notes (optional)</label>
              <input name="notes" placeholder="" />
            </div>
          </div>

          <div style="margin-top:12px; display:flex; gap:10px; flex-wrap:wrap;">
            <button type="submit">Save Entry</button>
          </div>
        </form>
      </div>

      <div class="card">
        <h3>Today Totals ({{today}})</h3>
        <table>
          <thead><tr><th>Person</th><th>Total Qty</th><th>Entries</th></tr></thead>
          <tbody>
            {% for r in totals %}
              <tr><td><b>{{r['user_name']}}</b></td><td>{{r['total_qty'] or 0}}</td><td>{{r['lines']}}</td></tr>
            {% endfor %}
            {% if totals|length == 0 %}
              <tr><td colspan="3" class="subtle">No entries yet.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>

      <div class="card">
        <h3>Most Recent (last 20)</h3>
        <table>
          <thead><tr><th>Time</th><th>Person</th><th>Action</th><th>Item #</th><th>Qty</th><th>Loc</th><th>Notes</th></tr></thead>
          <tbody>
            {% for r in recent %}
              <tr>
                <td>{{r['ts'][11:]}}</td>
                <td>{{r['user_name']}}</td>
                <td>{{r['action']}}</td>
                <td>{{r['item_no']}}</td>
                <td>{{r['quantity']}}</td>
                <td>{{r['location']}}</td>
                <td>{{r['notes']}}</td>
              </tr>
            {% endfor %}
            {% if recent|length == 0 %}
              <tr><td colspan="7" class="subtle">No entries yet.</td></tr>
            {% endif %}
          </tbody>
        </table>
      </div>
    {% endblock %}
    """
    return render_template_string(tpl, base=BASE_HTML, css=CSS, depts=DEPTS, title=dept, active=dept, today=today,
                                  dept=dept, users=users, actions=actions, recent=recent, totals=totals)

@app.route("/admin/users", methods=["GET","POST"])
def admin_users():
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as con:
        if request.method == "POST":
            name = (request.form.get("name") or "").strip()
            if name:
                con.execute("INSERT OR IGNORE INTO users(name) VALUES(?)", (name,))
                con.commit()
            return redirect(url_for("admin_users"))

        users = con.execute("SELECT name FROM users ORDER BY name").fetchall()

    tpl = """
    {% extends base %}
    {% block body %}
      <div class="card">
        <h2>Admin — Users</h2>
        <div class="subtle">Add operator names (no passwords in this simple build).</div>

        <form method="post" style="margin-top:10px; display:flex; gap:10px; flex-wrap:wrap;">
          <div style="flex:1; min-width:220px;">
            <input name="name" placeholder="New user name" />
          </div>
          <button type="submit">Add</button>
        </form>

        <table>
          <thead><tr><th>Users</th></tr></thead>
          <tbody>
            {% for u in users %}
              <tr><td>{{u['name']}}</td></tr>
            {% endfor %}
          </tbody>
        </table>
      </div>
    {% endblock %}
    """
    return render_template_string(tpl, base=BASE_HTML, css=CSS, depts=DEPTS, title="Admin", active="Admin", today=today, users=users)

@app.route("/labels", methods=["GET","POST"])
def labels():
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")

    tpl = """
    {% extends base %}
    {% block body %}
      <div class="card">
        <h2>Label PDF (4x6)</h2>
        <div class="subtle">Item # first • Quantity second • Location third • Bulk/non-bulk printing • No barcodes.</div>

        <form method="post" enctype="multipart/form-data" style="margin-top:10px;">
          <label>Upload CSV</label>
          <input type="file" name="file" accept=".csv" required />

          <div class="subtle" style="margin-top:10px;">
            CSV headers: <b>item_no,quantity,location,date_received,checked_by,mode</b><br/>
            mode = bulk (1 label per pallet) or nonbulk (prints quantity labels)<br/>
            item_no must be 6 digits (numbers only)
          </div>

          <div style="margin-top:12px;">
            <button type="submit">Generate PDF</button>
          </div>
        </form>
      </div>
    {% endblock %}
    """
    if request.method == "GET":
        return render_template_string(tpl, base=BASE_HTML, css=CSS, depts=DEPTS, title="Labels", active="Labels", today=today)

    f = request.files.get("file")
    if not f:
        return "No CSV uploaded", 400

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        in_path = os.path.join(td, "labels.csv")
        out_path = os.path.join(td, "labels.pdf")
        f.save(in_path)
        generate_labels_pdf(in_path, out_path)
        return send_file(out_path, as_attachment=True, download_name="labels.pdf", mimetype="application/pdf")

@app.route("/export")
def export_today():
    init_db()
    today = datetime.now().strftime("%Y-%m-%d")
    with db() as con:
        rows = con.execute("""
            SELECT ts, work_date, hour, user_name, department, action, item_no, quantity, location, notes
            FROM entries
            WHERE work_date=?
            ORDER BY ts ASC
        """, (today,)).fetchall()

    sio = StringIO()
    w = csv.writer(sio)
    w.writerow(["ts","work_date","hour","user_name","department","action","item_no","quantity","location","notes"])
    for r in rows:
        w.writerow([r["ts"], r["work_date"], r["hour"], r["user_name"], r["department"], r["action"],
                    r["item_no"], r["quantity"], r["location"], r["notes"]])

    bio = BytesIO(sio.getvalue().encode("utf-8"))
    return send_file(bio, as_attachment=True, download_name=f"ops_{today}.csv", mimetype="text/csv")

if __name__ == "__main__":
    init_db()
    app.run(port=5000, debug=True)
