frappe.ui.form.on("Sales Billing Batch", {
  refresh(frm) {

    frm.set_query("contract_of_carriage", () => ({
      query: "trackpro.trackpro.api.search_contracts_with_pending_unloading",
      filters: { customer: frm.doc.customer || null },
    }));

    if (frm.fields_dict.download_command) {
      frm.set_query("download_command", () => ({
        query: "trackpro.trackpro.api.search_open_download_commands_with_pending_unloading",
        filters: { contract: frm.doc.contract_of_carriage || null },
      }));
    }

    if (frm.fields_dict.delivery_order) {
      frm.set_query("delivery_order", () => ({
        query: "trackpro.trackpro.api.search_open_delivery_orders",
        filters: { contract: frm.doc.contract_of_carriage || null },
      }));
    }

    // Create SI button
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
          },
        });
      });
    }


    if (frm.fields_dict.unbilled_unloading) {
      frm.fields_dict.unbilled_unloading.grid.wrapper.off("change.trackpro");
      frm.fields_dict.unbilled_unloading.grid.wrapper.on("change.trackpro", function () {
        recompute_totals(frm);
      });
    }
  },

  customer(frm) {
    frm.set_value("contract_of_carriage", null);
    if (frm.fields_dict.download_command) frm.set_value("download_command", null);
    if (frm.fields_dict.delivery_order) frm.set_value("delivery_order", null);

    frm.clear_table("unbilled_unloading");
    frm.refresh_field("unbilled_unloading");
    frm.set_value("count_unbilled_unloading", 0);
    frm.set_value("total_delivered_quantity", 0);
    frm.refresh_fields(["count_unbilled_unloading", "total_delivered_quantity"]);
  },

  contract_of_carriage(frm) {
    if (frm.fields_dict.download_command) frm.set_value("download_command", null);
    if (frm.fields_dict.delivery_order) frm.set_value("delivery_order", null);

    if (!frm.doc.contract_of_carriage) return;

    frappe.db
      .get_value("Contract of Carriage", frm.doc.contract_of_carriage, "customer")
      .then((r) => {
        const cust = r.message && r.message.customer;
        if (cust && cust !== frm.doc.customer) frm.set_value("customer", cust);

        frappe.call({
          method: "trackpro.trackpro.api.get_unbilled_unloading",
          args: { contract: frm.doc.contract_of_carriage },
          callback(res) {
            frm.clear_table("unbilled_unloading");
            frm.refresh_field("unbilled_unloading");
            frm.set_value("count_unbilled_unloading", 0);
            frm.set_value("total_delivered_quantity", 0);

            if (!res.message) return;

            if (res.message.status === "none") {
              frappe.msgprint("No unloading receipts have been created for this contract.");
              return;
            }

            if (res.message.status === "all_billed") {
              frappe.msgprint("All unloading receipts for this contract have been billed.");
              return;
            }

            (res.message.receipts || []).forEach((row) => {
              let d = frm.add_child("unbilled_unloading");
              d.unloading_receipt = row.name;
              d.delivered_quantity = row.unloaded_quantity;
            });

            frm.refresh_field("unbilled_unloading");
            recompute_totals(frm);
          },
        });
      });
  },
});

frappe.ui.form.on("Unbilled Unloading", {
  delivered_quantity(frm) { recompute_totals(frm); },
  unbilled_unloading_add(frm) { recompute_totals(frm); },
  unbilled_unloading_remove(frm) { recompute_totals(frm); },
});

function recompute_totals(frm) {
  const rows = frm.doc.unbilled_unloading || [];
  const count = rows.length;
  const total = rows.reduce((acc, r) => acc + (parseFloat(r.delivered_quantity) || 0), 0);
  frm.set_value("count_unbilled_unloading", count);
  frm.set_value("total_delivered_quantity", total);
  frm.refresh_field("count_unbilled_unloading");
  frm.refresh_field("total_delivered_quantity");
}
