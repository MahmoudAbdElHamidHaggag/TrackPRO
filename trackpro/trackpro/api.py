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


def _ur_date_field() -> str:
    meta = frappe.get_meta("Unloading Receipt")
    for f in ("date", "posting_date", "transaction_date", "unloading_date"):
        if meta.get_field(f):
            return f
    frappe.throw("No date field found on Unloading Receipt. Add a Date field (e.g. 'date' or 'posting_date').")

def _validated_between(date_field: str, from_date: str | None, to_date: str | None) -> dict:
    if not from_date or not to_date:
        frappe.throw("Please select both From Date and To Date.")
    if getdate(from_date) > getdate(to_date):
        frappe.throw("From Date cannot be after To Date.")
    return {date_field: ["between", [from_date, to_date]]}

@frappe.whitelist()
def get_unbilled_unloading(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    all_receipts = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=["name", "unloaded_quantity", "driver", "vehicle", "sales_invoice", date_field],
        order_by=f"{date_field} asc, name asc",
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
                "driver": r.get("driver"),
                "vehicle": r.get("vehicle"),
                "date": r.get(date_field),
            }
            for r in unbilled
        ],
        "count": len(unbilled),
        "total": total,
    }

@frappe.whitelist()
def get_unbilled_delivery(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    all_receipts = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=["name", "loaded_quantity", "driver", "vehicle", "sales_invoice", date_field],
        order_by=f"{date_field} asc, name asc",
    )

    if not all_receipts:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in all_receipts if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    total = sum(flt(r.get("loaded_quantity") or 0) for r in unbilled)
    return {
        "status": "ok",
        "receipts": [
            {
                "name": r["name"],
                "loaded_quantity": flt(r.get("loaded_quantity") or 0),
                "driver": r.get("driver"),
                "vehicle": r.get("vehicle"),
                "date": r.get(date_field),
            }
            for r in unbilled
        ],
        "count": len(unbilled),
        "total": total,
    }

@frappe.whitelist()
def get_unbilled_less_dev_unload(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    all_receipts = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=["name", "driver", "vehicle", "loaded_quantity", "unloaded_quantity", "sales_invoice", date_field],
        order_by=f"{date_field} asc, name asc",
    )

    if not all_receipts:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in all_receipts if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    rows, total = [], 0.0
    for r in unbilled:
        billable = min(flt(r.get("loaded_quantity") or 0), flt(r.get("unloaded_quantity") or 0))
        if billable > 0:
            rows.append({
                "name": r["name"],
                "unloaded_quantity": billable,
                "driver": r.get("driver"),
                "vehicle": r.get("vehicle"),
                "date": r.get(date_field),
            })
            total += billable

    if not rows:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    return {
        "status": "ok",
        "receipts": rows,
        "count": len(rows),
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
###################################################################3


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


#########################################################################


@frappe.whitelist()
def create_sales_invoice(docname):
    from frappe.utils import nowdate, flt

    batch = frappe.get_doc("Sales Billing Batch", docname)

    # لو في فاتورة مرتبطة سابقًا
    if getattr(batch, "sales_invoice", None):
        si_doc = frappe.get_doc("Sales Invoice", batch.sales_invoice)
        if si_doc.docstatus == 2 or si_doc.is_return:
            ur_names = frappe.get_all(
                "Unloading Receipt",
                filters={"sales_invoice": batch.sales_invoice},
                pluck="name",
            )
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

    # إعدادات
    settings = frappe.get_single("TrackPRO Setting")
    company = settings.company or frappe.defaults.get_user_default("Company")
    income_account = settings.income_account or frappe.get_value("Company", company, "default_income_account")
    cost_center = settings.cost_center or frappe.get_value("Company", company, "cost_center")
    cost_account = getattr(settings, "cost_account", None) or frappe.get_value("Company", company, "default_expense_account")
    taxes_template = getattr(settings, "sales_taxes_and_charges_template", None)

    # حقول الدفعة
    type_of_contract = (batch.get("type_of_contract") or "").strip()
    supplied_material_item = batch.get("supplied_materials")
    transportation_price = flt(batch.get("transportation_price") or 0)
    supplied_material_price = flt(batch.get("supplied_material_price") or 0)

    transportation_service_item = getattr(settings, "item", None) or frappe.db.get_single_value(
        "Selling Settings", "default_item"
    )

    if not batch.contract_of_carriage:
        frappe.throw("Contract is required.")

    rows = batch.get("unbilled_unloading") or []
    if not rows:
        frappe.throw("No unloading receipts were selected in the table.")

    total_qty = sum(flt(d.get("delivered_quantity") or 0) for d in rows)
    if total_qty <= 0:
        frappe.throw("Total quantity must be greater than zero.")

    valid_contracts = {"Transportation", "Transport and Supply"}
    if type_of_contract not in valid_contracts:
        frappe.throw("Type Of Contract must be one of: Transportation, Transport and Supply.")

    if type_of_contract == "Transportation":
        if not transportation_service_item:
            frappe.throw("Transportation service item is not set (TrackPRO Setting.item or Selling Settings.default_item).")
        if transportation_price <= 0:
            frappe.throw("Transportation Price must be greater than zero for Transportation contracts.")
    else:
        if not supplied_material_item:
            frappe.throw("Supplied Materials is required for Transport and Supply contracts.")
        if supplied_material_price <= 0:
            frappe.throw("Supplied Material Price must be greater than zero for Transport and Supply contracts.")
        if not transportation_service_item:
            frappe.throw("Transportation service item is not set (TrackPRO Setting.item or Selling Settings.default_item).")
        if transportation_price <= 0:
            frappe.throw("Transportation Price must be greater than zero for Transport and Supply contracts.")

    # تحديث مجاميع الدفعة
    count_rows = len(rows)
    batch.db_set("count_unbilled_unloading", count_rows)
    batch.db_set("total_delivered_quantity", total_qty)

    # إنشاء الفاتورة مع إغلاق كل مصادر إعادة التسعير
    si = frappe.new_doc("Sales Invoice")
    si.customer = batch.customer
    si.company = company
    si.posting_date = nowdate()

    # اقفل أي Price List / Pricing Rules / خصومات / تقريب
    si.selling_price_list = None
    si.price_list_currency = None
    si.ignore_pricing_rule = 1
    si.flags.ignore_pricing_rule = 1
    si.apply_discount_on = "Net Total"
    si.additional_discount_percentage = 0
    si.discount_amount = 0
    si.disable_rounded_total = 1  # يمنع إنشاء صف تقريب

    if taxes_template:
        si.taxes_and_charges = taxes_template

    # حمِّل القيم الافتراضية (بدون بنود لسه)
    si.set_missing_values()

    # لو فيه ضرائب، الغِ الشمول (Included In Print Rate) محليًا على الفاتورة
    # علشان ما يعيدش توزيع السعر
    for tx in (si.taxes or []):
        if getattr(tx, "included_in_print_rate", 0):
            tx.included_in_print_rate = 0

    def add_item(item_code, qty, rate, desc=None):
        child = si.append("items", {
            "item_code": item_code,
            "qty": qty,
            "description": desc or "",
            "income_account": income_account,
            "expense_account": cost_account,
            "cost_center": cost_center,
            "discount_percentage": 0,
            "discount_amount": 0,
        })
        # تثبيت السعر ومنع أي اشتقاق من Price List / Rules
        child.pricing_rules = ""
        child.margin_type = None
        child.margin_rate_or_amount = 0
        child.rate = flt(rate or 0)
        child.price_list_rate = flt(rate or 0)
        child.net_rate = flt(rate or 0)
        child.base_rate = flt(rate or 0)
        child.base_price_list_rate = flt(rate or 0)

    if type_of_contract == "Transportation":
        add_item(
            transportation_service_item,
            total_qty,
            transportation_price,
            desc=f"Transportation for {count_rows} receipts (Batch: {batch.name})",
        )
    else:
        add_item(
            supplied_material_item,
            total_qty,
            supplied_material_price,
            desc=f"Supplied Materials for {count_rows} receipts (Batch: {batch.name})",
        )
        add_item(
            transportation_service_item,
            total_qty,
            transportation_price,
            desc=f"Transportation for {count_rows} receipts (Batch: {batch.name})",
        )

    # احسب الإجماليات بعد ما ثبتنا كل حاجة
    si.calculate_taxes_and_totals()

    # إدخال وترحيل
    si.insert(ignore_permissions=True)
    si.submit()

    # ربط الفاتورة وتحديث سندات التفريغ
    batch.db_set({"sales_invoice": si.name, "status": "Invoiced"})

    ur_names = [r.unloading_receipt for r in rows if r.get("unloading_receipt")]
    if ur_names:
        frappe.db.sql(
            """
            UPDATE `tabUnloading Receipt`
            SET sales_invoice=%(si)s, status='Invoiced'
            WHERE name IN %(names)s
            """,
            {"si": si.name, "names": tuple(ur_names)},
        )
        if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET billing_status='Invoiced'
                WHERE name IN %(names)s
                """,
                {"names": tuple(ur_names)},
            )

    return si.name



#################################################################################



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
