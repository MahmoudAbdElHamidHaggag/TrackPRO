# Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe.utils import flt

class PurchaseBillingBatch(Document):
    def validate(self):
        # يُستدعى عند كل حفظ (جديد/تعديل) قبل الكتابة في قاعدة البيانات
        self._recompute_aggregates()
        self._compute_status()

    def on_update_after_submit(self):
        # لو بتسمح بتعديل بعد الإرسال، حافظ على نفس السلوك
        self._recompute_aggregates()
        self._compute_status()

    # -------- Helpers --------
    def _recompute_aggregates(self):
        """
        يجمع تلقائيًا كميات جدول unbilled ويعد الصفوف.
        يعتمد أسماء الحقول التي ذكرتها:
          - total_delivered_quantity (Float / Read Only)
          - unbilled_count (Int / Read Only)
        ويقرأ الكمية من delivered_quantity أو quantity أو qty داخل الصف.
        """
        total = 0.0
        count = 0

        for row in (self.get("unbilled") or []):
            qty = flt(
                getattr(row, "delivered_quantity", 0)
                or getattr(row, "quantity", 0)
                or getattr(row, "qty", 0)
                or 0
            )
            total += qty
            count += 1

        # اكتب القيم لو الحقول موجودة فعلاً على الدوك تايب
        if self.meta.has_field("total_delivered_quantity"):
            self.total_delivered_quantity = total
        if self.meta.has_field("unbilled_count"):
            self.unbilled_count = count

    def _compute_status(self):
        """
        يحدد الحالة بناءً على وجود purchase_invoice:
          - Invoiced   لو فيه رقم فاتورة مشتريات
          - Uninvoiced لو مفيش
        يكتب في أول حقل حالة متاح من: billing_status / invoice_status / status
        """
        status_field = None
        for fn in ("billing_status", "invoice_status", "status"):
            if self.meta.has_field(fn):
                status_field = fn
                break

        if status_field:
            self.set(status_field, "Invoiced" if getattr(self, "purchase_invoice", None) else "Uninvoiced")
