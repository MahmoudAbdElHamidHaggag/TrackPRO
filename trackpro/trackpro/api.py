import frappe
from frappe.model.document import Document
from frappe.utils import flt, getdate, now_datetime, get_datetime, add_to_date, get_link_to_form, cint, nowdate
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

#########################################################################

@frappe.whitelist()
@frappe.whitelist()
def create_delivery_order(
    contract, download, quantity, transported_by=None,
    # Own Fleet
    driver=None, vehicle=None,
    # External Carrier
    supplier=None, driver_name=None, driver_iqama_number=None,
    driver_license_number=None, vehicle_configuration=None,
    vehicle_plate_number=None, tractor_plate_number=None, trailer_plate_number=None,
):
    if not transported_by:
        frappe.throw(_("Please choose 'Transported By'."))

    q = flt(quantity)
    if q <= 0:
        frappe.throw(_("Quantity must be greater than zero."))

    download_doc = frappe.get_doc("Download command", download)
    if hasattr(download_doc, "remaining_quantity_delivery"):
        remaining = flt(download_doc.remaining_quantity_delivery)
        if remaining and q > remaining:
            frappe.throw(_("Quantity exceeds remaining delivery balance."))

    doc = frappe.new_doc("Delivery Order")
    doc.contract_of_carriage = contract
    doc.download_command = download
    doc.quantity = q
    doc.transported_by = transported_by

    if transported_by == "Own Fleet":
        # كل الظاهر إجباري: Driver + Vehicle
        if not driver or not vehicle:
            frappe.throw(_("Driver and Vehicle are required for 'Own Fleet'."))
        doc.driver = driver
        doc.vehicle = vehicle

    elif transported_by == "External Carrier":
        # إجباري: supplier + iqama + vehicle_type
        if not supplier:
            frappe.throw(_("Supplier is required."))
        doc.supplier = supplier
        if not driver_iqama_number:
            frappe.throw(_("Driver Iqama/ID is required."))
        doc.driver_iqama_number = driver_iqama_number
        if not vehicle_configuration:
            frappe.throw(_("Vehicle Type is required."))
        doc.vehicle_configuration = vehicle_configuration

        # اختياريّان
        if driver_name: doc.driver_name = driver_name
        if driver_license_number: doc.driver_license_number = driver_license_number

        doc.vehicle_configuration = vehicle_configuration

        if vehicle_configuration == "Truck":
            if not vehicle_plate_number:
                frappe.throw(_("Vehicle Plate No. is required for 'Truck'."))
            doc.vehicle_plate_number = vehicle_plate_number

        elif vehicle_configuration == "Tractor + Trailer":
            if not tractor_plate_number:
                frappe.throw(_("Head Plate No. is required for 'Tractor + Trailer'."))
            doc.tractor_plate_number = tractor_plate_number
            if trailer_plate_number:
                doc.trailer_plate_number = trailer_plate_number

        else:
            frappe.throw(_("Invalid Vehicle Type."))

    # الحالة الابتدائية
    if hasattr(doc, "status"):
        doc.status = "Pending Unloading"

    doc.insert(ignore_permissions=True)
    if "docstatus" in doc.as_dict() and doc.meta.is_submittable:
        doc.save()

    try:
        if hasattr(download_doc, "calculate_executed_quantity"):
            download_doc.calculate_executed_quantity()
        if hasattr(download_doc, "update_status"):
            download_doc.update_status()
        download_doc.save(ignore_permissions=True)
    except Exception:
        pass

    return doc.name

################################################################

@frappe.whitelist()
def get_unloading_remaining(delivery):
    """يرجع الكمية المُحمّلة، المُفرّغة سابقًا، والمتبقية على أمر التسليم."""
    do = frappe.get_doc("Delivery Order", delivery)
    loaded = flt(do.quantity)
    already = (
        frappe.db.sql("""
            SELECT COALESCE(SUM(unloaded_quantity),0)
            FROM `tabUnloading Receipt`
            WHERE delivery_order=%s AND docstatus=1
        """, (delivery,))[0][0] or 0
    )
    remaining = max(loaded - flt(already), 0.0)
    return {"loaded": loaded, "already": flt(already), "remaining": remaining}

@frappe.whitelist()
def create_unloading_receipt(contract, download, delivery, driver=None, vehicle=None, l_quty=None, quantity=None):
    """ينشئ Unloading Receipt مع جميع التحققات الضرورية."""
    delivery_doc = frappe.get_doc("Delivery Order", delivery)

    # دايمًا نعتمد الكمية المحمّلة من الـ Delivery Order (لو l_quty وصل، نتجاهله)
    loaded_quantity = flt(delivery_doc.quantity)

    q = flt(quantity)
    if q <= 0:
        frappe.throw(_("Quantity must be greater than zero."))

    rem_info = get_unloading_remaining(delivery)
    #if q > rem_info["remaining"]:
    #    frappe.throw(_("Cannot unload a quantity greater than the remaining quantity on the delivery order."))

    doc = frappe.new_doc("Unloading Receipt")
    doc.delivery_order = delivery
    doc.download_command = download
    doc.contract_of_carriage = contract
    doc.loaded_quantity = loaded_quantity
    # قد تكون None مع الناقل الخارجي — مفيش مشكلة
    if driver:  doc.driver = driver
    if vehicle: doc.vehicle = vehicle
    doc.unloaded_quantity = q

    doc.insert(ignore_permissions=True)

    # لو الـ Doctype قابل للتقديم، نعمل Submit
    if getattr(doc.meta, "is_submittable", False):
        doc.save()

    # تحديثات اختيارية آمنة (لو الدوال موجودة)
    try:
        # تحديث حالة Delivery Order إن لزم
        already = rem_info["already"] + q
        if abs(loaded_quantity - already) < 1e-9:
            if hasattr(delivery_doc, "status"):
                delivery_doc.status = "Unloaded"
            delivery_doc.save(ignore_permissions=True)

        # تحديث Download command لو عندك دوال
        dc = frappe.get_doc("Download command", download)
        if hasattr(dc, "calculate_executed_quantity"):
            dc.calculate_executed_quantity()
        if hasattr(dc, "update_status"):
            dc.update_status()
        dc.save(ignore_permissions=True)
    except Exception:
        pass

    return doc.name

# إبقاء الاسم القديم كـ alias لتجنّب كسر أي استدعاءات حالية
@frappe.whitelist()
def create_unloading_eceipt(contract, download, delivery, driver=None, vehicle=None, l_quty=None, quantity=None):
    return create_unloading_receipt(contract, download, delivery, driver, vehicle, l_quty, quantity)

######################################################################

@frappe.whitelist()
def closed_status(contract):
    doc = frappe.get_doc("Contract of Carriage", contract)
    doc.status = "Closed"
    doc.save(ignore_permissions=True)
    return "Closed"

########################################################################

@frappe.whitelist()
def closed_statu(download):
    doc = frappe.get_doc("Download command", download)
    doc.status = "Closed"
    doc.save(ignore_permissions=True)
    return "Closed"

#####################################################################

def _ur_date_field() -> str:
    meta = frappe.get_meta("Unloading Receipt")
    for f in ("date", "posting_date", "transaction_date", "unloading_date"):
        if meta.get_field(f):
            return f
    frappe.throw("No date field found on Unloading Receipt. Add a Date field (e.g. 'date' or 'posting_date').")

###################

def _validated_between(date_field: str, from_date: str | None, to_date: str | None) -> dict:
    if not from_date or not to_date:
        frappe.throw("Please select both From Date and To Date.")
    if getdate(from_date) > getdate(to_date):
        frappe.throw("From Date cannot be after To Date.")
    return {date_field: ["between", [from_date, to_date]]}

#####################################################################  


def _pick_first(row, keys):
    for k in keys:
        v = row.get(k)
        if v:
            return str(v).strip()
    return ""

def _resolve_transport_and_supplier(r):
    """
    أولوية: بيانات UR، ولو ناقصة نكمّل من الـ DO المرتبط.
    لو مفيش transported_by ومالقيناش مورد → نعتبرها Own Fleet.
    لو Own Fleet نخلي supplier فارغ.
    """
    transported_by = r.get("transported_by") or ""
    supplier = r.get("supplier") or ""

    # لو ناقصين، كمّل من الـ DO
    do = r.get("delivery_order") or ""
    if (not transported_by or not supplier) and do:
        if not transported_by:
            transported_by = frappe.db.get_value("Delivery Order", do, "transported_by") or transported_by
        if not supplier:
            supplier = frappe.db.get_value("Delivery Order", do, "supplier") or supplier

    if not transported_by:
        transported_by = "External Carrier" if supplier else "Own Fleet"

    if transported_by == "Own Fleet":
        supplier = ""  # نحافظ على supplier فارغ في أسطولنا

    return transported_by, supplier

def _resolve_driver_for_row(r):
    """
    Own Fleet: driver_name / driver / full_name
    External: iqama (إن وجد) ثم ' - ' ثم الاسم (إن وجد)
    """
    transported_by, _ = _resolve_transport_and_supplier(r)
    if transported_by == "External Carrier":
        iqama = _pick_first(r, ["iqama_no", "residency_id", "id_no", "driver_id", "iqama", "id_number"])
        name = _pick_first(r, ["driver_name", "driver", "full_name"])
        if iqama and name:
            return f"{iqama} - {name}"
        return iqama or name or ""
    else:
        return _pick_first(r, ["driver_name", "driver", "full_name"])

def _resolve_vehicle_for_row(r):
    """
    Tractor+Trailer => HEAD:TRAILER (لو الذيل موجود)
    Truck/أحادي => رقم اللوحة (UR عندك فيها vehicle_plate_numbe بدون r)
    """
    cfg = r.get("vehicle_configuration") or ""
    head = _pick_first(r, ["tractor_plate_number", "head_plate_number", "head_plate"])
    trailer = _pick_first(r, ["trailer_plate_number", "trailer_plate"])

    if cfg == "Tractor + Trailer" or head or trailer:
        return f"{head}:{trailer}" if (head and trailer) else (head or trailer or "")

    # Truck/أحادي
    return _pick_first(r, ["vehicle_plate_numbe", "vehicle_plate_number", "vehicle", "truck_plate", "vehicle_no"])


@frappe.whitelist()
def get_unbilled_unloading(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    rows = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=[
            "name",
            "unloaded_quantity",
            "driver", "driver_name", "full_name",
            "vehicle", "vehicle_configuration", "vehicle_plate_numbe",
            "tractor_plate_number", "trailer_plate_number",
            "transported_by", "supplier",
            "delivery_order",
            "sales_invoice",
            date_field,
        ],
        order_by=f"{date_field} asc, name asc",
    )

    if not rows:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in rows if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    out = []
    total = 0.0
    for r in unbilled:
        qty = flt(r.get("unloaded_quantity") or 0)
        transported_by, supplier = _resolve_transport_and_supplier(r)
        out.append({
            "name": r["name"],
            "unloaded_quantity": qty,
            "driver": _resolve_driver_for_row(r),
            "vehicle": _resolve_vehicle_for_row(r),
            "transported_by": transported_by,
            "supplier": supplier,
            "date": r.get(date_field),
        })
        total += qty

    return {"status": "ok", "receipts": out, "count": len(out), "total": total}

#####################################################################    

@frappe.whitelist()
def get_unbilled_delivery(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    rows = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=[
            "name",
            "loaded_quantity",
            "driver", "driver_name", "full_name",
            "vehicle", "vehicle_configuration", "vehicle_plate_numbe",
            "tractor_plate_number", "trailer_plate_number",
            "transported_by", "supplier",
            "delivery_order",
            "sales_invoice",
            date_field,
        ],
        order_by=f"{date_field} asc, name asc",
    )

    if not rows:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in rows if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    out = []
    total = 0.0
    for r in unbilled:
        qty = flt(r.get("loaded_quantity") or 0)
        transported_by, supplier = _resolve_transport_and_supplier(r)
        out.append({
            "name": r["name"],
            "loaded_quantity": qty,
            "driver": _resolve_driver_for_row(r),
            "vehicle": _resolve_vehicle_for_row(r),
            "transported_by": transported_by,
            "supplier": supplier,
            "date": r.get(date_field),
        })
        total += qty

    return {"status": "ok", "receipts": out, "count": len(out), "total": total}
#####################################################################    

@frappe.whitelist()
def get_unbilled_less_dev_unload(contract, from_date=None, to_date=None):
    date_field = _ur_date_field()
    filters = {"contract_of_carriage": contract, "docstatus": 1}
    filters.update(_validated_between(date_field, from_date, to_date))

    rows = frappe.get_all(
        "Unloading Receipt",
        filters=filters,
        fields=[
            "name",
            "loaded_quantity", "unloaded_quantity",
            "driver", "driver_name", "full_name",
            "vehicle", "vehicle_configuration", "vehicle_plate_numbe",
            "tractor_plate_number", "trailer_plate_number",
            "transported_by", "supplier",
            "delivery_order",
            "sales_invoice",
            date_field,
        ],
        order_by=f"{date_field} asc, name asc",
    )

    if not rows:
        return {"status": "none", "receipts": [], "count": 0, "total": 0}

    unbilled = [r for r in rows if not r.get("sales_invoice")]
    if not unbilled:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    out, total = [], 0.0
    for r in unbilled:
        billable = min(flt(r.get("loaded_quantity") or 0), flt(r.get("unloaded_quantity") or 0))
        if billable > 0:
            transported_by, supplier = _resolve_transport_and_supplier(r)
            out.append({
                "name": r["name"],
                "unloaded_quantity": billable,   # الكمية القابلة للفوترة
                "driver": _resolve_driver_for_row(r),
                "vehicle": _resolve_vehicle_for_row(r),
                "transported_by": transported_by,
                "supplier": supplier,
                "date": r.get(date_field),
            })
            total += billable

    if not out:
        return {"status": "all_billed", "receipts": [], "count": 0, "total": 0}

    return {"status": "ok", "receipts": out, "count": len(out), "total": total}

#####################################################################

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

#####################################################################

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

#####################################################################

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

#####################################################################

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

#####################################################################

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

#####################################################################

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

#####################################################################

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

#####################################################################

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
    customer = (filters or {}).get("customer")
    like = f"%{txt or ''}%"

    query = """
        SELECT DISTINCT name
        FROM (
            -- (أ) UR غير مفوتر + DO غير مفوتر
            SELECT coc.name
            FROM `tabUnloading Receipt` ur
            JOIN `tabDelivery Order` do ON do.name = ur.delivery_order AND do.docstatus = 1
            JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
            JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage AND coc.docstatus = 1
            WHERE ur.docstatus = 1
              AND (ur.sales_invoice IS NULL OR ur.sales_invoice = '')
              AND (do.sales_invoice IS NULL OR do.sales_invoice = '')
              {customer_filter_1}
              AND coc.name LIKE %(like)s

            UNION

            -- (ب) DO غير مفوتر ولا يوجد له UR معتمد حتى الآن
            SELECT coc.name
            FROM `tabDelivery Order` do
            JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
            JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage AND coc.docstatus = 1
            LEFT JOIN `tabUnloading Receipt` ur
                   ON ur.delivery_order = do.name AND ur.docstatus = 1
            WHERE do.docstatus = 1
              AND (do.sales_invoice IS NULL OR do.sales_invoice = '')
              AND ur.name IS NULL
              {customer_filter_2}
              AND coc.name LIKE %(like)s
        ) q
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """.format(
        customer_filter_1="AND coc.customer = %(customer)s" if customer else "",
        customer_filter_2="AND coc.customer = %(customer)s" if customer else "",
    )

    return frappe.db.sql(
        query,
        {
            "like": like,
            "start": int(start or 0),
            "page_len": int(page_len or 20),
            "customer": customer,
        },
    )

###################################

@frappe.whitelist()
def search_open_download_commands_with_pending_unloading(doctype, txt, searchfield, start, page_len, filters):
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
                AND (do.status = 'Pending Unloading')
          )
          AND dc.name LIKE %(like)s
        ORDER BY dc.name
        LIMIT %(start)s, %(page_len)s
        """,
        {"contract": contract, "like": like, "start": int(start or 0), "page_len": int(page_len or 20)},
    )

############################

@frappe.whitelist()
def search_open_delivery_orders(doctype, txt, searchfield, start, page_len, filters):
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
                OR (
                    do.quantity - IFNULL((
                        SELECT SUM(ur.unloaded_quantity)
                        FROM `tabUnloading Receipt` ur
                        WHERE ur.delivery_order = do.name AND ur.docstatus = 1
                    ), 0)
                ) > 0
          )
          AND do.name LIKE %(like)s
        ORDER BY do.name
        LIMIT %(start)s, %(page_len)s
        """,
        {"contract": contract, "like": like, "start": int(start or 0), "page_len": int(page_len or 20)},
    )


#########################################################################


import frappe
from frappe.utils import nowdate, flt

@frappe.whitelist()
def create_sales_invoice(docname):
    from frappe.utils import flt, nowdate
    import frappe

    # ===== Batch =====
    batch = frappe.get_doc("Sales Billing Batch", docname)

    # لو في فاتورة مبيعات مرتبطة سابقًا
    if getattr(batch, "sales_invoice", None):
        si_doc = frappe.get_doc("Sales Invoice", batch.sales_invoice)
        # نسمح بفك الارتباط فقط لو الفاتورة مُلغاة (docstatus=2) أو كانت مرتجع
        if si_doc.docstatus == 2 or getattr(si_doc, "is_return", 0):
            ur_names = frappe.get_all(
                "Unloading Receipt",
                filters={"sales_invoice": batch.sales_invoice},
                pluck="name",
            )
            if ur_names:
                frappe.db.sql(
                    """
                    UPDATE `tabUnloading Receipt`
                    SET
                        sales_invoice = NULL,
                        status = CASE
                            WHEN IFNULL(purchase_invoice, '') != '' THEN 'Purchase Billing'
                            ELSE 'Uninvoiced'
                        END
                    WHERE name IN %(names)s
                    """,
                    {"names": tuple(ur_names)},
                )
                # لو عندك billing_status
                if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
                    frappe.db.sql(
                        """
                        UPDATE `tabUnloading Receipt`
                        SET billing_status = CASE
                            WHEN IFNULL(purchase_invoice, '') != '' THEN 'Purchase Billing'
                            ELSE 'Uninvoiced'
                        END
                        WHERE name IN %(names)s
                        """,
                        {"names": tuple(ur_names)},
                    )
            batch.db_set({"sales_invoice": None, "status": "Uninvoiced"})
        else:
            frappe.throw("A Sales Invoice already exists for this batch.")

    # ===== Settings / Company =====
    try:
        settings = frappe.get_single("TrackPRO Setting")
    except Exception:
        settings = frappe.get_single("TrackPro Settings")

    company = (getattr(settings, "company", None)
               or frappe.defaults.get_user_default("Company")
               or frappe.db.get_default("company"))

    if not company:
        frappe.throw("Company is not set (TrackPRO Settings / User Default).")

    cm = frappe.get_meta("Company")

    def _co(field):
        return frappe.db.get_value("Company", company, field) if cm.has_field(field) else None

    income_account = (getattr(settings, "income_account", None)
                      or _co("default_income_account"))

    # Cost Center (مع رسالة تنبيه عند استخدام الافتراضي)
    cost_center = (getattr(settings, "cost_center", None)
                   or _co("cost_center")
                   or _co("default_cost_center"))

    if not getattr(settings, "cost_center", None) and cost_center:
        frappe.msgprint(
            f"تنبيه: مركز التكلفة غير مضبوط في الإعدادات. تم استخدام الافتراضي للشركة: <b>{cost_center}</b>.",
            alert=True, indicator="orange"
        )
    elif not cost_center:
        frappe.throw(f"لا يوجد مركز تكلفة في الإعدادات ولا افتراضي على الشركة ({company}).")

    cost_account = (getattr(settings, "cost_account", None)
                    or _co("default_expense_account"))

    taxes_template = getattr(settings, "sales_taxes_and_charges_template", None)

    # ===== Validations =====
    type_of_contract = (batch.get("type_of_contract") or "").strip()
    supplied_material_item = batch.get("supplied_materials")
    transportation_price = flt(batch.get("transportation_price") or 0)
    supplied_material_price = flt(batch.get("supplied_material_price") or 0)

    transportation_service_item = (getattr(settings, "item", None)
                                   or frappe.db.get_single_value("Selling Settings", "default_item"))

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

    # تحديث مجاميع الباتش
    count_rows = len(rows)
    batch.db_set("count_unbilled_unloading", count_rows)
    batch.db_set("total_delivered_quantity", total_qty)

    # ===== Create Sales Invoice =====
    si = frappe.new_doc("Sales Invoice")
    si.customer = batch.customer
    si.company = company
    si.posting_date = nowdate()

    # إيقاف تأثير قوائم الأسعار والقواعد
    si.ignore_pricing_rule = 1
    si.flags.ignore_pricing_rule = 1
    si.apply_discount_on = "Net Total"
    si.additional_discount_percentage = 0
    si.discount_amount = 0
    si.disable_rounded_total = 1

    if taxes_template:
        si.taxes_and_charges = taxes_template

    si.set_missing_values()

    # تأكيد أن الضرائب ليست مضمنة في السعر
    for tx in (si.taxes or []):
        if getattr(tx, "included_in_print_rate", 0):
            tx.included_in_print_rate = 0

    def add_item(item_code, qty, rate, desc=None):
        child = si.append("items", {
            "item_code": item_code,
            "qty": qty,
            "description": desc or "",
            "income_account": income_account,
            "cost_center": cost_center,
            # expense_account اختياري في SI؛ أضفه لو متوفر
            **({"expense_account": cost_account} if cost_account else {}),
            "discount_percentage": 0,
            "discount_amount": 0,
        })
        r = flt(rate or 0)
        child.pricing_rules = ""
        child.margin_type = None
        child.margin_rate_or_amount = 0
        child.rate = r
        child.price_list_rate = r
        child.net_rate = r
        child.base_rate = r
        child.base_price_list_rate = r

    if type_of_contract == "Transportation":
        add_item(
            transportation_service_item,
            total_qty,
            transportation_price,
            desc=f"Transportation for {count_rows} receipts (Batch: {batch.name})",
        )
    else:
        # Transport and Supply: بند المواد فقط (لو عايز بند النقل كمان أضفه ثانيًا)
        add_item(
            supplied_material_item,
            total_qty,
            supplied_material_price,
            desc=f"Supplied Materials for {count_rows} receipts (Batch: {batch.name})",
        )

    si.calculate_taxes_and_totals()
    si.insert(ignore_permissions=True)
    si.save()

    # اربط الفاتورة بالباتش
    batch.db_set({"sales_invoice": si.name, "status": "Invoiced"})

    # اربط الفاتورة بسجلات التفريغ مع تحديث الحالة الصحيح
    ur_names = [r.unloading_receipt for r in rows if r.get("unloading_receipt")]
    if ur_names:
        frappe.db.sql(
            """
            UPDATE `tabUnloading Receipt`
            SET
                sales_invoice = %(si)s,
                status = CASE
                    WHEN IFNULL(purchase_invoice, '') != '' THEN 'Invoiced'
                    ELSE 'Sales Billing'
                END
            WHERE name IN %(names)s
            """,
            {"si": si.name, "names": tuple(ur_names)},
        )
        if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET billing_status = CASE
                    WHEN IFNULL(purchase_invoice, '') != '' THEN 'Invoiced'
                    ELSE 'Sales Billing'
                END
                WHERE name IN %(names)s
                """,
                {"names": tuple(ur_names)},
            )

    return si.name


#############################################################################

@frappe.whitelist()
def unbill_batch(batch_name):
    batch = frappe.get_doc("Sales Billing Batch", batch_name)
    if not batch.sales_invoice:
        return "Nothing to unbill."

    si_status, is_return = frappe.db.get_value(
        "Sales Invoice", batch.sales_invoice, ["docstatus", "is_return"]
    )

    # لا تفك الارتباط لو الفاتورة مُعتمدة وليست مرتجع
    if si_status == 1 and not is_return:
        frappe.throw("Sales Invoice is submitted. Cancel/return it first, then unbill.")

    ur_names = frappe.get_all(
        "Unloading Receipt",
        filters={"sales_invoice": batch.sales_invoice},
        pluck="name"
    )
    if ur_names:
        frappe.db.sql(
            """
            UPDATE `tabUnloading Receipt`
            SET
                sales_invoice = NULL,
                status = CASE
                    WHEN IFNULL(purchase_invoice, '') != '' THEN 'Purchase Billing'
                    ELSE 'Uninvoiced'
                END
            WHERE name IN %(names)s
            """,
            {"names": tuple(ur_names)},
        )

    batch.db_set({"sales_invoice": None, "status": "Uninvoiced"})
    return "Unbilled."



#########################################################################

@frappe.whitelist()
def detach_now(name: str, when: str | None = None):

    doc = frappe.get_doc("Head Trailer Assignment", name)

    assert_can_change_head_trailer(doc.tractor_vehicle, when or now_datetime())

    end_at = add_to_date(get_datetime(when) if when else now_datetime(), seconds=-1)

    # نعدّل بس الحقلين دول
    frappe.db.set_value("Head Trailer Assignment", name, {
        "to_datetime": end_at,
        "status": "Ended",
    })

    doc = frappe.get_doc("Head Trailer Assignment", name)
    return {"ok": True, "name": doc.name, "status": doc.status, "to_datetime": doc.to_datetime}



    #################################################################################

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def vehicles_by_category(doctype, txt, searchfield, start, page_len, filters):
    # 1) حوّل الفلاتر لو وصلت كنص JSON
    if isinstance(filters, str):
        try:
            filters = frappe.parse_json(filters)
        except Exception:
            filters = {}
    filters = filters or {}

    # 2) اجمع الفئات: category (واحدة) أو categories (قائمة)
    cats = []
    if filters.get("categories"):
        cats = filters["categories"]
        if isinstance(cats, str):
            cats = [cats]
    elif filters.get("category"):
        cats = [filters["category"]]

    # طبع/تنظيف
    cats = [str(c).strip() for c in cats if str(c).strip()]

    # 3) STRICT: لو مفيش فئات، رجّع فاضي (علشان ما نرجّعش الكل بالغلط)
    if not cats:
        return []

    # 4) فلترة ORM مضمونة على عمودك الفعلي custom_vehicle_category
    cond = {
        "custom_vehicle_category": ["in", cats],
        "name": ["like", f"%{txt}%"],
    }

    names = frappe.get_all(
        "Vehicle",
        filters=cond,
        pluck="name",
        limit_start=start,
        limit_page_length=page_len,
        order_by="name asc",
    )
    # صيغة search_link المتوقعة: list of tuples
    return [(n,) for n in names]

   ##########################################################################

@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def vehicles_by_category_drive(doctype, txt, searchfield, start, page_len, filters):

    if isinstance(filters, str):
        try:
            filters = frappe.parse_json(filters)
        except Exception:
            filters = {}
    filters = filters or {}

    # 2) اجمع الفئات: category واحدة أو categories قائمة
    cats = []
    if filters.get("categories"):
        cats = filters["categories"]
        if isinstance(cats, str):
            cats = [cats]
    elif filters.get("category"):
        cats = [filters["category"]]
    cats = [str(c).strip() for c in cats if str(c).strip()]

    # STRICT: لو مفيش فئات ما نرجّعش الكل بالغلط
    if not cats:
        return []

    # 3) بنِ placeholders مسمّاة للفئات
    params = {"txt": f"%{txt}%", "start": start, "page_len": page_len}
    ph = []
    for i, c in enumerate(cats):
        k = f"cat{i}"
        params[k] = c
        ph.append(f"%({k})s")

    sql = f"""
        SELECT name
        FROM `tabVehicle`
        WHERE custom_vehicle_category IN ({', '.join(ph)})
          AND name LIKE %(txt)s
        ORDER BY name
        LIMIT %(start)s, %(page_len)s
    """

    return frappe.db.sql(sql, params)  # ← مرّر dict واحد بس


########################################3


@frappe.whitelist()
def detach_driver_now(name: str, when: str | None = None):
    end_at = add_to_date(get_datetime(when) if when else now_datetime(), seconds=-1)
    frappe.db.set_value("Driver Assignment", name, {"to_datetime": end_at, "status": "Ended"})
    doc = frappe.get_doc("Driver Assignment", name)
    return {"ok": True, "name": doc.name, "status": doc.status, "to_datetime": doc.to_datetime}

####################################################

@frappe.whitelist()
def get_active_trailer_for_head(head: str, at: str | None = None):
    at_dt = get_datetime(at) if at else now_datetime()
    row = frappe.db.sql("""
        SELECT trailer_vehicle
        FROM `tabHead Trailer Assignment`
        WHERE docstatus < 2
          AND status = 'Active'
          AND tractor_vehicle = %(head)s
          AND from_datetime <= %(at)s
          AND (to_datetime IS NULL OR to_datetime >= %(at)s)
        ORDER BY from_datetime DESC
        LIMIT 1
    """, values={"head": head, "at": at_dt}, as_dict=True)
    return row[0]["trailer_vehicle"] if row else None


    #################################################################################


def _find_active_driver_assignments(vehicle: str, at=None):
    at = get_datetime(at) if at else now_datetime()
    return frappe.db.sql("""
        SELECT name, driver
        FROM `tabDriver Assignment`
        WHERE docstatus < 2
          AND status = 'Active'
          AND vehicle = %(v)s
          AND from_datetime <= %(at)s
          AND (to_datetime IS NULL OR to_datetime >= %(at)s)
        ORDER BY from_datetime DESC
    """, {"v": vehicle, "at": at}, as_dict=True)



###############

def assert_can_change_head_trailer(head: str, at=None):
    """يرمى throw لو الرأس عليه Driver Assignment نشط. يضمّن روابط للمستندات."""
    if not head:
        return
    rows = _find_active_driver_assignments(head, at)
    if rows:
        links = "<br>".join(
            f"{get_link_to_form('Driver Assignment', r['name'])} — {r['driver']}" for r in rows
        )
        frappe.throw(
            _("لا يمكن تعديل/فك ربط الرأس <b>{0}</b> لأنه مرتبط بسائق حاليًا."
              "<br>فضّلًا قم بإنهاء ربط السائق أولًا ثم أعد المحاولة."
              "<br><br>{1}").format(head, links),
            title=_("الرأس مرتبط بسائق")
        )
##########################################################################


@frappe.whitelist()
def get_active_vehicle_for_driver(driver, at=None):
    at = get_datetime(at) if at else now_datetime()
    row = frappe.db.sql("""
        SELECT vehicle
        FROM `tabDriver Assignment`
        WHERE docstatus < 2
          AND status = 'Active'
          AND driver = %(driver)s
          AND from_datetime <= %(at)s
          AND (to_datetime IS NULL OR to_datetime >= %(at)s)
        ORDER BY from_datetime DESC
        LIMIT 1
    """, {"driver": driver, "at": at}, as_dict=True)
    return row[0]["vehicle"] if row else None

################################################################################

@frappe.whitelist()
def get_active_driver_for_vehicle(vehicle, at=None):
    at = get_datetime(at) if at else now_datetime()
    row = frappe.db.sql("""
        SELECT driver
        FROM `tabDriver Assignment`
        WHERE docstatus < 2
          AND status = 'Active'
          AND vehicle = %(vehicle)s
          AND from_datetime <= %(at)s
          AND (to_datetime IS NULL OR to_datetime >= %(at)s)
        ORDER BY from_datetime DESC
        LIMIT 1
    """, {"vehicle": vehicle, "at": at}, as_dict=True)
    return row[0]["driver"] if row else None

#######################################################################################3

# @frappe.whitelist()
# def search_contracts_with_pending_unloading_for_purchase(doctype, txt, searchfield, start, page_len, filters):
#     supplier = (filters or {}).get("supplier")
#     like = f"%{txt or ''}%"

#     query = """
#         SELECT DISTINCT name
#         FROM (
#             -- (أ) UR غير مفوتر مشتريات + DO غير مفوتر مشتريات + خارجية
#             SELECT coc.name
#             FROM `tabUnloading Receipt` ur
#             JOIN `tabDelivery Order` do ON do.name = ur.delivery_order AND do.docstatus = 1
#             JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
#             JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage AND coc.docstatus = 1
#             WHERE ur.docstatus = 1
#               AND (ur.purchase_invoice IS NULL OR ur.purchase_invoice = '')
#               AND (do.purchase_invoice IS NULL OR do.purchase_invoice = '')
#               AND (do.transported_by = 'External Carrier' OR do.supplier IS NOT NULL)
#               {supplier_filter_1}
#               AND coc.name LIKE %(like)s

#             UNION

#             -- (ب) DO غير مفوتر مشتريات (خارجية) ولا يوجد له UR معتمد حتى الآن
#             SELECT coc.name
#             FROM `tabDelivery Order` do
#             JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
#             JOIN `tabContract of Carriage` coc ON coc.name = dc.contract_of_carriage AND coc.docstatus = 1
#             LEFT JOIN `tabUnloading Receipt` ur
#                    ON ur.delivery_order = do.name AND ur.docstatus = 1
#             WHERE do.docstatus = 1
#               AND (do.purchase_invoice IS NULL OR do.purchase_invoice = '')
#               AND ur.name IS NULL
#               AND (do.transported_by = 'External Carrier' OR do.supplier IS NOT NULL)
#               {supplier_filter_2}
#               AND coc.name LIKE %(like)s
#         ) q
#         ORDER BY name
#         LIMIT %(start)s, %(page_len)s
#     """.format(
#         supplier_filter_1="AND do.supplier = %(supplier)s" if supplier else "",
#         supplier_filter_2="AND do.supplier = %(supplier)s" if supplier else "",
#     )

#     return frappe.db.sql(
#         query,
#         {
#             "like": like,
#             "start": int(start or 0),
#             "page_len": int(page_len or 20),
#             "supplier": supplier,
#         },
#     )



##################################################################################

def _pick_first(d, keys):
    for k in keys:
        v = d.get(k)
        if v:
            return v
    return None

def _extract_vehicle_from_do(do_doc):
    # رأس/ذيل إن وجدوا
    head = _pick_first(do_doc, ["tractor_plate_number"])
    trailer = _pick_first(do_doc, ["trailer_plate_number"])
    if head or trailer:
        return f"{head or ''}{('-' + trailer) if trailer else ''}".strip("-")
    # شاحنة مفردة
    return _pick_first(do_doc, ["vehicle_plate_number", "vehicle"])

def _extract_vehicle_from_ur(ur_doc):
    # عندك الحقل الغلط إملائيًا: vehicle_plate_numbe
    head = _pick_first(ur_doc, ["tractor_plate_number"])
    trailer = _pick_first(ur_doc, ["trailer_plate_number"])
    if head or trailer:
        return f"{head or ''}{('-' + trailer) if trailer else ''}".strip("-")
    return _pick_first(ur_doc, ["vehicle_plate_numbe", "vehicle"])

def _extract_driver(do_doc=None, ur_doc=None):
    # أولوية للاسم النصي driver_name ثم رابط driver
    if ur_doc:
        d = _pick_first(ur_doc, ["driver_name", "driver"])
        if d:
            return d
    if do_doc:
        return _pick_first(do_doc, ["driver_name", "driver"])
    return None

def _enrich_driver_vehicle(rows):
    out = []
    for r in rows or []:
        do_name = r.get("delivery_order")
        ur_name = r.get("unloading_receipt")
        do_doc = None
        ur_doc = None

        if do_name:
            try:
                do_doc = frappe.get_doc("Delivery Order", do_name).as_dict()
            except Exception:
                do_doc = None
        if ur_name:
            try:
                ur_doc = frappe.get_doc("Unloading Receipt", ur_name).as_dict()
            except Exception:
                ur_doc = None

        driver = r.get("driver") or _extract_driver(do_doc, ur_doc) or ""
        vehicle = r.get("vehicle") or ""
        if not vehicle and do_doc:
            vehicle = _extract_vehicle_from_do(do_doc) or ""
        if not vehicle and ur_doc:
            vehicle = _extract_vehicle_from_ur(ur_doc) or ""

        r["driver"] = driver
        r["vehicle"] = vehicle
        out.append(r)
    return out

def _date_between_clause(fieldname, from_date, to_date):
    if from_date and to_date:
        return f" AND {fieldname} BETWEEN %(from_date)s AND %(to_date)s "
    if from_date:
        return f" AND {fieldname} >= %(from_date)s "
    if to_date:
        return f" AND {fieldname} <= %(to_date)s "
    return ""

def _as_rows(records, row_type="UR"):
    rows = []
    for r in records or []:
        rows.append({
            "unloading_receipt": r.get("unloading_receipt"),
            "delivery_order": r.get("delivery_order"),
            "download_command": r.get("download_command"),
            "receipt_number": r.get("unloading_receipt") or r.get("delivery_order"),
            "date": r.get("date"),
            "delivered_quantity": flt(r.get("delivered_quantity") or 0),
            "driver": r.get("driver"),
            "vehicle": r.get("vehicle"),
            "_basis": "Unloading Receipt" if row_type == "UR" else "Delivery Order",
        })
    return rows

def _service_item_for_purchase():
    # يمكنك ربطه بإعداداتك إن وجدت
    code = frappe.db.get_single_value("TrackPro Setting", "item") or "TRANSPORT-SERVICE-EXT"
    if not frappe.db.exists("Item", code):
        item = frappe.get_doc({
            "doctype": "Item",
            "item_code": code,
            "item_name": "External Transport Service",
            "is_stock_item": 0,
        })
        item.insert(ignore_permissions=True)
    return code

# ============ Fetch (Unbilled) ============

@frappe.whitelist()
def get_unbilled_unloading_purchase(supplier=None, from_date=None, to_date=None, external_only=1):
    if not supplier or not from_date or not to_date:
        return {"status": "none", "rows": []}

    params = {"supplier": supplier, "from_date": from_date, "to_date": to_date}
    dcl = _date_between_clause("ur.`date`", from_date, to_date)

    q = f"""
        SELECT
            ur.name AS unloading_receipt,
            do.name AS delivery_order,
            dc.name AS download_command,
            ur.`date` AS date,
            COALESCE(ur.unloaded_quantity, do.quantity) AS delivered_quantity
        FROM `tabUnloading Receipt` ur
        JOIN `tabDelivery Order` do ON do.name = ur.delivery_order AND do.docstatus = 1
        JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
        WHERE ur.docstatus = 1
          AND (ur.purchase_invoice IS NULL OR ur.purchase_invoice = '')
          AND (do.purchase_invoice IS NULL OR do.purchase_invoice = '')
          AND (do.supplier = %(supplier)s OR ur.supplier = %(supplier)s)
          {dcl}
          {"AND (do.transported_by = 'External Carrier' OR do.supplier IS NOT NULL)" if cint(external_only) else ""}
        ORDER BY ur.`date`, ur.name
    """
    base = frappe.db.sql(q, params, as_dict=True)
    rows = _as_rows(base, "UR")
    rows = _enrich_driver_vehicle(rows)
    return {"status": "ok" if rows else "none", "rows": rows}


@frappe.whitelist()
def get_unbilled_delivery_purchase(supplier=None, from_date=None, to_date=None, external_only=1):
    if not supplier or not from_date or not to_date:
        return {"status": "none", "rows": []}

    params = {"supplier": supplier, "from_date": from_date, "to_date": to_date}

    # نستخدم COALESCE(ur.date, do.posting_date) للتصفية والعرض
    q = """
        SELECT
            do.name AS delivery_order,
            dc.name AS download_command,
            COALESCE(MIN(ur.`date`), do.posting_date) AS date,
            do.quantity AS delivered_quantity
        FROM `tabDelivery Order` do
        JOIN `tabDownload command` dc ON dc.name = do.download_command AND dc.docstatus = 1
        LEFT JOIN `tabUnloading Receipt` ur
               ON ur.delivery_order = do.name AND ur.docstatus = 1
        WHERE do.docstatus = 1
          AND (do.purchase_invoice IS NULL OR do.purchase_invoice = '')
          AND do.supplier = %(supplier)s
          AND COALESCE(ur.`date`, do.posting_date) BETWEEN %(from_date)s AND %(to_date)s
          {external_clause}
        GROUP BY do.name, dc.name, do.posting_date, do.quantity
        ORDER BY date, do.name
    """.format(
        external_clause="AND (do.transported_by = 'External Carrier' OR do.supplier IS NOT NULL)"
        if cint(external_only) else ""
    )

    base = frappe.db.sql(q, params, as_dict=True)

    rows = _as_rows([
        {
            "unloading_receipt": None,
            "delivery_order": r.get("delivery_order"),
            "download_command": r.get("download_command"),
            "date": r.get("date"),
            "delivered_quantity": r.get("delivered_quantity"),
        } for r in base
    ], "DO")

    rows = _enrich_driver_vehicle(rows)
    return {"status": "ok" if rows else "none", "rows": rows}

@frappe.whitelist()
def get_unbilled_less_dev_unload_purchase(supplier=None, from_date=None, to_date=None, external_only=1):
    if not supplier or not from_date or not to_date:
        return {"status": "none", "rows": []}

    # 1) هات UR داخل الفترة (خارجي فقط)
    ur_res = get_unbilled_unloading_purchase(
        supplier=supplier, from_date=from_date, to_date=to_date, external_only=external_only
    ) or {}
    ur_rows = ur_res.get("rows", []) or []

    # 2) هات DO داخل الفترة (خارجي فقط) — الحالية قد ترجع DO سواء لها UR أو لا
    do_res = get_unbilled_delivery_purchase(
        supplier=supplier, from_date=from_date, to_date=to_date, external_only=external_only
    ) or {}
    do_rows = do_res.get("rows", []) or []

    # 3) استبعد أي DO له UR (أولوية دائماً لـ UR عند التعادل/الوجود)
    do_has_ur = {r.get("delivery_order") for r in ur_rows if r.get("delivery_order")}
    do_rows = [r for r in do_rows if r.get("delivery_order") not in do_has_ur]

    rows = []
    rows.extend(ur_rows)   # أولوية التفريغ
    rows.extend(do_rows)   # ثم أوامر التحميل التي لا UR لها

    return {"status": "ok" if rows else "none", "rows": rows}

# ============ Build / Create Purchase Invoice ============

@frappe.whitelist()
def build_purchase_invoice_for_external_carrier(
    supplier,
    lines=None,
    posting_date=None,
    submit=1,
    service_item=None,  
    unit_rate=None,      
    description=None    
):
    import json
    from frappe.utils import flt, cint, nowdate

    if not supplier:
        frappe.throw("Supplier is required.")

    # فكّ JSON إن لزم
    if isinstance(lines, str):
        lines = json.loads(lines or "[]")
    lines = lines or []
    if not lines:
        frappe.throw("No lines to bill.")

    # إجمالي الكمية من الحقول المتاحة في الواجهة
    total_qty = 0.0
    for ln in lines:
        total_qty += flt(ln.get("delivered_quantity") or ln.get("qty") or 0)
    if total_qty <= 0:
        frappe.throw("Total quantity is zero.")

    rate = flt(unit_rate or 0)
    if rate <= 0:
        frappe.throw("Unit rate must be greater than zero.")

    # ===== Settings / Company =====
    try:
        settings = frappe.get_single("TrackPRO Setting")
    except Exception:
        settings = frappe.get_single("TrackPro Settings")

    company = (getattr(settings, "company", None)
               or frappe.defaults.get_user_default("Company")
               or frappe.db.get_default("company"))
    if not company:
        frappe.throw("Company is not set in TrackPRO Settings or User Defaults.")

    cm = frappe.get_meta("Company")
    def _co(field):
        return frappe.db.get_value("Company", company, field) if cm.has_field(field) else None

    # حسابات ومراكز تكلفة
    expense_account = (getattr(settings, "cost_account", None)
                       or _co("default_expense_account"))
    cost_center = (getattr(settings, "cost_center", None)
                   or _co("cost_center")
                   or _co("default_cost_center"))
    if not getattr(settings, "cost_center", None) and cost_center:
        frappe.msgprint(
            f"تنبيه: مركز التكلفة غير مضبوط في الإعدادات. تم استخدام الافتراضي للشركة: <b>{cost_center}</b>.",
            alert=True, indicator="orange"
        )
    elif not cost_center:
        frappe.throw(f"لا يوجد مركز تكلفة في الإعدادات ولا افتراضي على الشركة ({company}).")

    # ضريبة شراء (إن وجدت)
    purchase_taxes_template = getattr(settings, "purchase_taxes_and_charges_template", None)

    # صنف الخدمة
    item_code = (service_item
                 or getattr(settings, "purchase_service_item", None)
                 or getattr(settings, "item", None))
    if not item_code:
        frappe.throw("Service Item for purchase is not set (argument `service_item` or TrackPRO Settings.purchase_service_item / item).")

    # UOM الافتراضي للصنف
    uom = frappe.db.get_value("Item", item_code, "stock_uom") or "Nos"

    # ===== إنشاء فاتورة مشتريات بسطر واحد مجمّع =====
    pi = frappe.new_doc("Purchase Invoice")
    pi.supplier = supplier
    pi.company = company
    pi.posting_date = posting_date or nowdate()
    pi.set_posting_time = 1

    # إيقاف تأثير قواعد التسعير
    pi.ignore_pricing_rule = 1
    pi.flags.ignore_pricing_rule = 1

    if purchase_taxes_template:
        pi.taxes_and_charges = purchase_taxes_template

    pi.append("items", {
        "item_code": item_code,
        "description": description or "External Transport Service (Aggregated)",
        "qty": total_qty,
        "uom": uom,
        "rate": rate,
        "expense_account": expense_account,
        "cost_center": cost_center,
        "discount_percentage": 0,
        "discount_amount": 0,
    })

    # احسب الضرائب والإجماليات
    pi.set_missing_values()
    pi.calculate_taxes_and_totals()

    # احفظ وقدّم حسب الطلب
    pi.insert(ignore_permissions=True)
    if cint(submit):
        pi.submit()

    # ===== ربط UR/DO بالفاتورة وتحديث الحالة =====
    ur_names, do_names = set(), set()
    for ln in lines:
        ur = ln.get("unloading_receipt")
        if ur:
            ur_names.add(ur)
            do = frappe.db.get_value("Unloading Receipt", ur, "delivery_order")
            if do:
                do_names.add(do)
        else:
            do = ln.get("delivery_order")
            if do:
                do_names.add(do)

    # حدّث UR: purchase_invoice + الحالة (Invoiced لو عنده Sales، وإلا Purchase Billing)
    if ur_names:
        frappe.db.sql(
            """
            UPDATE `tabUnloading Receipt`
            SET
                purchase_invoice = %(pi)s
            WHERE name IN %(names)s
            """,
            {"pi": pi.name, "names": tuple(ur_names)},
        )
        if frappe.get_meta("Unloading Receipt").has_field("status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET status = CASE
                    WHEN IFNULL(sales_invoice, '') != '' THEN 'Invoiced'
                    ELSE 'Purchase Billing'
                END
                WHERE name IN %(names)s
                """,
                {"names": tuple(ur_names)},
            )
        if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET billing_status = CASE
                    WHEN IFNULL(sales_invoice, '') != '' THEN 'Invoiced'
                    ELSE 'Purchase Billing'
                END
                WHERE name IN %(names)s
                """,
                {"names": tuple(ur_names)},
            )

    # حدّث DO: purchase_invoice
    for do in do_names:
        if frappe.get_meta("Delivery Order").has_field("purchase_invoice"):
            frappe.db.set_value("Delivery Order", do, "purchase_invoice", pi.name, update_modified=False)
        # (اختياري) حدّث حالة الـ DO فورًا لو حابب
        try:
            d = frappe.get_doc("Delivery Order", do)
            if hasattr(d, "update_status"):
                d.update_status()
                d.db_update()
        except Exception:
            pass

    return {"status": "ok", "name": pi.name}

@frappe.whitelist()
def create_purchase_invoice(docname, unit_rate=None, service_item=None, description=None, submit=0):
    import frappe
    from frappe.utils import flt, nowdate, cint

    # 1) حمل الباتش
    batch = frappe.get_doc("Purchase Billing Batch", docname)

   # 2) جهّز السطور من الجدول الابن
    lines = []
    basis = (batch.get("billing_basis") or [])           # المختارة (لو فيه اختيار)
    if not basis:
        basis = (batch.get("unbilled") or [])            # fallback لو المستخدم لسه ما نقلها

    for r in basis:
        # رقم المستند
        ref = (r.get("receipt_number")
            or r.get("unloading_receipt")
            or r.get("delivery_order")
            or "").strip()
        if not ref:
            continue

        # الكمية المعلَنة في الجدول (الأولوية للي ظاهر للمستخدم)
        qty = flt(r.get("delivered_quantity") or r.get("quantity") or r.get("qty") or 0)

        # حدّد نوع المرجع
        is_ur = frappe.db.exists("Unloading Receipt", ref)
        is_do = frappe.db.exists("Delivery Order", ref) if not is_ur else False

        # لو الكمية مش موجودة، نحاول نقرأها من المستند نفسه
        if not qty:
            if is_ur:
                qty = flt(frappe.db.get_value("Unloading Receipt", ref, "unloaded_quantity") or 0)
                if not qty:
                    qty = flt(frappe.db.get_value("Unloading Receipt", ref, "delivered_quantity") or 0)
            elif is_do:
                qty = flt(frappe.db.get_value("Delivery Order", ref, "quantity") or 0)

        # لو أساس الفوتر "Which is less?" ومتاح UR و DO، خذ الأقل
        if (batch.get("billing_is_based_on") == "Which is less?") and is_ur:
            do_name = frappe.db.get_value("Unloading Receipt", ref, "delivery_order")
            if do_name:
                do_qty = flt(frappe.db.get_value("Delivery Order", do_name, "quantity") or 0)
                ur_qty = qty or flt(frappe.db.get_value("Unloading Receipt", ref, "unloaded_quantity") or 0)
                qty = min([q for q in (do_qty, ur_qty) if q > 0] or [qty])

        if qty <= 0:
            continue

        if is_ur:
            lines.append({"unloading_receipt": ref, "delivered_quantity": qty})
        elif is_do:
            lines.append({"delivery_order": ref, "delivered_quantity": qty})

    if not lines:
        frappe.throw("No billable lines were found in the batch.")


    # 3) المورّد والسعر/الصنف
    supplier = (batch.get("supplier") or "").strip()
    if not supplier:
        frappe.throw("Supplier is required on the batch.")
    rate = flt(unit_rate or batch.get("unit_rate") or 0)
    if rate <= 0:
        frappe.throw("Unit rate must be greater than zero.")
    item = service_item or batch.get("service_item")

    # 4) ابني الفاتورة (حفظ فقط بدون Submit)
    res = build_purchase_invoice_for_external_carrier(
        supplier=supplier,
        lines=lines,
        posting_date=nowdate(),
        submit=cint(submit),          # هنمرّر 0 عشان Save فقط
        service_item=item,
        unit_rate=rate,
        description=description or f"External Transport Service (Batch: {batch.name})"
    )
    pi_name = res.get("name")

    # 5) اكتب اسم الفاتورة داخل الباتش في حقل الربط (purchase_invoice أو “برشيز انفيس”)
    pb_meta = frappe.get_meta("Purchase Billing Batch")
    target_field = None
    if pb_meta.has_field("purchase_invoice"):
        target_field = "purchase_invoice"
    else:
        # دور على حقل ليبله عربي "برشيز انفيس" أو "فاتورة الشراء"
        for df in pb_meta.fields:
            lbl = (df.label or "").strip()
            if lbl in ("برشيز انفيس", "فاتورة الشراء", "Purchase Invoice"):
                target_field = df.fieldname
                break

    data = {"status": "Invoiced" if cint(submit) else "Purchase Billing"}
    if target_field:
        data[target_field] = pi_name
    batch.db_set(data, update_modified=False)

    # 6) رجّع الاسم + route علشان الواجهة تنقلك للفاتورة مباشرة
    return {"name": pi_name, "route": ["Form", "Purchase Invoice", pi_name]}
