// Copyright (c) 2025, MahmoudAbdElHamidHaggag and contributors
// For license information, please see license.txt
const PBB_PURCHASE_METHOD = {
  "Unloading Receipt": "trackpro.trackpro.api.get_unbilled_unloading_purchase",
  "Delivery Order": "trackpro.trackpro.api.get_unbilled_delivery_purchase",
  "Which is less?": "trackpro.trackpro.api.get_unbilled_less_dev_unload_purchase",
};
const PBB_AGG_FIELDS = {
  sum_candidates: ["total_qty", "total_quantity", "sum_qty", "total_delivered_quantity"],
  count_candidates: ["row_count", "count_receipt", "lines_count", "unbilled_count"],
  rate_candidates: ["rate", "price", "unit_rate", "unit_price"]
};

function pbb_pick_field(frm, names) {
  return (names || []).find(n => frm.fields_dict && frm.fields_dict[n]) || null;
}

function pbb_row_qty(r) {
  return Number(r.delivered_quantity ?? r.quantity ?? r.qty ?? 0) || 0;
}

function pbb_recalc(frm) {
  const rows = frm.doc.unbilled || [];
  const total = rows.reduce((acc, r) => acc + pbb_row_qty(r), 0);
  const count = rows.length;

  const sum_fn = pbb_pick_field(frm, PBB_AGG_FIELDS.sum_candidates);
  const cnt_fn = pbb_pick_field(frm, PBB_AGG_FIELDS.count_candidates);

  if (sum_fn) frm.set_value(sum_fn, total);
  if (cnt_fn) frm.set_value(cnt_fn, count);
}

function pbb_pick_rate(frm) {
  const rate_fn = pbb_pick_field(frm, PBB_AGG_FIELDS.rate_candidates);
  return rate_fn ? Number(frm.doc[rate_fn] || 0) : 0;
}

function pbb_set_status(frm) {
  const st_fn = ["billing_status", "status", "invoice_status"]
    .find(n => frm.fields_dict && frm.fields_dict[n]);
  if (!st_fn) return;
  frm.set_value(st_fn, frm.doc.purchase_invoice ? "Invoiced" : "Uninvoiced");
}




function pbb_clear(frm) {
  if (frm.doc.unbilled && frm.doc.unbilled.length) {
    frm.clear_table("unbilled");
    frm.refresh_field("unbilled");
  }
}

function pbb_add_rows(frm, rows) {
  if (!Array.isArray(rows) || !rows.length) return;
  rows.forEach((r) => {
    const d = frm.add_child("unbilled"); // Child doctype: Billing Basis
    d.receipt_number = r.receipt_number || r.unloading_receipt || r.delivery_order || "";
    d.date = r.date || r.posting_date || null;
    d.delivered_quantity = r.delivered_quantity || r.quantity || r.qty || 0;
    d.driver = r.driver || "";
    d.vehicle = r.vehicle || "";
  });
  frm.refresh_field("unbilled");
}

function pbb_ready(frm) {
  // كل القيم لازم تكون موجودة — بدونها لا نفعل شيئًا
  return !!(frm.doc.supplier && frm.doc.from_date && frm.doc.to_date && frm.doc.billing_is_based_on);
}

function pbb_fetch(frm) {
  if (!(frm.doc.supplier && frm.doc.from_date && frm.doc.to_date && frm.doc.billing_is_based_on)) return;

  const method = PBB_PURCHASE_METHOD[frm.doc.billing_is_based_on];
  if (!method) return;

  // امسح القديم وصامتًا
  if (frm.doc.unbilled && frm.doc.unbilled.length) {
    frm.clear_table("unbilled");
    frm.refresh_field("unbilled");
  }

  frappe.call({
    method,
    args: {
      supplier: frm.doc.supplier,
      from_date: frm.doc.from_date,
      to_date: frm.doc.to_date,
      external_only: 1
    },
    callback: (r) => {
      const rows = (r.message && r.message.rows) || [];
      rows.forEach((rr) => {
        const d = frm.add_child("unbilled");
        d.receipt_number = rr.receipt_number || rr.unloading_receipt || rr.delivery_order || "";
        d.date = rr.date || null;
        d.delivered_quantity = rr.delivered_quantity || 0;
        d.driver = rr.driver || "";
        d.vehicle = rr.vehicle || "";
      });
      frm.refresh_field("unbilled");
      pbb_recalc(frm);
    }
  });
}

frappe.ui.form.on("Purchase Billing Batch", {
  refresh(frm) {
    if (!frm.is_new() && frm.doc.docstatus === 1 && frm.doc.status !== "Invoiced") {
      frm.add_custom_button(__("Create Purchase Invoice (Save)"), async () => {
        if (frm.is_dirty()) await frm.save();

        const rate = (typeof pbb_pick_rate === "function" ? pbb_pick_rate(frm) : frm.doc.unit_rate) || 0;
        if (!rate) {
          frappe.msgprint(__("ضع سعر الوحدة أولًا.")); 
          return;
        }

        try {
          const { message } = await frappe.call({
            method: "trackpro.trackpro.api.create_purchase_invoice",
            args: { docname: frm.doc.name, unit_rate: rate, submit: 0 }, // حفظ فقط
            freeze: true,
            freeze_message: __("Building Purchase Invoice..."),
          });

          const name = typeof message === "string" ? message : message?.name;
          const route = Array.isArray(message?.route) ? message.route : ["Form", "Purchase Invoice", name];

          await frm.reload_doc();                 // السيرفر كتب اسم الفاتورة في الباتش
          frappe.set_route(...route);             // روّت للفاتورة مباشرة
        } catch (e) {
          frappe.msgprint({
            message: (e && e.message) || __("Failed to create Purchase Invoice."),
            indicator: "red"
          });
        }
      }).addClass("btn-primary");
    }

    if (typeof pbb_set_status === "function") pbb_set_status(frm);
  },

  supplier(frm) { if (typeof pbb_fetch === "function") pbb_fetch(frm); },
  from_date(frm) { if (typeof pbb_fetch === "function") pbb_fetch(frm); },
  to_date(frm) { if (typeof pbb_fetch === "function") pbb_fetch(frm); },
  billing_is_based_on(frm) { if (typeof pbb_fetch === "function") pbb_fetch(frm); },

  // الجدول الصحيح في المشتريات: Billing Basis
  billing_basis_add(frm) { if (typeof pbb_recalc === "function") pbb_recalc(frm); },
  billing_basis_remove(frm) { if (typeof pbb_recalc === "function") pbb_recalc(frm); },
});

frappe.ui.form.on("Billing Basis", {
  delivered_quantity(frm) { if (typeof pbb_recalc === "function") pbb_recalc(frm); },
  quantity(frm) { if (typeof pbb_recalc === "function") pbb_recalc(frm); },
  qty(frm) { if (typeof pbb_recalc === "function") pbb_recalc(frm); }
});
