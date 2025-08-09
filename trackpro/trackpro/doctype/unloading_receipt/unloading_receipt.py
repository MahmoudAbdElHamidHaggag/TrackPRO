# Copyright (c) 2025, MahmoudAbdElHamidHaggag
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt
from trackpro.trackpro.api import (
    update_area_quantity,
    revert_area_quantity,
    revert_quantity_to_contract,
)

ALLOWED_STATUSES = ("Not Started", "In Progress")


def _sum_unloaded_excluding_current(delivery_order, current_docname=None):
    params = {"do": delivery_order}
    exclude_clause = ""
    if current_docname:
        exclude_clause = "AND name != %(cur)s"
        params["cur"] = current_docname

    return (
        frappe.db.sql(
            f"""
            SELECT COALESCE(SUM(unloaded_quantity), 0)
            FROM `tabUnloading Receipt`
            WHERE delivery_order = %(do)s
              AND docstatus = 1
              {exclude_clause}
            """,
            params,
        )[0][0]
        or 0
    )


class UnloadingReceipt(Document):
    def validate(self):
        required = {
            "contract_of_carriage": "Contract of Carriage",
            "download_command": "Download command",
            "delivery_order": "Delivery Order",
            "loading_area": "Loading Area",
            "unloading_area": "Unloading Area",
        }
        for f, lbl in required.items():
            if not getattr(self, f, None):
                frappe.throw(f"{lbl} must be set first.")

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        dc = frappe.get_doc("Download command", self.download_command)
        de = frappe.get_doc("Delivery Order", self.delivery_order)

        if contract.docstatus != 1 or contract.status not in ALLOWED_STATUSES:
            frappe.throw("Contract is not active; cannot create/modify an Unloading Receipt.")

        if dc.contract_of_carriage != contract.name:
            frappe.throw("Selected Download Command does not belong to the selected contract.")
        if de.contract_of_carriage != contract.name:
            frappe.throw("Selected Delivery Order does not belong to the selected contract.")
        if de.download_command != dc.name:
            frappe.throw("Selected Delivery Order does not belong to the selected Download Command.")

        if self.loading_area != dc.loading_area or self.unloading_area != dc.unloading_area:
            frappe.throw("Unloading Receipt areas must match the Download Command (loading/unloading).")

        if getattr(de, "loading_area", None) and getattr(de, "unloading_area", None):
            if self.loading_area != de.loading_area or self.unloading_area != de.unloading_area:
                frappe.throw("Unloading Receipt areas must match the Delivery Order areas.")

        sd = getdate(self.get("posting_date")) if self.get("posting_date") else None
        cs = getdate(contract.start_date) if contract.start_date else None
        ce = getdate(contract.end_date) if contract.end_date else None
        if sd and cs and sd < cs:
            frappe.throw("Unloading Receipt date cannot be before the contract start date.")
        if sd and ce and sd > ce:
            frappe.throw("Unloading Receipt date cannot be after the contract end date.")

        if flt(self.unloaded_quantity) <= 0:
            frappe.throw("Unloaded quantity must be greater than zero.")

        already_unloaded = _sum_unloaded_excluding_current(
            de.name,
            self.name if self.name and self.docstatus != 0 else None,
        )
        remaining_to_unload = flt(de.quantity or 0) - flt(already_unloaded)

        if flt(self.unloaded_quantity) > remaining_to_unload:
            frappe.throw(
                f"Unloaded quantity ({flt(self.unloaded_quantity)}) exceeds remaining quantity on the Delivery Order ({remaining_to_unload})."
            )

        self.unloading_status()

    def before_save(self):
        self.unloading_status()

    def on_submit(self):
        self.difference_quantity = flt(self.loaded_quantity) - flt(self.unloaded_quantity)
        self.difference_percentage = (
            (self.difference_quantity / flt(self.loaded_quantity)) * 100 if flt(self.loaded_quantity) else 0
        )

        dc = frappe.get_doc("Download command", self.download_command)

        update_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=dc.loading_area,
            unloading_area=dc.unloading_area,
            qty=flt(self.unloaded_quantity),
            fieldname="equnownload",
        )

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.executed_quantity_unloaded = flt(contract.executed_quantity_unloaded) + flt(self.unloaded_quantity)
        contract.remaining_quantity_unloaded = flt(contract.remaining_quantity_unloaded) - flt(self.unloaded_quantity)
        contract.save(ignore_permissions=True)

        dc.calculate_executed_quantity()
        dc.update_status()
        dc.save(ignore_permissions=True)

        self._touch_delivery_order_status()
        self.update_contract()
        self.update_download()

    def on_update_after_submit(self):
        self.unloading_status()

    def on_cancel(self):
        dc = frappe.get_doc("Download command", self.download_command)

        revert_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=dc.loading_area,
            unloading_area=dc.unloading_area,
            qty=flt(self.unloaded_quantity),
            fieldname="equnownload",
        )

        revert_quantity_to_contract(
            contract_name=self.contract_of_carriage,
            qty_field_executed="executed_quantity_unloaded",
            qty_field_remaining="remaining_quantity_unloaded",
            qty=flt(self.unloaded_quantity),
        )

        dc.calculate_executed_quantity()
        dc.update_status()
        dc.save(ignore_permissions=True)

        self._touch_delivery_order_status()
        self.update_contract()
        self.update_download()

    def update_contract(self):
        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.validate()
        contract.save(ignore_permissions=True)

    def update_download(self):
        download = frappe.get_doc("Download command", self.download_command)
        download.validate()
        download.save(ignore_permissions=True)

    def _touch_delivery_order_status(self):
        if not self.delivery_order:
            return
        do = frappe.get_doc("Delivery Order", self.delivery_order)
        do.update_status()
        do.save(ignore_permissions=True)

    def unloading_status(self):
        self.status = "Invoiced" if self.sales_invoice else "Uninvoiced"
