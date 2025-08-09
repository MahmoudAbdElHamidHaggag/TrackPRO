# Copyright (c) 2025, MahmoudAbdElHamidHaggag
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class SalesBillingBatch(Document):
    def before_cancel(self):
        si = getattr(self, "sales_invoice", None)
        if not si:
            return

        si_status = frappe.db.get_value("Sales Invoice", si, "docstatus")
        if si_status != 2:
            frappe.throw(
                "Cannot cancel this batch while the Sales Invoice exists and is not cancelled/returned."
            )

    def validate(self):
        self._set_status()

    def before_save(self):
        self._set_status()

    def on_update_after_submit(self):
        self._set_status()

    def _set_status(self):
        self.status = "Invoiced" if getattr(self, "sales_invoice", None) else "Uninvoiced"
