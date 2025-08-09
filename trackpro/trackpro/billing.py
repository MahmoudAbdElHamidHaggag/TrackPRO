# trackpro/trackpro/api/billing_hooks.py

import frappe

BILLING_FIELD = "sales_invoice"
UR_STATUS_FIELD = "billing_status"


def _set_if_exists(doctype: str, name: str, field: str, value):
    if frappe.get_meta(doctype).has_field(field):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)


def _update_unloading_receipts_for_invoice(si_name: str, status: str, clear_link: bool):
    if not si_name:
        return
    ur_names = frappe.get_all(
        "Unloading Receipt",
        filters={BILLING_FIELD: si_name},
        pluck="name",
    )
    if not ur_names:
        return
    for ur in ur_names:
        if clear_link and frappe.get_meta("Unloading Receipt").has_field(BILLING_FIELD):
            frappe.db.set_value(
                "Unloading Receipt",
                ur,
                BILLING_FIELD,
                None,
                update_modified=False,
            )
        _set_if_exists("Unloading Receipt", ur, UR_STATUS_FIELD, status)


def _update_batches_for_invoice(si_name: str, clear_link: bool, batch_status: str | None = None):
    if not si_name:
        return
    batch_names = frappe.get_all(
        "Sales Billing Batch",
        filters={BILLING_FIELD: si_name},
        pluck="name",
    )
    if not batch_names:
        return
    for b in batch_names:
        data = {}
        if clear_link and frappe.get_meta("Sales Billing Batch").has_field(BILLING_FIELD):
            data[BILLING_FIELD] = None
        if batch_status and frappe.get_meta("Sales Billing Batch").has_field("status"):
            data["status"] = batch_status
        if data:
            frappe.db.set_value("Sales Billing Batch", b, data, update_modified=False)


def on_si_submit(doc, method=None):
    if getattr(doc, "is_return", 0):
        target = doc.get("return_against")
        _update_unloading_receipts_for_invoice(target, status="Uninvoiced", clear_link=True)
        _update_batches_for_invoice(target, clear_link=True, batch_status="Uninvoiced")
    else:
        _update_unloading_receipts_for_invoice(doc.name, status="Invoiced", clear_link=False)
        _update_batches_for_invoice(doc.name, clear_link=False, batch_status="Invoiced")


def on_si_cancel(doc, method=None):
    _update_unloading_receipts_for_invoice(doc.name, status="Uninvoiced", clear_link=True)
    _update_batches_for_invoice(doc.name, clear_link=True, batch_status="Uninvoiced")
