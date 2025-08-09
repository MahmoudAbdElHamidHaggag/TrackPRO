frappe.ui.form.on("Unloading Receipt", {
  onload(frm) {
    frm.__updating_links = false;        
    frm.__setting_from_delivery_order = false;
    apply_queries(frm);
  },

  refresh(frm) {
    apply_queries(frm);
  },

  customer(frm) {
    if (frm.__updating_links) return;
    frm.set_value("contract_of_carriage", null);
    frm.set_value("download_command", null);
    frm.set_value("delivery_order", null);
    apply_queries(frm);
  },

  contract_of_carriage(frm) {
    if (frm.__updating_links) return;
    frm.set_value("download_command", null);
    frm.set_value("delivery_order", null);
    apply_queries(frm);
  },

  download_command(frm) {

    if (frm.__setting_from_delivery_order || frm.__updating_links) return;
    frm.set_value("delivery_order", null);
    apply_queries(frm);
  },

  async delivery_order(frm) {
    if (!frm.doc.delivery_order) return;


    frm.__updating_links = true;
    try {
      const r = await frappe.db.get_value(
        "Delivery Order",
        frm.doc.delivery_order,
        ["download_command", "contract_of_carriage"]
      );

      const dc = r?.message?.download_command;
      const coc = r?.message?.contract_of_carriage;

     
      if (coc && frm.doc.contract_of_carriage !== coc) {
        await frm.set_value("contract_of_carriage", coc);
      }

      if (dc && frm.doc.download_command !== dc) {
        frm.__setting_from_delivery_order = true;
        await frm.set_value("download_command", dc);
        frm.__setting_from_delivery_order = false;
      }
    } finally {
      frm.__updating_links = false;
      apply_queries(frm); 
    }
  },
});

function apply_queries(frm) {
  if (frm.__updating_links) return; 

  frm.set_query("contract_of_carriage", () => ({
    query: "trackpro.trackpro.api.search_contracts_from_pending_delivery_orders",
    filters: { customer: frm.doc.customer || null },
  }));

  if (frm.doc.contract_of_carriage) {
    frm.set_query("download_command", () => ({
      query: "trackpro.trackpro.api.search_open_download_commands_from_contract_with_pending_do",
      filters: { contract: frm.doc.contract_of_carriage },
    }));
  } else {
  
    frm.set_query("download_command", () => ({ filters: {} }));
  }

  if (frm.doc.contract_of_carriage && frm.doc.download_command) {
    frm.set_query("delivery_order", () => ({
      query: "trackpro.trackpro.api.search_pending_delivery_orders_by_download",
      filters: {
        contract: frm.doc.contract_of_carriage,
        download: frm.doc.download_command,
      },
    }));
  } else {
    frm.set_query("delivery_order", () => ({ filters: {} }));
  }
}
