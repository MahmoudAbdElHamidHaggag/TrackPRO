import frappe

DEFAULTS = {
    "model": "T",
    "make": "J",
    "fuel_type": "Diesel",   
    "uom": "Nos",     
}

ODOMETER_FIELDS = ("odometer_value_last", "last_odometer_value", "last_odometer")

def after_install():
    ensure_vehicle_defaults()

def ensure_vehicle_defaults():
    meta = frappe.get_meta("Vehicle")
 
    for fieldname, value in DEFAULTS.items():   # بدل item() → items()
        if meta.get_field(fieldname):
            _upsert_ps("Vehicle", fieldname, value)
 
    for f in ODOMETER_FIELDS:
        if meta.get_field(f):
            _upsert_ps("Vehicle", f, 0)
            break
    frappe.clear_cache(doctype="Vehicle")

def _upsert_ps(doctype, field, value):
    name = frappe.db.exists("Property Setter", {
        "doc_type": doctype, "field_name": field, "property": "default"
    })
    if name:
        frappe.db.set_value("Property Setter", name, {
            "value": value, "property_type": "Text", "doctype_or_field": "DocField"
        })
    else:
        frappe.get_doc({
            "doctype": "Property Setter",
            "doc_type": doctype,
            "field_name": field,
            "property": "default",
            "value": value,
            "property_type": "Text",
            "doctype_or_field": "DocField",
        }).insert(ignore_permissions=True)
