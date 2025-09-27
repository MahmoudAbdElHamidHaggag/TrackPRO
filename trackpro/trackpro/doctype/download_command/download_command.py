# Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt
from trackpro.trackpro.api import update_area_quantity, revert_area_quantity, revert_quantity_to_contract

ALLOWED_STATUSES = ["Not Started", "In Progress", "Completed"]


class Downloadcommand(Document):

    def validate(self):
        if not self.contract_of_carriage:
            frappe.throw("You must select a contract of carriage first.")

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)

        sd = getdate(self.start_date) if self.start_date else None
        ed = getdate(self.end_date) if self.end_date else None
        cs = getdate(contract.start_date) if contract.start_date else None
        ce = getdate(contract.end_date) if contract.end_date else None

        if contract.docstatus != 1 or contract.status not in ALLOWED_STATUSES:
            frappe.throw("Cannot create/modify a download command for an inactive contract.")

        if sd and cs and sd < cs:
            frappe.throw("Download command start date cannot be before the contract start date.")
        if ed and cs and ed < cs:
            frappe.throw("Download command end date cannot be before the contract start date.")
        if ce:
            if sd and sd > ce:
                frappe.throw("Download command start date cannot be after the contract end date.")
            if ed and ed > ce:
                frappe.throw("Download command end date cannot be after the contract end date.")
        if sd and ed and sd > ed:
            frappe.throw("Start date cannot be after end date.")

        allowed = {(r.loading_area, r.unloading_area) for r in contract.loading_and_unloading_areas}
        if (self.loading_area, self.unloading_area) not in allowed:
            frappe.throw(f"Path does not exist in the contract: {self.loading_area} → {self.unloading_area}")

        if flt(self.quantity) <= 0:
            frappe.throw("Quantity must be greater than zero.")
        if flt(self.quantity) > flt(contract.remaining_quantity_download or 0) and self.docstatus == 0:
            frappe.throw("Quantity exceeds the remaining download quantity in the contract.")

        self.calculate_executed_quantity()
        self.update_status()

    def on_submit(self):
        self.calculate_executed_quantity()

        update_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=self.loading_area,
            unloading_area=self.unloading_area,
            qty=flt(self.quantity),
            fieldname="eqdownload",
        )

        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.executed_quantity_download = flt(contract.executed_quantity_download or 0) + flt(self.quantity)
        contract.remaining_quantity_download = flt(contract.remaining_quantity_download or 0) - flt(self.quantity)
        contract.save(ignore_permissions=True)

        self.update_contract()

    def on_cancel(self):
        revert_area_quantity(
            contract=self.contract_of_carriage,
            loading_area=self.loading_area,
            unloading_area=self.unloading_area,
            qty=flt(self.quantity),
            fieldname="eqdownload",
        )

        revert_quantity_to_contract(
            contract_name=self.contract_of_carriage,
            qty_field_executed="executed_quantity_download",
            qty_field_remaining="remaining_quantity_download",
            qty=flt(self.quantity),
        )

        self.update_contract()

    def update_contract(self):
        contract = frappe.get_doc("Contract of Carriage", self.contract_of_carriage)
        contract.validate()
        contract.save(ignore_permissions=True)

    def calculate_executed_quantity(self):
        qty = flt(self.quantity or 0)

        total_delivery = frappe.db.sql("""
            SELECT COALESCE(SUM(quantity), 0)
            FROM `tabDelivery Order`
            WHERE download_command = %s AND docstatus = 1
        """, self.name)[0][0] or 0

        total_unload = frappe.db.sql("""
            SELECT COALESCE(SUM(unloaded_quantity), 0)
            FROM `tabUnloading Receipt`
            WHERE download_command = %s AND docstatus = 1
        """, self.name)[0][0] or 0

        self.executed_quantity_delivery = flt(total_delivery)
        self.remaining_quantity_delivery = max(qty - flt(total_delivery), 0)

        self.executed_quantity_unload = flt(total_unload)
        self.remaining_quantity_unload = max(qty - flt(total_unload), 0)

    def update_status(self):
        if self.docstatus == 2:
            self.status = "Cancelled"
            return

        if self.end_date and getdate(self.end_date) < getdate():
            self.status = "Finished"
            return

        qty = flt(self.quantity or 0)
        exec_del = flt(self.executed_quantity_delivery or 0)
        rem_del = flt(self.remaining_quantity_delivery if self.remaining_quantity_delivery is not None else qty)

        if exec_del == 0 and rem_del == qty:
            self.status = "Not Started"
        elif exec_del < qty and rem_del != qty:
            self.status = "In Progress"
        elif exec_del == qty and rem_del == 0:
            self.status = "Completed"
