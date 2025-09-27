import frappe

def apply_defaults(doc, method=None):
    meta = frappe.get_meta("Vehicle")
    if meta.get_field("model") and not doc.model: doc.model = "T"
    if meta.get_field("make") and not doc.make: doc.make = "J"
    for f in ("odometer_value_last","last_odometer_value","last_odometer"):
        if meta.get_field(f) and not doc.get(f): setattr(doc, f, 0); break
    if meta.get_field("uom") and not doc.get("uom"): doc.uom = "Nos"

def get_data(data=None, **kwargs):
    return {"heatmap": False, "fieldname": "vehicle", "transactions": []}