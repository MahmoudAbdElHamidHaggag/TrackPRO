import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate
from frappe import _

ALLOWED_CONTRACT_STATUSES = ("Not Started", "In Progress")
ALLOWED_DC_STATUSES = ("Not Started", "In Progress")
ALLOWED_DO_STATUSES = ("Not Started", "In Progress")


@frappe.whitelist()
def create_download_command(
    contract, quantity, loading_area, unloading_area, start_date, end_date
):
    contract_doc = frappe.get_doc("Contract of Carriage", contract)

    q = flt(quantity)
    if q <= 0:
        frappe.throw("Quantity must be greater than zero.")

    if q > flt(contract_doc.remaining_quantity_download or 0):
        frappe.throw(
            "Cannot create a download command with a quantity greater than the contract's remaining download quantity."
        )

    sd = getdate(start_date) if start_date else None
    ed = getdate(end_date) if end_date else None
    if sd and ed and sd > ed:
        frappe.throw("Start date cannot be after end date.")

    if contract_doc.start_date and sd and sd < getdate(contract_doc.start_date):
        frappe.throw(
            "Download command start date cannot be before the contract start date."
        )
    if contract_doc.end_date and ed and ed > getdate(contract_doc.end_date):
        frappe.throw("Download command end date cannot be after the contract end date.")

    if loading_area == unloading_area:
        frappe.throw("Loading area cannot be the same as the unloading area.")

    allowed_paths = {
        (r.loading_area, r.unloading_area)
        for r in contract_doc.loading_and_unloading_areas
    }
    if (loading_area, unloading_area) not in allowed_paths:
        frappe.throw(
            "The selected loading/unloading path does not exist on this contract."
        )

    new_doc = frappe.new_doc("Download command")
    new_doc.contract_of_carriage = contract
    new_doc.quantity = q
    new_doc.loading_area = loading_area
    new_doc.unloading_area = unloading_area
    new_doc.start_date = start_date
    new_doc.end_date = end_date
    new_doc.insert()

    frappe.logger().info(
        f"Created Download command for Contract: {contract} with Qty: {q}"
    )
    return new_doc.name


@frappe.whitelist()
def create_delivery_order(contract, download, driver, vehicle, quantity):
    download_doc = frappe.get_doc("Download command", download)

    q = flt(quantity)
    if q <= 0:
        frappe.throw(_("Quantity must be greater than zero."))

    remaining_qty = flt(download_doc.remaining_quantity_delivery)
    if q > remaining_qty:
        frappe.throw(
            _(
                "Cannot create a delivery order with a quantity greater than the remaining quantity of the download command."
            )
        )

    doc = frappe.new_doc("Delivery Order")
    doc.download_command = download
    doc.contract_of_carriage = contract
    doc.driver = driver
    doc.vehicle = vehicle
    doc.quantity = q
    doc.insert()
    return doc.name


@frappe.whitelist()
def create_unloading_eceipt(
    contract, download, delivery, driver, vehicle, l_quty, quantity
):
    delivery_doc = frappe.get_doc("Delivery Order", delivery)

    q = flt(quantity)
    if q <= 0:
        frappe.throw(_("Quantity must be greater than zero."))

    already = (
        frappe.db.sql(
            """
        SELECT COALESCE(SUM(unloaded_quantity),0)
        FROM `tabUnloading Receipt`
        WHERE delivery_order=%s AND docstatus=1
        """,
            delivery,
        )[0][0]
        or 0
    )

    remaining = flt(delivery_doc.quantity) - flt(already)
    if q > remaining:
        frappe.throw(
            _(
                "Cannot unload a quantity greater than the remaining quantity on the delivery order."
            )
        )

    doc = frappe.new_doc("Unloading Receipt")
    doc.delivery_order = delivery
    doc.download_command = download
    doc.contract_of_carriage = contract
    doc.loaded_quantity = flt(l_quty)
    doc.driver = driver
    doc.vehicle = vehicle
    doc.unloaded_quantity = q
    doc.insert()
    return doc.name


@frappe.whitelist()
def closed_status(contract):
    doc = frappe.get_doc("Contract of Carriage", contract)
    doc.status = "Closed"
    doc.save(ignore_permissions=True)
    return "Closed"


@frappe.whitelist()
def closed_statu(download):
    doc = frappe.get_doc("Download command", download)
    doc.status = "Closed"
    doc.save(ignore_permissions=True)
    return "Closed"


@frappe.whitelist()
def get_unbilled_unloading(contract):
    all_receipts = frappe.get_all(
        "Unloading Receipt",
        filters={"contract_of_carriage": contract, "docstatus": 1},
        fields=["name", "unloaded_quantity", "sales_invoice"],
    )

    if not all_receipts:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in all_receipts if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    total = sum(flt(r.get("unloaded_quantity") or 0) for r in unbilled)
    return {
        "status": "ok",
        "receipts": [
            {
                "name": r["name"],
                "unloaded_quantity": flt(r.get("unloaded_quantity") or 0),
            }
            for r in unbilled
        ],
        "count": len(unbilled),
        "total": total,
    }



@frappe.whitelist()
def update_area_quantity(contract, loading_area, unloading_area, qty, fieldname):
    if not contract or not loading_area or not unloading_area or not qty:
        return

    doc = frappe.get_doc("Contract of Carriage", contract)
    updated = False

    for row in doc.loading_and_unloading_areas:
        if row.loading_area == loading_area and row.unloading_area == unloading_area:
            current = getattr(row, fieldname) or 0
            setattr(row, fieldname, current + qty)
            updated = True
            break

    if updated:
        doc.save(ignore_permissions=True)


@frappe.whitelist()
def revert_area_quantity(contract, loading_area, unloading_area, qty, fieldname):
    if not contract or not loading_area or not unloading_area or not qty:
        return

    doc = frappe.get_doc("Contract of Carriage", contract)
    updated = False

    for row in doc.loading_and_unloading_areas:
        if row.loading_area == loading_area and row.unloading_area == unloading_area:
            current = getattr(row, fieldname) or 0
            setattr(row, fieldname, max(current - qty, 0))
            updated = True
            break

    if updated:
        doc.save(ignore_permissions=True)


@frappe.whitelist()
def revert_quantity_to_contract(
    contract_name, qty_field_executed, qty_field_remaining, qty
):
    contract = frappe.get_doc("Contract of Carriage", contract_name)

    if contract.status in ["Closed", "Cancelled", "Finished"]:
        frappe.throw("Cannot modify a contract that is Closed, Cancelled, or Finished.")

    setattr(
        contract,
        qty_field_executed,
        max((getattr(contract, qty_field_executed) or 0) - qty, 0),
    )
    setattr(
        contract,
        qty_field_remaining,
        (getattr(contract, qty_field_remaining) or 0) + qty,
    )

    if contract.status == "Completed":
        contract.status = "In Progress"

    contract.save(ignore_permissions=True)


@frappe.whitelist()
def search_contracts_with_open_downloads(
    doctype, txt, searchfield, start, page_len, filters
):
    customer = (filters or {}).get("customer")
    like = f"%{txt or ''}%"

    return frappe.db.sql(
        """
        SELECT DISTINCT coc.name
        FROM `tabDownload command` dc
        JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage
        WHERE dc.docstatus = 1
        AND (dc.status IN %(dc_status)s OR IFNULL(dc.remaining_quantity_delivery,0) > 0)
        AND coc.docstatus = 1
        AND coc.status IN %(coc_status)s
        AND coc.name LIKE %(like)s
        {customer_filter}
        ORDER BY coc.name
        LIMIT %(start)s, %(page_len)s
        """.format(
            customer_filter="AND coc.customer = %(customer)s" if customer else ""
        ),
        {
            "dc_status": ALLOWED_DC_STATUSES,
            "coc_status": ALLOWED_CONTRACT_STATUSES,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
            "customer": customer,
        },
    )


@frappe.whitelist()
def search_open_download_commands(doctype, txt, searchfield, start, page_len, filters):
    contract = (filters or {}).get("contract")
    if not contract:
        return []

    like = f"%{txt or ''}%"

    return frappe.db.sql(
        """
        SELECT dc.name
        FROM `tabDownload command` dc
        WHERE dc.docstatus = 1
        AND dc.contract_of_carriage = %(contract)s
        AND (dc.status IN %(dc_status)s OR IFNULL(dc.remaining_quantity_delivery,0) > 0)
        AND dc.name LIKE %(like)s
        ORDER BY dc.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "contract": contract,
            "dc_status": ALLOWED_DC_STATUSES,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )


ALLOWED_CONTRACT_STATUSES = ("Not Started", "In Progress")
ALLOWED_DC_STATUSES = ("Not Started", "In Progress")
ALLOWED_DO_STATUSES = ("Pending Unloading",)


@frappe.whitelist()
def search_contracts_from_pending_delivery_orders(
    doctype, txt, searchfield, start, page_len, filters
):
    customer = (filters or {}).get("customer")
    like = f"%{txt or ''}%"

    return frappe.db.sql(
        """
        SELECT DISTINCT coc.name
        FROM `tabDelivery Order` do
        JOIN `tabDownload command` dc ON dc.name = do.download_command
        JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage
        WHERE do.docstatus = 1
        AND dc.docstatus = 1
        AND coc.docstatus = 1
        AND do.status = 'Pending Unloading'
        {customer_filter}
        AND coc.name LIKE %(like)s
        ORDER BY coc.name
        LIMIT %(start)s, %(page_len)s
        """.format(
            customer_filter="AND coc.customer = %(customer)s" if customer else ""
        ),
        {
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
            "customer": customer,
        },
    )


@frappe.whitelist()
def search_open_download_commands_from_contract_with_pending_do(
    doctype, txt, searchfield, start, page_len, filters
):
    contract = (filters or {}).get("contract")
    if not contract:
        return []
    like = f"%{txt or ''}%"

    return frappe.db.sql(
        """
        SELECT DISTINCT dc.name
        FROM `tabDownload command` dc
        WHERE dc.docstatus = 1
        AND dc.contract_of_carriage = %(contract)s
        AND EXISTS (
                SELECT 1
                FROM `tabDelivery Order` do
                WHERE do.download_command = dc.name
                AND do.docstatus = 1
                AND do.status = 'Pending Unloading'
        )
        AND dc.name LIKE %(like)s
        ORDER BY dc.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "contract": contract,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )


@frappe.whitelist()
def search_pending_delivery_orders_by_download(
    doctype, txt, searchfield, start, page_len, filters
):
    contract = (filters or {}).get("contract")
    download = (filters or {}).get("download")
    if not (contract and download):
        return []
    like = f"%{txt or ''}%"

    return frappe.db.sql(
        """
        SELECT do.name
        FROM `tabDelivery Order` do
        WHERE do.docstatus = 1
        AND do.contract_of_carriage = %(contract)s
        AND do.download_command = %(download)s
        AND do.status = 'Pending Unloading'
        AND do.name LIKE %(like)s
        ORDER BY do.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "contract": contract,
            "download": download,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )


###########################################################


@frappe.whitelist()
def search_contracts_with_pending_unloading(doctype, txt, searchfield, start, page_len, filters):
    """Contracts that have at least one Delivery Order in 'Pending Unloading' via its Download Command."""
    customer = (filters or {}).get("customer")
    like = f"%{txt or ''}%"
    return frappe.db.sql(
        """
        SELECT DISTINCT coc.name
        FROM `tabDelivery Order` do
        JOIN `tabDownload command` dc ON dc.name = do.download_command
        JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage
        WHERE do.docstatus = 1
          AND do.status = 'Pending Unloading'
          AND dc.docstatus = 1
          AND coc.docstatus = 1
          {customer_filter}
          AND coc.name LIKE %(like)s
        ORDER BY coc.name
        LIMIT %(start)s, %(page_len)s
        """.format(customer_filter="AND coc.customer = %(customer)s" if customer else ""),
        {
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
            "customer": customer,
        },
    )

@frappe.whitelist()
def search_open_download_commands_with_pending_unloading(doctype, txt, searchfield, start, page_len, filters):
    """Download Commands under a given Contract that still have Delivery Orders in 'Pending Unloading'."""
    contract = (filters or {}).get("contract")
    if not contract:
        return []
    like = f"%{txt or ''}%"
    return frappe.db.sql(
        """
        SELECT DISTINCT dc.name
        FROM `tabDownload command` dc
        WHERE dc.docstatus = 1
          AND dc.contract_of_carriage = %(contract)s
          AND EXISTS (
              SELECT 1
              FROM `tabDelivery Order` do
              WHERE do.download_command = dc.name
                AND do.docstatus = 1
                AND do.status = 'Pending Unloading'
          )
          AND dc.name LIKE %(like)s
        ORDER BY dc.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "contract": contract,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )

@frappe.whitelist()
def search_open_delivery_orders(doctype, txt, searchfield, start, page_len, filters):
    """Delivery Orders that still have remaining to unload (or status set to Pending Unloading)."""
    contract = (filters or {}).get("contract")
    if not contract:
        return []
    like = f"%{txt or ''}%"
    return frappe.db.sql(
        """
        SELECT do.name
        FROM `tabDelivery Order` do
        WHERE do.docstatus = 1
          AND do.contract_of_carriage = %(contract)s
          AND (
                do.status = 'Pending Unloading'
                OR (do.quantity - COALESCE((
                       SELECT SUM(ur.unloaded_quantity)
                       FROM `tabUnloading Receipt` ur
                       WHERE ur.delivery_order = do.name AND ur.docstatus = 1
                   ), 0)) > 0
          )
          AND do.name LIKE %(like)s
        ORDER BY do.name
        LIMIT %(start)s, %(page_len)s
        """,
        {
            "contract": contract,
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
        },
    )



@frappe.whitelist()
def create_sales_invoice(docname):
    batch = frappe.get_doc("Sales Billing Batch", docname)

    if getattr(batch, "sales_invoice", None):
        si_doc = frappe.get_doc("Sales Invoice", batch.sales_invoice)
        if si_doc.docstatus == 2 or si_doc.is_return:
            ur_names = frappe.get_all("Unloading Receipt", filters={"sales_invoice": batch.sales_invoice}, pluck="name")
            if ur_names:
                frappe.db.sql(
                    """
                    UPDATE `tabUnloading Receipt`
                    SET sales_invoice=NULL, status='Uninvoiced'
                    WHERE name IN %(names)s
                    """,
                    {"names": tuple(ur_names)},
                )
            batch.db_set({"sales_invoice": None, "status": "Uninvoiced"})
        else:
            frappe.throw("A Sales Invoice already exists for this batch.")

    settings = frappe.get_single("TrackPRO Setting")
    company = settings.company or frappe.defaults.get_user_default("Company")
    income_account = settings.income_account or frappe.get_value("Company", company, "default_income_account")
    cost_center = settings.cost_center or frappe.get_value("Company", company, "cost_center")
    item_code = settings.item or frappe.db.get_single_value("Selling Settings", "default_item")
    cost_account = getattr(settings, "cost_account", None) or frappe.get_value("Company", company, "default_expense_account")

    if not batch.contract_of_carriage:
        frappe.throw("Contract is required.")
    probe = get_unbilled_unloading(batch.contract_of_carriage)
    if probe["status"] in ("none", "all_billed"):
        frappe.throw("There are no unbilled unloading receipts for this contract.")

    if not batch.unbilled_unloading:
        frappe.throw("No unloading receipts were selected in the table.")

    total_qty = sum(flt(d.delivered_quantity or 0) for d in batch.unbilled_unloading)
    if total_qty <= 0:
        frappe.throw("Total quantity must be greater than zero.")

    count_rows = len(batch.unbilled_unloading)
    batch.db_set("count_unbilled_unloading", count_rows)
    batch.db_set("total_delivered_quantity", total_qty)

    si = frappe.new_doc("Sales Invoice")
    si.customer = batch.customer
    si.company = company
    si.append("items", {
        "item_code": item_code,
        "qty": total_qty,
        "income_account": income_account,
        "expense_account": cost_account,
        "cost_center": cost_center,
    })
    si.insert(ignore_permissions=True)

    batch.db_set({"sales_invoice": si.name, "status": "Invoiced"})

    for d in batch.unbilled_unloading:
        if d.unloading_receipt:
            frappe.db.set_value("Unloading Receipt", d.unloading_receipt, {"sales_invoice": si.name, "status": "Invoiced"}, update_modified=False)
            if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
                frappe.db.set_value("Unloading Receipt", d.unloading_receipt, "billing_status", "Invoiced")

    return si.name


@frappe.whitelist()
def unbill_batch(batch_name):
    batch = frappe.get_doc("Sales Billing Batch", batch_name)
    if not batch.sales_invoice:
        return "Nothing to unbill."

    si_status = frappe.db.get_value("Sales Invoice", batch.sales_invoice, "docstatus")
    if si_status == 1:
        frappe.throw("Sales Invoice is submitted. Cancel/return it first, then unbill.")

    ur_names = frappe.get_all("Unloading Receipt", filters={"sales_invoice": batch.sales_invoice}, pluck="name")
    if ur_names:
        frappe.db.sql(
            """
            UPDATE `tabUnloading Receipt`
            SET sales_invoice=NULL, status='Uninvoiced'
            WHERE name IN %(names)s
            """,
            {"names": tuple(ur_names)},
        )

    batch.db_set({"sales_invoice": None, "status": "Uninvoiced"})
    return "Unbilled."
