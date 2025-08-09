frappe.ui.form.on("Delivery Order", {
  setup(frm) {
    ensure_visible(frm);
  },
  onload(frm) {
    ensure_visible(frm);
    apply_queries(frm);
  },
  refresh(frm) {
    ensure_visible(frm);
    apply_queries(frm);

    if (!frm.is_new() && frm.doc.docstatus === 1) {
      frm.add_custom_button("Unload Cargo", () => open_start_dialog(frm));
    }
  },

  customer(frm) {
    frm.set_value("contract_of_carriage", null);
    frm.set_value("download_command", null);
    apply_queries(frm);
  },

  contract_of_carriage(frm) {
    frm.set_value("download_command", null);
    apply_queries(frm);
  },
});

function ensure_visible(frm) {
  ["contract_of_carriage", "download_command"].forEach((f) => {
    try {
      frm.set_df_property(f, "hidden", 0);
      frm.toggle_display(f, true);
      frm.refresh_field(f);
    } catch (e) {
      console.warn("ensure_visible:", f, e);
    }
  });
}

function apply_queries(frm) {
  try {
    frm.set_query("contract_of_carriage", () => ({
      query: "trackpro.trackpro.api.search_contracts_with_open_downloads",
      filters: { customer: frm.doc.customer || null },
    }));
  } catch (e) {
    console.warn("contract_of_carriage set_query:", e);
  }

  try {
    if (frm.doc.contract_of_carriage) {
      frm.set_query("download_command", () => ({
        query: "trackpro.trackpro.api.search_open_download_commands",
        filters: { contract: frm.doc.contract_of_carriage },
      }));
    } else {
      // If contract isn't selected yet, keep search empty to avoid errors
      frm.set_query("download_command", () => ({
        filters: { name: ["in", []] },
      }));
    }
  } catch (e) {
    console.warn("download_command set_query:", e);
  }
}

/* -------- dialog to create unloading receipt -------- */

function open_start_dialog(frm) {
  const d = new frappe.ui.Dialog({
    title: "Start Unloading Quantity",
    fields: [{ label: "Quantity", fieldname: "quantity", fieldtype: "Float", reqd: 1 }],
    primary_action_label: "Confirm",
    primary_action(values) {
      if (!values.quantity || values.quantity <= 0) {
        frappe.msgprint("Quantity must be greater than zero.");
        return;
      }
      d.hide();
      create_unloading_eceipt(frm, { quantity: values.quantity });
    },
  });
  d.show();
}

function create_unloading_eceipt(frm, values) {
  frappe.call({
    method: "trackpro.trackpro.api.create_unloading_eceipt",
    args: {
      delivery: frm.doc.name,
      download: frm.doc.download_command,
      contract: frm.doc.contract_of_carriage,
      l_quty: frm.doc.quantity,
      driver: frm.doc.driver,
      vehicle: frm.doc.vehicle,
      quantity: values.quantity,
    },
    callback(r) {
      if (!r.exc) {
        frappe.msgprint("Unloading Receipt created: " + r.message);
        frappe.set_route("Form", "Unloading Receipt", r.message);
      }
    },
  });
}
