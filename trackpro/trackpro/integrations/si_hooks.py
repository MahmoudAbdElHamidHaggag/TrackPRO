import frappe

def on_sales_invoice_cancel(doc, method=None):
    """When a Sales Invoice is cancelled, clear links on the Sales Billing Batch and its receipts."""

    batches = frappe.get_all("Sales Billing Batch", filters={"sales_invoice": doc.name}, pluck="name")
    for bname in batches:
        batch = frappe.get_doc("Sales Billing Batch", bname)

        for d in batch.unbilled_unloading:
            if d.unloading_receipt:
                if frappe.get_meta("Unloading Receipt").has_field("sales_invoice"):
                    frappe.db.set_value("Unloading Receipt", d.unloading_receipt, "sales_invoice", None)
                if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
                    frappe.db.set_value("Unloading Receipt", d.unloading_receipt, "billing_status", "Unbilled")

        if frappe.get_meta("Sales Billing Batch").has_field("sales_invoice"):
            batch.db_set("sales_invoice", None)
