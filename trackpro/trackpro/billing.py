import frappe

BILLING_FIELD = "sales_invoice"
UR_STATUS_FIELD = "billing_status"
DO_STATUS_FIELD = "billing_status"  # لو مش موجود، _set_if_exists مش هيكتب

def _set_if_exists(doctype: str, name: str, field: str, value):
    if frappe.get_meta(doctype).has_field(field):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)

def _update_unloading_receipts_for_invoice(si_name: str, status: str, clear_link: bool):
    if not si_name:
        return
    ur_names = frappe.get_all("Unloading Receipt", filters={BILLING_FIELD: si_name}, pluck="name")
    for ur in ur_names:
        if clear_link and frappe.get_meta("Unloading Receipt").has_field(BILLING_FIELD):
            frappe.db.set_value("Unloading Receipt", ur, BILLING_FIELD, None, update_modified=False)
        _set_if_exists("Unloading Receipt", ur, UR_STATUS_FIELD, status)

def _update_delivery_orders_for_invoice(si_name: str, status: str, clear_link: bool):
    """اختياري: لو عندك DO عليه sales_invoice، نزبطه برضه."""
    if not si_name:
        return
    do_names = frappe.get_all("Delivery Order", filters={BILLING_FIELD: si_name}, pluck="name")
    for do in do_names:
        if clear_link and frappe.get_meta("Delivery Order").has_field(BILLING_FIELD):
            frappe.db.set_value("Delivery Order", do, BILLING_FIELD, None, update_modified=False)
        _set_if_exists("Delivery Order", do, DO_STATUS_FIELD, status)

def _update_batches_for_invoice(si_name: str, clear_link: bool, batch_status: str | None = None):
    if not si_name:
        return
    batch_names = frappe.get_all("Sales Billing Batch", filters={BILLING_FIELD: si_name}, pluck="name")
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
        _update_delivery_orders_for_invoice(target, status="Uninvoiced", clear_link=True)
        _update_batches_for_invoice(target, clear_link=True, batch_status="Uninvoiced")
    else:
        _update_unloading_receipts_for_invoice(doc.name, status="Invoiced", clear_link=False)
        _update_delivery_orders_for_invoice(doc.name, status="Invoiced", clear_link=False)
        _update_batches_for_invoice(doc.name, clear_link=False, batch_status="Invoiced")

def on_si_cancel(doc, method=None):
    _update_unloading_receipts_for_invoice(doc.name, status="Uninvoiced", clear_link=True)
    _update_delivery_orders_for_invoice(doc.name, status="Uninvoiced", clear_link=True)
    _update_batches_for_invoice(doc.name, clear_link=True, batch_status="Uninvoiced")


#################################################################


# ===== Purchases (PI + Purchase Billing Batch) =====

PBILLING_FIELD = "purchase_invoice"
UR_STATUS_FIELD = "billing_status"     
DO_STATUS_FIELD = "billing_status"      
PBB_STATUS_FIELD = "status"            

def _set_if_exists(doctype: str, name: str, field: str, value):
    if frappe.get_meta(doctype).has_field(field):
        frappe.db.set_value(doctype, name, field, value, update_modified=False)

def _update_unloading_receipts_for_pi(pi_name: str, status: str, clear_link: bool):
    if not pi_name:
        return
    ur_names = frappe.get_all("Unloading Receipt", filters={PBILLING_FIELD: pi_name}, pluck="name")
    for ur in ur_names:
        if clear_link and frappe.get_meta("Unloading Receipt").has_field(PBILLING_FIELD):
            frappe.db.set_value("Unloading Receipt", ur, PBILLING_FIELD, None, update_modified=False)
        _set_if_exists("Unloading Receipt", ur, UR_STATUS_FIELD, status)

def _update_delivery_orders_for_pi(pi_name: str, status: str, clear_link: bool):
    if not pi_name:
        return
    do_names = frappe.get_all("Delivery Order", filters={PBILLING_FIELD: pi_name}, pluck="name")
    for do in do_names:
        if clear_link and frappe.get_meta("Delivery Order").has_field(PBILLING_FIELD):
            frappe.db.set_value("Delivery Order", do, PBILLING_FIELD, None, update_modified=False)
        _set_if_exists("Delivery Order", do, DO_STATUS_FIELD, status)

def _update_purchase_batches_for_pi(pi_name: str, clear_link: bool, batch_status: str | None = None):
    if not pi_name:
        return
    batch_names = frappe.get_all("Purchase Billing Batch", filters={PBILLING_FIELD: pi_name}, pluck="name")
    for b in batch_names:
        data = {}
        if clear_link and frappe.get_meta("Purchase Billing Batch").has_field(PBILLING_FIELD):
            data[PBILLING_FIELD] = None
        if batch_status and frappe.get_meta("Purchase Billing Batch").has_field(PBB_STATUS_FIELD):
            data[PBB_STATUS_FIELD] = batch_status
        if data:
            frappe.db.set_value("Purchase Billing Batch", b, data, update_modified=False)


def _find_purchase_batches_for_pi(pi_name: str) -> list[str]:
    """حدد دفعات المشتريات (Purchase Billing Batch) التي تحتوي UR/DO مرتبطة بهذه الفاتورة."""
    if not pi_name:
        return []

    refs = set()

    # URs المربوطة بهذه الفاتورة
    ur_names = frappe.get_all("Unloading Receipt", filters={"purchase_invoice": pi_name}, pluck="name")
    refs.update(ur_names or [])

    # DOs المربوطة بهذه الفاتورة (لو تم حفظ الرابط عليها)
    do_names = frappe.get_all("Delivery Order", filters={"purchase_invoice": pi_name}, pluck="name")
    refs.update(do_names or [])

    if not refs:
        return []

    rows = frappe.db.sql(
        """
        select distinct c.parent
        from `tabBilling Basis` c
        where c.receipt_number in %(refs)s
        """,
        {"refs": tuple(refs)},
    )
    return [r[0] for r in rows] if rows else []


def _update_purchase_batches_for_pi(pi_name: str, *, clear_link: bool, batch_status: str | None = None) -> None:
    """حدّث حالة دفعات المشتريات المرتبطة بفاتورة مشتريات معينة.
       لا نعتمد على وجود حقل purchase_invoice على الدفعة؛ نضبطه فقط إن كان موجودًا."""
    batch_names = _find_purchase_batches_for_pi(pi_name)
    if not batch_names:
        return

    pb_meta = frappe.get_meta("Purchase Billing Batch")
    has_link_field = pb_meta.has_field("purchase_invoice")
    has_status_field = pb_meta.has_field("status")

    for b in batch_names:
        data = {}
        if has_status_field and batch_status:
            data["status"] = batch_status
        if has_link_field:
            data["purchase_invoice"] = None if clear_link else pi_name
        if data:
            frappe.db.set_value("Purchase Billing Batch", b, data, update_modified=False)


def on_pi_submit(doc, method=None):
    """Hook: عند اعتماد PI – ثبّت حالات UR، وحدّث دفعات المشتريات المرتبطة."""
    pi_name = doc.name

    ur_names = frappe.get_all("Unloading Receipt", filters={"purchase_invoice": pi_name}, pluck="name")
    if ur_names:
        # status / billing_status
        if frappe.get_meta("Unloading Receipt").has_field("status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET status = CASE
                    WHEN IFNULL(sales_invoice,'')!='' THEN 'Invoiced'
                    ELSE 'Purchase Billing'
                END
                WHERE name IN %(n)s
                """,
                {"n": tuple(ur_names)},
            )
        if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET billing_status = CASE
                    WHEN IFNULL(sales_invoice,'')!='' THEN 'Invoiced'
                    ELSE 'Purchase Billing'
                END
                WHERE name IN %(n)s
                """,
                {"n": tuple(ur_names)},
            )

    _update_purchase_batches_for_pi(pi_name, clear_link=False, batch_status="Invoiced")


def on_pi_cancel(doc, method=None):
    """Hook: عند إلغاء PI – نظّف الروابط وأعد الحالات، وحدّث دفعات المشتريات المرتبطة."""
    pi_name = doc.name

    ur_names = frappe.get_all("Unloading Receipt", filters={"purchase_invoice": pi_name}, pluck="name")
    if ur_names:
        # فكّ الربط
        if frappe.get_meta("Unloading Receipt").has_field("purchase_invoice"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET purchase_invoice = NULL
                WHERE name IN %(n)s
                """,
                {"n": tuple(ur_names)},
            )
        # status / billing_status ترجع حسب وجود Sales Invoice
        if frappe.get_meta("Unloading Receipt").has_field("status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET status = CASE
                    WHEN IFNULL(sales_invoice,'')!='' THEN 'Sales Billing'
                    ELSE 'Uninvoiced'
                END
                WHERE name IN %(n)s
                """,
                {"n": tuple(ur_names)},
            )
        if frappe.get_meta("Unloading Receipt").has_field("billing_status"):
            frappe.db.sql(
                """
                UPDATE `tabUnloading Receipt`
                SET billing_status = CASE
                    WHEN IFNULL(sales_invoice,'')!='' THEN 'Sales Billing'
                    ELSE 'Uninvoiced'
                END
                WHERE name IN %(n)s
                """,
                {"n": tuple(ur_names)},
            )

    _update_purchase_batches_for_pi(pi_name, clear_link=True, batch_status="Uninvoiced")

def on_pi_submit(doc, method=None):
    if getattr(doc, "is_return", 0):
        target = doc.get("return_against")
        _update_unloading_receipts_for_pi(target, status="Uninvoiced", clear_link=True)
        _update_delivery_orders_for_pi(target, status="Uninvoiced", clear_link=True)
        _update_purchase_batches_for_pi(target, clear_link=True, batch_status="Uninvoiced")
    else:
        _update_unloading_receipts_for_pi(doc.name, status="Invoiced", clear_link=False)
        _update_delivery_orders_for_pi(doc.name, status="Invoiced", clear_link=False)
        _update_purchase_batches_for_pi(doc.name, clear_link=False, batch_status="Invoiced")
        

def on_pi_cancel(doc, method=None):
    _update_unloading_receipts_for_pi(doc.name, status="Uninvoiced", clear_link=True)
    _update_delivery_orders_for_pi(doc.name, status="Uninvoiced", clear_link=True)
    _update_purchase_batches_for_pi(doc.name, clear_link=True, batch_status="Uninvoiced")




def _any_active_parents(child_doctype, child_filters, parenttype=None):
    """يرجع True لو لقى صفوف طفل تشير إلى آباء docstatus في (0,1)."""
    rows = frappe.get_all(child_doctype, filters=child_filters, fields=["parent", "parenttype"])
    parents = set()
    for r in rows:
        if parenttype and r.parenttype != parenttype:
            continue
        parents.add(r.parent)
    if not parents:
        return False
    for p in parents:
        ds = frappe.db.get_value(parenttype or child_doctype.rsplit(" ", 1)[0], p, "docstatus")
        if ds in (0, 1):
            return True
    return False

def prevent_cancel_unloading(doc, method=None):
    """UR: امنع الإلغاء لو مرتبط بفاتورة بيع/شراء غير ملغاة، أو داخل أي باتش قائم."""
    # 1) مرتبط بفاتورة؟
    si = getattr(doc, "sales_invoice", None)
    if si and frappe.db.get_value("Sales Invoice", si, "docstatus") != 2:
        frappe.throw(f"لا يمكن إلغاء سند التفريغ لأنه مرتبط بفاتورة بيع {si}. قم بإلغاء الفاتورة أولًا.")
    pi = getattr(doc, "purchase_invoice", None)
    if pi and frappe.db.get_value("Purchase Invoice", pi, "docstatus") != 2:
        frappe.throw(f"لا يمكن إلغاء سند التفريغ لأنه مرتبط بفاتورة مشتريات {pi}. قم بإلغاء الفاتورة أولًا.")

    # 2) موجود في Sales Billing Batch ؟ (child غالبًا Unbilled Unloading)
    in_sales_batch = _any_active_parents(
        child_doctype="Unbilled Unloading",
        child_filters={"unloading_receipt": doc.name},
        parenttype="Sales Billing Batch",
    )

    # 3) موجود في Purchase Billing Batch ؟ (child Billing Basis بعمود receipt_number)
    in_purchase_batch = _any_active_parents(
        child_doctype="Billing Basis",
        child_filters={"receipt_number": doc.name},
        parenttype="Purchase Billing Batch",
    )

    if in_sales_batch or in_purchase_batch:
        frappe.throw("لا يمكن إلغاء سند التفريغ لأنه مستخدم في Batch (مبيعات أو مشتريات). احذف/ألغِ الباتش أولًا.")

def prevent_cancel_delivery_order(doc, method=None):
    """DO: امنع الإلغاء لو له UR قائم، أو مرتبط بفاتورة، أو داخل باتش."""
    # 1) لو له UR docstatus 0/1
    has_ur = frappe.get_all("Unloading Receipt",
        filters={"delivery_order": doc.name, "docstatus": ["in", [0, 1]]}, limit=1)
    if has_ur:
        frappe.throw("لا يمكن إلغاء أمر التحميل لوجود سند/سندات تفريغ غير ملغاة مرتبطة به.")

    # 2) فواتير؟
    si = frappe.db.get_value("Delivery Order", doc.name, "sales_invoice")
    if si and frappe.db.get_value("Sales Invoice", si, "docstatus") != 2:
        frappe.throw(f"لا يمكن الإلغاء لأن الأمر مرتبط بفاتورة بيع {si}. قم بإلغاء الفاتورة أولًا.")
    pi = frappe.db.get_value("Delivery Order", doc.name, "purchase_invoice")
    if pi and frappe.db.get_value("Purchase Invoice", pi, "docstatus") != 2:
        frappe.throw(f"لا يمكن الإلغاء لأن الأمر مرتبط بفاتورة مشتريات {pi}. قم بإلغاء الفاتورة أولًا.")


    in_purchase_batch = _any_active_parents(
        child_doctype="Billing Basis",
        child_filters={"receipt_number": doc.name},
        parenttype="Purchase Billing Batch",
    )

    if in_purchase_batch:
        frappe.throw("لا يمكن إلغاء أمر التحميل لأنه مستخدم في Batch للمشتريات. احذف/ألغِ الباتش أولًا.")

