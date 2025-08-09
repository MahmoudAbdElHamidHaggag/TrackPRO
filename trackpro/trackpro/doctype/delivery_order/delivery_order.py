# apps/trackpro/trackpro/trackpro/doctype/delivery_order/delivery_order.py
import frappe
from frappe.model.document import Document
from frappe.utils import flt
from trackpro.trackpro.api import (
    update_area_quantity,
    revert_area_quantity,
    revert_quantity_to_contract,
)

ALLOWED_STATUSES = ("Not Started", "In Progress")


def _sum_do_qty_excluding_current(download_command: str, current_name: str | None = None, is_draft: bool = False) -> float:
    """Sum of submitted Delivery Orders for the given Download Command,
    excluding the current record when editing."""
    params = {"dc": download_command}
    exclude = ""
    if current_name and not is_draft:
        exclude = "AND name != %(cur)s"
        params["cur"] = current_name

    return (
        frappe.db.sql(
            f"""
            SELECT COALESCE(SUM(quantity), 0)
            FROM `tabDelivery Order`
            WHERE download_command = %(dc)s
              AND docstatus = 1
              {exclude}
            """,
            params,
        )[0][0]
        or 0
    )


class DeliveryOrder(Document):
    def validate(self):
        if not self.contract_of_carriage or not self.download_command:
            frappe.throw("Please select Contract of Carriage and Download Command first.")

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        dc = frappe.get_doc("Download command", self.download_command)

        if contract.docstatus != 1 or contract.status not in ALLOWED_STATUSES:
            frappe.throw("Contract is not active; cannot create/modify a Delivery Order.")

        if self.loading_area != dc.loading_area or self.unloading_area != dc.unloading_area:
            frappe.throw("Delivery Order areas must match the Download Command areas.")

        if flt(self.quantity) <= 0:
            frappe.throw("Quantity must be greater than zero.")

        # Validate against remaining of the Download Command (not the contract)
        delivered_so_far = _sum_do_qty_excluding_current(
            self.download_command,
            self.name,
            is_draft=(self.docstatus == 0),
        )
        dc_qty = flt(dc.quantity or 0)
        remaining_for_do = dc_qty - flt(delivered_so_far)

        if flt(self.quantity) > remaining_for_do:
            frappe.throw("Quantity exceeds the remaining quantity on the Download Command.")

        self.update_status()

    def on_submit(self):
        dc = frappe.get_doc("Download command", self.download_command)

        update_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=dc.loading_area,
            unloading_area=dc.unloading_area,
            qty=flt(self.quantity),
            fieldname="eqdelivery",
        )

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.executed_quantity_delivered = flt(contract.executed_quantity_delivered) + flt(self.quantity)
        contract.remaining_quantity_delivered = flt(contract.remaining_quantity_delivered) - flt(self.quantity)
        contract.save(ignore_permissions=True)

        dc.calculate_executed_quantity()
        dc.update_status()
        dc.save(ignore_permissions=True)

        self.update_contract()
        self.update_status()

    def on_cancel(self):
        dc = frappe.get_doc("Download command", self.download_command)

        revert_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=dc.loading_area,
            unloading_area=dc.unloading_area,
            qty=flt(self.quantity),
            fieldname="eqdelivery",
        )

        revert_quantity_to_contract(
            contract_name=self.contract_of_carriage,
            qty_field_executed="executed_quantity_delivered",
            qty_field_remaining="remaining_quantity_delivered",
            qty=flt(self.quantity),
        )

        dc.calculate_executed_quantity()
        dc.update_status()
        dc.save(ignore_permissions=True)

        self.update_contract()
        self.update_status()

    def update_contract(self):
        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.validate()
        contract.save(ignore_permissions=True)

    def update_status(self):
        """Set status to 'Pending Unloading' if there is remaining to unload, otherwise 'Unloaded'."""
        delivered_qty = flt(self.quantity or 0)
        unloaded_qty = (
            frappe.db.sql(
                """
                SELECT COALESCE(SUM(unloaded_quantity), 0)
                FROM `tabUnloading Receipt`
                WHERE delivery_order = %s AND docstatus = 1
                """,
                self.name,
            )[0][0]
            or 0
        )
        self.status = "Pending Unloading" if unloaded_qty < delivered_qty else "Unloaded"
