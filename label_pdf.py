\
import csv
from datetime import datetime
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch

LABEL_W, LABEL_H = 4*inch, 6*inch
MARGIN = 0.25*inch

ALLOWED_AREAS = {chr(c) for c in range(ord("A"), ord("L")+1)} | {"XA", "XG"}

def _validate_item_no(item_no: str):
    item_no = (item_no or "").strip()
    if not item_no:
        raise ValueError("Item # is required")
    if (not item_no.isdigit()) or len(item_no) != 6:
        raise ValueError(f"Item # must be 6 digits (numbers only). Got: {item_no}")

def _validate_location(loc: str):
    loc = (loc or "").strip().upper()
    if not loc:
        return
    parts = loc.split("-")
    if len(parts) < 2:
        raise ValueError(f"Location must look like AREA-ROW-BIN (e.g., A-10-1). Got: {loc}")
    if parts[0] not in ALLOWED_AREAS:
        raise ValueError(f"Area must be A–L, XA, or XG. Got: {parts[0]}")

def _draw_label(c: canvas.Canvas, item_no: str, quantity: int, location: str, date_received: str, checked_by: str):
    c.setLineWidth(1)
    c.rect(MARGIN/2, MARGIN/2, LABEL_W-MARGIN, LABEL_H-MARGIN)

    x0 = MARGIN
    y = LABEL_H - MARGIN

    # Item # big and first
    c.setFont("Helvetica-Bold", 30)
    c.drawString(x0, y - 36, f"ITEM: {item_no}")

    # Divider
    c.setLineWidth(0.5)
    c.line(x0, y - 52, LABEL_W - MARGIN, y - 52)

    # Quantity second
    c.setFont("Helvetica-Bold", 20)
    c.drawString(x0, y - 90, f"QTY: {quantity}")

    # Location third
    c.setFont("Helvetica-Bold", 22)
    c.drawString(x0, y - 128, f"LOC: {location}")

    # Remaining fields
    c.setFont("Helvetica", 14)
    c.drawString(x0, y - 165, f"Date received: {date_received}")
    c.drawString(x0, y - 190, f"Checked by: {checked_by}")

    c.setFont("Helvetica-Oblique", 10)
    c.drawRightString(LABEL_W - MARGIN, MARGIN, "4x6 label • no barcode")

def generate_labels_pdf(input_csv: str, output_pdf: str):
    c = canvas.Canvas(output_pdf, pagesize=(LABEL_W, LABEL_H))
    with open(input_csv, "r", newline="", encoding="utf-8-sig") as f:
        r = csv.DictReader(f)
        for idx, row in enumerate(r, start=2):
            item_no = (row.get("item_no") or "").strip()
            _validate_item_no(item_no)

            quantity = int((row.get("quantity") or "1").strip() or "1")
            if quantity < 1:
                raise ValueError(f"Line {idx}: quantity must be >= 1")

            location = (row.get("location") or "").strip().upper()
            _validate_location(location)

            date_received = (row.get("date_received") or "").strip() or datetime.now().strftime("%Y-%m-%d")
            checked_by = (row.get("checked_by") or "").strip() or "__________"
            mode = (row.get("mode") or "bulk").strip().lower()
            if mode not in ("bulk", "nonbulk"):
                raise ValueError(f"Line {idx}: mode must be bulk or nonbulk")

            copies = 1 if mode == "bulk" else quantity

            for _ in range(max(1, copies)):
                _draw_label(c, item_no, quantity, location, date_received, checked_by)
                c.showPage()

    c.save()
