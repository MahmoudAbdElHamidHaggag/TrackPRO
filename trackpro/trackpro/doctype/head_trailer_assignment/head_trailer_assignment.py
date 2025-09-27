# Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
# For license information, please see license.txt

import frappe
from frappe.utils import now_datetime, add_to_date, get_datetime
from frappe.model.document import Document
from trackpro.trackpro.api import assert_can_change_head_trailer

# ملاحظة: غيّر أسماء الحقول هنا لو كانت مختلفة فعليًا في الدوكتايب عندك
FIELD_TRACTOR = "tractor_vehicle"
FIELD_TRAILER = "trailer_vehicle"
FIELD_FROM    = "from_datetime"
FIELD_TO      = "to_datetime"
FIELD_STATUS  = "status"


class HeadTrailerAssignment(Document):
    def validate(self):
        at = get_datetime(self.from_datetime) if self.from_datetime else now_datetime()
        assert_can_change_head_trailer(self.tractor_vehicle, at)

    def before_cancel(self):
        assert_can_change_head_trailer(self.tractor_vehicle, now_datetime())



def on_before_insert(doc, method=None):
    """
    قبل إنشاء تعيين جديد:
    - اقفل أي تعيين مفتوح لنفس الراس/الذيل (to_datetime فارغ) بتحديد to_datetime = from_datetime - 1 ثانية
    """
    _close_open_assignments_if_needed(doc)

def on_validate(doc, method=None):
    _close_open_assignments_if_needed(doc)  # <-- أضِف السطر ده أولاً
    _validate_no_overlap(doc)
    _apply_status(doc)


def on_before_submit(doc, method=None):
    _apply_status(doc)

def on_update(doc, method=None):
    # كل تعديل: راجع الحالة (خصوصًا لو اتعبّى to_datetime)
    _apply_status(doc)

# ---------------------- Core Logic ----------------------

def _apply_status(doc):
    now = now_datetime()
    start = get_datetime(doc.get(FIELD_FROM)) if doc.get(FIELD_FROM) else None
    end   = get_datetime(doc.get(FIELD_TO)) if doc.get(FIELD_TO) else None

    # حالة بسيطة حسب طلبك:
    # Active: المدة بدون نهاية أو لم تنتهِ بعد
    # Ended : يوجد To Datetime وانتهت المدة (<= الآن) أو تم تحديد نهاية أصلاً
    if end:
        doc.set(FIELD_STATUS, "Ended" if end <= now else "Active")
    else:
        # مافيش نهاية => Active دايمًا
        doc.set(FIELD_STATUS, "Active")

def _validate_no_overlap(doc):
    """
    يمنع وجود فترات متداخلة لنفس الراس أو الذيل.
    تعريف التداخل بين [start, end] و [s2, e2]:
      start < e2 AND s2 < end
    لو end أو e2 فاضية => تُعتبر مفتوحة (تعامل كـ +inf)
    """
    start = get_datetime(doc.get(FIELD_FROM))
    end   = get_datetime(doc.get(FIELD_TO)) if doc.get(FIELD_TO) else None

    if not start:
        frappe.throw("From Datetime is required.")

    for role_field, label in [(FIELD_TRACTOR, "Tractor Vehicle"), (FIELD_TRAILER, "Trailer Vehicle")]:
        val = doc.get(role_field)
        if not val:
            continue

        # ابحث عن أي سجل مختلف عن الحالي لنفس المركبة/المقطورة وفترته تتقاطع مع فترة هذا السجل
        overlaps = _find_overlaps(
            vehicle_field=role_field,
            vehicle_value=val,
            start=start,
            end=end,
            exclude_name=doc.name if doc.name else None
        )
        if overlaps:
            msg = f"{label} '{val}' already assigned in an overlapping period: {', '.join(overlaps)}"
            frappe.throw(msg)

def _find_overlaps(vehicle_field, vehicle_value, start, end, exclude_name=None):
    """
    يرجع أسماء السجلات المتداخلة.
    """
    conditions = [
        f"`{vehicle_field}` = %(veh)s",
        "docstatus < 2"  # استبعد الملغى فقط
    ]
    params = {"veh": vehicle_value}

    if exclude_name:
        conditions.append("name != %(nm)s")
        params["nm"] = exclude_name

    # هنجلب نطاق واسع ونفلتر في بايثون لضبط منطق نهاية مفتوحة
    rows = frappe.db.sql(f"""
        SELECT name, {FIELD_FROM} as s, {FIELD_TO} as e
        FROM `tabHead Trailer Assignment`
        WHERE {" AND ".join(conditions)}
    """, values=params, as_dict=True)

    overlapping = []
    for r in rows:
        s2 = get_datetime(r.s) if r.s else None
        e2 = get_datetime(r.e) if r.e else None  # ممكن تكون None (مفتوحة)

        if not s2:
            continue

        # اعتبر end المفتوحة كمالانهاية: نحقق الشرط start < e2 AND s2 < end
        # لو end (بتاع السجل الحالي) None => اعتبرها +inf
        # لو e2 None => اعتبرها +inf
        cond1 = start < (e2 or add_to_date(start, years=100))  # تقريب لمالانهاية
        cond2 = s2   < (end   or add_to_date(s2,   years=100))
        if cond1 and cond2:
            overlapping.append(r.name)

    return overlapping

def _close_open_assignments_if_needed(doc):
    """
    لما ننشئ تعيين جديد:
    - لو في تعيين مفتوح لنفس الراس/الذيل (to_datetime فارغ)، نقفله عند from_datetime - 1 ثانية.
    """
    start = get_datetime(doc.get(FIELD_FROM))
    if not start:
        return

    def close_for(field):
        val = doc.get(field)
        if not val:
            return
        rows = frappe.db.get_all(
            "Head Trailer Assignment",
            filters={
                field: val,
                FIELD_TO: ["in", [None, ""]],
                "name": ["!=", doc.name or ""],
                "docstatus": ["<", 2],
            },
            fields=["name", FIELD_FROM]
        )
        for r in rows:
            prev = frappe.get_doc("Head Trailer Assignment", r.name)
            # اقفل السابق عند ثانية قبل بداية الجديد
            prev.set(FIELD_TO, add_to_date(start, seconds=-1))
            _apply_status(prev)
            prev.save(ignore_permissions=True)

    close_for(FIELD_TRACTOR)
    close_for(FIELD_TRAILER)

# ---------------------- (اختياري) API عام لسجلات أخرى ----------------------

@frappe.whitelist()
def close_open_assignment_for_vehicle(vehicle, when=None, as_trailer=False):
    """
    يمكنك نداء هذه الوظيفة من أي DocType آخر (مثلاً لما تربط مركبة/مقطورة بسير عمل جديد)
    لقفل التعيين الحالي تلقائيًا.
      vehicle: اسم المركبة
      when   : datetime string؛ لو None هستخدم now()
      as_trailer: لو True هتعامل مع المركبة كمقطورة (trailer)
    """
    when_dt = get_datetime(when) if when else now_datetime()
    field = FIELD_TRAILER if as_trailer else FIELD_TRACTOR

    rows = frappe.db.get_all(
        "Head Trailer Assignment",
        filters={field: vehicle, FIELD_TO: ["in", [None, ""]], "docstatus": ["<", 2]},
        fields=["name"]
    )
    for r in rows:
        prev = frappe.get_doc("Head Trailer Assignment", r.name)
        prev.set(FIELD_TO, add_to_date(when_dt, seconds=-1))
        _apply_status(prev)
        prev.save(ignore_permissions=True)
    return {"closed": [r.name for r in rows]}
