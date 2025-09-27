const BASIS_METHOD = {
  "Unloading Receipt": "trackpro.trackpro.api.get_unbilled_unloading",
  "Delivery Order": "trackpro.trackpro.api.get_unbilled_delivery",
  "Which is less?": "trackpro.trackpro.api.get_unbilled_less_dev_unload"
};

frappe.ui.form.on("Sales Billing Batch", {
  refresh(frm) {
    frm.__loading_unbilled = frm.__loading_unbilled || false;
    frm.__unbilled_sig = frm.__unbilled_sig || null;

    frm.set_query("contract_of_carriage", () => ({
      query: "trackpro.trackpro.api.search_contracts_with_pending_unloading",
      filters: { customer: frm.doc.customer || null }
    }));

    if (frm.fields_dict.download_command) {
      frm.set_query("download_command", () => ({
        query: "trackpro.trackpro.api.search_open_download_commands_with_pending_unloading",
        filters: { contract: frm.doc.contract_of_carriage || null }
      }));
    }

    if (frm.fields_dict.delivery_order) {
      frm.set_query("delivery_order", () => ({
        query: "trackpro.trackpro.api.search_open_delivery_orders",
        filters: { contract: frm.doc.contract_of_carriage || null }
      }));
    }

    if (!frm.is_new() && frm.doc.docstatus === 1) {
      frm.add_custom_button("Create Sales Invoice", () => {
        if (!frm.doc.unbilled_unloading || !frm.doc.unbilled_unloading.length) {
          frappe.msgprint("Please add at least one unloading receipt row.");
          return;
        }
        frappe.call({
          method: "trackpro.trackpro.api.create_sales_invoice",
          args: { docname: frm.doc.name },
          callback(r) {
            if (r.message) frappe.set_route("Form", "Sales Invoice", r.message);
          }
        });
      });
    }

    if (frm.fields_dict.unbilled_unloading) {
      const $w = frm.fields_dict.unbilled_unloading.grid.wrapper;
      $w.off("change.trackpro");
      $w.on("change.trackpro", function () { recompute_totals(frm); });
    }

    // مهم: لا تنادِ maybe_load هنا لتجنب تعديل المستند بعد الحفظ مباشرة
  },

  customer(frm) {
    frm.set_value("contract_of_carriage", null);
    if (frm.fields_dict.download_command) frm.set_value("download_command", null);
    if (frm.fields_dict.delivery_order) frm.set_value("delivery_order", null);
    clear_unbilled_table(frm);
    frm.__unbilled_sig = null;
  },

  billing_is_based_on(frm) {
    if (!frm.doc.billing_is_based_on) {
      clear_unbilled_table(frm);
      frappe.msgprint("لابد من اختيار قيمة في الحقل: Billing is based on.");
      frm.set_focus("billing_is_based_on");
      frm.__unbilled_sig = null;
      return;
    }
    maybe_load(frm);
  },

  contract_of_carriage(frm) {
    if (frm.fields_dict.download_command) frm.set_value("download_command", null);
    if (frm.fields_dict.delivery_order) frm.set_value("delivery_order", null);
    if (!frm.doc.contract_of_carriage) return;

    frappe.db.get_value("Contract of Carriage", frm.doc.contract_of_carriage, "customer")
      .then(r => {
        const cust = r.message?.customer;
        if (cust && cust !== frm.doc.customer) frm.set_value("customer", cust);
        if (!frm.doc.billing_is_based_on) {
          clear_unbilled_table(frm);
          frappe.msgprint("لابد من اختيار قيمة في الحقل: Billing is based on.");
          frm.set_focus("billing_is_based_on");
          frm.__unbilled_sig = null;
          return;
        }
        frm.__unbilled_sig = null; // التوقيع يتغير لأن العقد تغير
        maybe_load(frm);
      });
  },

  from_date(frm) { frm.__unbilled_sig = null; maybe_load(frm); },
  to_date(frm)   { frm.__unbilled_sig = null; maybe_load(frm); }
});

frappe.ui.form.on("Unbilled Unloading", {
  delivered_quantity(frm) { recompute_totals(frm); },
  unbilled_unloading_add(frm) { recompute_totals(frm); },
  unbilled_unloading_remove(frm) { recompute_totals(frm); }
});

function maybe_load(frm) {
  if (frm.__loading_unbilled) return;

  const basis = frm.doc.billing_is_based_on;
  if (!basis) return;
  if (!frm.doc.customer) return;
  if (!frm.doc.contract_of_carriage) return;

  // لا تحميل قبل إدخال التاريخين
  if (!frm.doc.from_date || !frm.doc.to_date) return;
  if (frm.doc.from_date > frm.doc.to_date) {
    frappe.msgprint(__("From Date cannot be after To Date."));
    return;
  }

  // توقيع يمنع إعادة التحميل لنفس المعايير ويمنع تدوير الحفظ
  const sig = JSON.stringify({
    basis,
    contract: frm.doc.contract_of_carriage,
    from: frm.doc.from_date,
    to: frm.doc.to_date
  });
  if (frm.__unbilled_sig === sig) return;

  frm.__loading_unbilled = true;

  clear_unbilled_table(frm);

  const method = BASIS_METHOD[basis];
  if (!method) {
    frm.__loading_unbilled = false;
    return;
  }

  frappe.call({
    method,
    args: {
      contract: frm.doc.contract_of_carriage,
      from_date: frm.doc.from_date,
      to_date: frm.doc.to_date
    },
    freeze: true,
    freeze_message: __("Loading..."),
    callback(res) {
      const m = res.message || {};
      if (!m.status) return;

      if (m.status === "none") {
        frappe.msgprint("No documents found for this contract in the selected period.");
        return;
      }
      if (m.status === "all_billed") {
        if (m.message) frappe.msgprint(m.message);
        else frappe.msgprint("All items are billed for the selected period.");
        return;
      }

      (m.receipts || []).forEach(row => {
        const qty = parseFloat(row.unloaded_quantity ?? row.loaded_quantity ?? row.quantity ?? 0) || 0;
        const d = frm.add_child("unbilled_unloading");
        d.unloading_receipt = row.name;
        d.delivered_quantity = qty;
        d.driver = row.driver;
        d.vehicle = row.vehicle;
        d.date = row.date;
        if (row.delivery_order && frm.fields_dict.delivery_order) d.delivery_order = row.delivery_order;
      });

      frm.refresh_field("unbilled_unloading");
      recompute_totals(frm);

      // ثبّت التوقيع بعد نجاح التحميل لمنع إعادة التحميل في refresh التالي
      frm.__unbilled_sig = sig;
    },
    always() {
      frm.__loading_unbilled = false;
    }
  });
}

function clear_unbilled_table(frm) {
  const had_rows = (frm.doc.unbilled_unloading || []).length > 0;
  if (had_rows) {
    frm.clear_table("unbilled_unloading");
    frm.refresh_field("unbilled_unloading");
  }
  // اضبط المجاميع فقط إذا اختلفت لتقليل تغييرات الوثيقة أثناء الحفظ
  if ((frm.doc.count_unbilled_unloading || 0) !== 0) frm.set_value("count_unbilled_unloading", 0);
  if ((frm.doc.total_delivered_quantity || 0) !== 0) frm.set_value("total_delivered_quantity", 0);
}

function recompute_totals(frm) {
  const rows = frm.doc.unbilled_unloading || [];
  const count = rows.length;
  const total = rows.reduce((acc, r) => acc + (parseFloat(r.delivered_quantity) || 0), 0);

  if ((frm.doc.count_unbilled_unloading || 0) !== count) {
    frm.set_value("count_unbilled_unloading", count);
  }
  if ((frm.doc.total_delivered_quantity || 0) !== total) {
    frm.set_value("total_delivered_quantity", total);
  }

  frm.refresh_field("count_unbilled_unloading");
  frm.refresh_field("total_delivered_quantity");
}
