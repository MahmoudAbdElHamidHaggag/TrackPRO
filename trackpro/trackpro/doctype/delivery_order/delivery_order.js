frappe.ui.form.on("Delivery Order", {
  setup(frm) { ensure_visible(frm); },
  onload(frm) { ensure_visible(frm); apply_queries(frm); },
  refresh(frm) {
    ensure_visible(frm);
    apply_queries(frm);

    if (!frm.is_new() && frm.doc.docstatus === 1) {
      frm.add_custom_button(__("Unload Cargo"), () => open_start_dialog(frm));
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

/* ---------- helpers (بقيت كما هي) ---------- */
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
  } catch (e) { console.warn("contract_of_carriage set_query:", e); }

  try {
    if (frm.doc.contract_of_carriage) {
      frm.set_query("download_command", () => ({
        query: "trackpro.trackpro.api.search_open_download_commands",
        filters: { contract: frm.doc.contract_of_carriage },
      }));
    } else {
      frm.set_query("download_command", () => ({ filters: { name: ["in", []] } }));
    }
  } catch (e) { console.warn("download_command set_query:", e); }
}

/* ---------- رسائل ثابتة ---------- */
function stickyMsg(title, message, on_close) {
  frappe.msgprint({
    title: __(title || "Notice"),
    message: __(message || ""),
    indicator: "red",
    primary_action: {
      label: __("OK"),
      action() {
        frappe.hide_msgprint();
        if (typeof on_close === "function") on_close();
      },
    },
  });
}

/* ---------- ديلوج إنشاء Unloading Receipt ---------- */
function open_start_dialog(frm) {
  // أولاً هات المتبقي لنعرضه ونمنع الإنشاء لو 0
  frappe.call({
    method: "trackpro.trackpro.api.get_unloading_remaining",
    args: { delivery: frm.doc.name },
    callback(r) {
      if (r && r.exc) {
        stickyMsg("Server Error", r._server_messages || r.exception || __("Unknown error"));
        return;
      }
      const info = r.message || {};
      const remaining = flt(info.remaining || 0);

      if (remaining <= 0) {
        stickyMsg("No Remaining", __("This delivery order is already fully unloaded."));
        return;
      }

      const d = new frappe.ui.Dialog({
        title: __("Start Unloading Quantity"),
        fields: [
          { label: __("Quantity to Unload"), fieldname: "quantity", fieldtype: "Float", reqd: 1,
            description: __("Loaded: {0} | Already Unloaded: {1} | Remaining: {2}")
              .replace("{0}", info.loaded ?? 0).replace("{1}", info.already ?? 0).replace("{2}", remaining)
          },
        ],
        primary_action_label: __("Confirm"),
        primary_action(values) {
          const q = flt(values.quantity || 0);
          if (!q || q <= 0) { stickyMsg("Validation", __("Quantity must be greater than zero.")); return; }
          /*if (q > remaining) { stickyMsg("Validation", __("Quantity cannot exceed remaining ({0}).").replace("{0}", remaining)); return; }*/

          d.hide();
          create_unloading_receipt(frm, { quantity: q });
        },
      });

      // اختياري: نحط القيمة المتبقية كاقتراح أولي
      d.set_value("quantity", remaining);
      d.show();
    },
  });
}

function create_unloading_receipt(frm, values) {
  frappe.call({
    method: "trackpro.trackpro.api.create_unloading_receipt", // المسار الصحيح
    args: {
      delivery: frm.doc.name,
      download: frm.doc.download_command,
      contract: frm.doc.contract_of_carriage,
      l_quty: frm.doc.quantity, // سيُتجاهل في السيرفر لصالح قيمة الـDO
      driver: frm.doc.driver || null,
      vehicle: frm.doc.vehicle || null,
      quantity: values.quantity,
    },
    callback(r) {
      if (r && r.exc) {
        stickyMsg("Server Error", r._server_messages || r.exception || __("Unknown error"));
        return;
      }
      frappe.msgprint(__("Unloading Receipt created: ") + r.message);
      frappe.set_route("Form", "Unloading Receipt", r.message);
    },
  });
}

/* ---------- util ---------- */
function flt(v) { return parseFloat(v || 0); }
