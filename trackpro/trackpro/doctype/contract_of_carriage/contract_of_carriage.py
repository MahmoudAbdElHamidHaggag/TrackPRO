import frappe
from frappe.model.document import Document
from frappe.utils import getdate, flt


class ContractofCarriage(Document):
    def validate_areas(self):
        seen = set()
        for idx, row in enumerate(self.loading_and_unloading_areas or [], start=1):
            la = (row.loading_area or "").strip()
            ua = (row.unloading_area or "").strip()

            if not la or not ua:
                frappe.throw(f"Row #{idx}: Both loading and unloading areas must be specified.")
            if la == ua:
                frappe.throw(f"Row #{idx}: Unloading area cannot be the same as loading area ({la}).")

            key = (la, ua)
            if key in seen:
                frappe.throw(f"Row #{idx}: Path ({la} → {ua}) is duplicated in the table.")
            seen.add(key)

    def update_status(self):
        if self.docstatus == 2:
            self.status = "Cancelled"
        elif self.end_date and getdate(self.end_date) < getdate():
            self.status = "Finished"
        elif flt(self.executed_quantity_download) == 0 and flt(self.remaining_quantity_download) == flt(self.agreed_quantity):
            self.status = "Not Started"
        elif flt(self.executed_quantity_download) < flt(self.agreed_quantity) and flt(self.remaining_quantity_download) != flt(self.agreed_quantity):
            self.status = "In Progress"
        elif flt(self.executed_quantity_download) == flt(self.agreed_quantity) and flt(self.remaining_quantity_download) == 0:
            self.status = "Completed"

    def validate(self):
        self.executed_quantity_download = flt(frappe.db.sql(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM `tabDownload command`
            WHERE contract_of_carriage=%s AND docstatus=1
            """,
            self.name,
        )[0][0])

        self.executed_quantity_delivered = flt(frappe.db.sql(
            """
            SELECT COALESCE(SUM(quantity), 0)
            FROM `tabDelivery Order`
            WHERE contract_of_carriage=%s AND docstatus=1
            """,
            self.name,
        )[0][0])

        self.executed_quantity_unloaded = flt(frappe.db.sql(
            """
            SELECT COALESCE(SUM(unloaded_quantity), 0)
            FROM `tabUnloading Receipt`
            WHERE contract_of_carriage=%s AND docstatus=1
            """,
            self.name,
        )[0][0])

        self.remaining_quantity_download = flt(self.agreed_quantity) - flt(self.executed_quantity_download)
        self.remaining_quantity_delivered = flt(self.agreed_quantity) - flt(self.executed_quantity_delivered)
        self.remaining_quantity_unloaded = flt(self.agreed_quantity) - flt(self.executed_quantity_unloaded)

        if self.end_date < self.start_date:
            frappe.throw("The contract end date cannot be earlier than the contract start date.")

        self.update_status()
