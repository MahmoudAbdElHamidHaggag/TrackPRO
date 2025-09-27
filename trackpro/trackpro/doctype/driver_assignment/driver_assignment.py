# Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils import get_datetime, now_datetime, add_to_date
from frappe.model.document import Document

DT = "Driver Assignment"

HEAD_TYPES = {"Head", "Tractor", "Truck"}



class DriverAssignment(Document):
	pass

def on_validate(doc, method=None):
    _set_title(doc)
    _apply_status(doc)
    _maybe_autofill_trailer(doc)          # لو السيارة رأس ومربوطة بذيل → عبّي trailer
    _close_open_assignments_if_needed(doc) # اقفال أي تعارضات قديمة

def _set_title(doc):
    if doc.driver and doc.vehicle:
        doc.driver_vehicle = f"{doc.driver}-{doc.vehicle}"

def _apply_status(doc):
    end = get_datetime(doc.to_datetime) if doc.to_datetime else None
    doc.status = "Ended" if end and end < now_datetime() else "Active"

_HEAD_ALIASES = {"head", "tractor", "رأس", "راس", "جرار"}

def _is_head_vehicle(vehicle_name: str) -> bool:
    """يراجع نوع المركبة من الداتابيز، ويرجّع True لو رأس/تراكتور."""
    vtype = frappe.db.get_value("Vehicle", vehicle_name, "custom_vehicle_category") or ""
    vtype = vtype.strip().lower()
    return vtype in _HEAD_ALIASES

def _maybe_autofill_trailer(doc):
    """
    لو السيارة رأس ومربوطة بذيل نشِط عند وقت البدء → عبّي trailer (Data).
    غير كده: لا تعمل أي رسالة ولا شيء.
    """
    if not doc.vehicle:
        return

    # اخرج فورًا لو العربية ليست رأس
    if not _is_head_vehicle(doc.vehicle):
        return

    at = get_datetime(doc.from_datetime) if doc.from_datetime else now_datetime()

    row = frappe.db.sql(
        """
        SELECT trailer_vehicle
        FROM `tabHead Trailer Assignment`
        WHERE docstatus < 2
          AND status = 'Active'
          AND tractor_vehicle = %(head)s
          AND from_datetime <= %(at)s
          AND (to_datetime IS NULL OR to_datetime >= %(at)s)
        ORDER BY from_datetime DESC
        LIMIT 1
        """,
        values={"head": doc.vehicle, "at": at},
        as_dict=True,
    )

    if row:
        # trailer عندك Data (نص) — نحط اسم الذيل كما هو
        doc.trailer = row[0]["trailer_vehicle"]
    # لو مفيش ذيل: ولا رسالة ولا throw — نخلي الواجهة تتصرف

def _close_open_assignments_if_needed(doc):
    """اقفل أي ربط مفتوح يتعارض مع هذا: نفس السيارة أو نفس السائق."""
    if not doc.from_datetime:
        return
    start = get_datetime(doc.from_datetime)
    name = doc.name or ""

    # على مستوى السيارة
    if doc.vehicle:
        vs = frappe.db.sql(f"""
            SELECT name
            FROM `tab{DT}`
            WHERE docstatus < 2
              AND name != %(name)s
              AND vehicle = %(vehicle)s
              AND (to_datetime IS NULL OR to_datetime >= %(start)s)
        """, values={"name": name, "vehicle": doc.vehicle, "start": start}, as_dict=True)
        for r in vs:
            _end_assignment(r["name"], start)

    # على مستوى السائق
    if doc.driver:
        ds = frappe.db.sql(f"""
            SELECT name
            FROM `tab{DT}`
            WHERE docstatus < 2
              AND name != %(name)s
              AND driver = %(driver)s
              AND (to_datetime IS NULL OR to_datetime >= %(start)s)
        """, values={"name": name, "driver": doc.driver, "start": start}, as_dict=True)
        for r in ds:
            _end_assignment(r["name"], start)

def _end_assignment(name, new_start):
    end_at = add_to_date(new_start, seconds=-1)
    # كتابة مباشرة لتجاوز أي إلزاميات
    frappe.db.set_value(DT, name, {"to_datetime": end_at, "status": "Ended"})
