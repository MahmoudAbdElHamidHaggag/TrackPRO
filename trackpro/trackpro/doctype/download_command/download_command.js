frappe.ui.form.on("Download command", {
  refresh(frm) {
    set_contract_query(frm);
    build_area_index(frm).then(() => {
      apply_loading_query(frm);
      apply_unloading_query(frm);
    });
    toggle_field_enablement(frm);

    if (
      !frm.is_new() &&
      frm.doc.docstatus === 1 &&
      ["Not Started", "In Progress"].includes(frm.doc.status) &&
      !["Closed", "Completed", "Finished"].includes(frm.doc.status)
    ) {
      frm.add_custom_button(__("Close Download Command"), () => {
        frappe.confirm("Are you sure you want to permanently close the download command?", () => {
          frappe.call({
            method: "trackpro.trackpro.api.closed_status",
            args: { download: frm.doc.name },
            callback(r) {
              if (r.message) {
                frappe.msgprint(__("Download command has been permanently closed"));
                frm.reload_doc();
              }
            },
          });
        });
      });
    }

    if (
      !frm.is_new() &&
      frm.doc.docstatus === 1 &&
      !["Closed", "Completed"].includes(frm.doc.status)
    ) {
      frm.add_custom_button("Create Delivery Order", function () {
        open_start_dialog(frm);
      });
    }
  },

  customer(frm) {
    set_contract_query(frm);
    frm.set_value("contract_of_carriage", null);
    clear_dependent_fields(frm);
    reset_area_index();
    toggle_field_enablement(frm);
  },

  contract_of_carriage(frm) {
    reset_area_index();
    build_area_index(frm).then(() => {
      apply_loading_query(frm);
      apply_unloading_query(frm);
      enforce_date_bounds(frm);
      toggle_field_enablement(frm);
    });
  },

  loading_area(frm) {
    frm.set_value("unloading_area", null);
    apply_unloading_query(frm);
    toggle_field_enablement(frm);
  },

  start_date(frm) { enforce_date_bounds(frm); },
  end_date(frm)   { enforce_date_bounds(frm); },
});

/* ---------------- helpers ---------------- */

function set_contract_query(frm) {
  frm.set_query("contract_of_carriage", () => {
    const filters = {
      docstatus: 1,
      status: ["in", ["Not Started", "In Progress"]],
    };
    if (frm.doc.customer) filters.customer = frm.doc.customer;
    return { filters };
  });
}

function toggle_field_enablement(frm) {
  const has_customer = !!frm.doc.customer;
  const has_contract = !!frm.doc.contract_of_carriage;
  const has_loading = !!frm.doc.loading_area;

  frm.toggle_enable("contract_of_carriage", has_customer);
  ["start_date", "end_date", "loading_area"].forEach((f) =>
    frm.toggle_enable(f, has_contract)
  );

  show_unloading(frm, has_contract && has_loading);
  frm.toggle_enable("unloading_area", has_contract && has_loading);
}

function clear_dependent_fields(frm) {
  frm.set_value("start_date", null);
  frm.set_value("end_date", null);
  frm.set_value("loading_area", null);
  frm.set_value("unloading_area", null);
}

function enforce_date_bounds(frm) {
  if (!frm.doc.contract_of_carriage) return;

  frappe.db
    .get_value("Contract of Carriage", frm.doc.contract_of_carriage, ["start_date", "end_date"])
    .then((r) => {
      const cs = r?.message?.start_date;
      const ce = r?.message?.end_date;
      const sd = frm.doc.start_date;
      const ed = frm.doc.end_date;

      if (sd && cs && sd < cs) frm.set_value("start_date", cs);
      if (ed && cs && ed < cs) frm.set_value("end_date", cs);

      if (ce) {
        if (sd && sd > ce) frm.set_value("start_date", ce);
        if (ed && ed > ce) frm.set_value("end_date", ce);
      }

      const nsd = frm.doc.start_date;
      const ned = frm.doc.end_date;
      if (nsd && ned && nsd > ned) frm.set_value("end_date", nsd);
    });
}

let AREA_INDEX = null; 

function reset_area_index() {
  AREA_INDEX = null;
}

function build_area_index(frm) {
  if (!frm.doc.contract_of_carriage) {
    AREA_INDEX = null;
    return Promise.resolve();
  }

  return frappe.db.get_doc("Contract of Carriage", frm.doc.contract_of_carriage).then((coc) => {
    const rows = coc.loading_and_unloading_areas || [];
    const map = {};
    const loadingSet = new Set();

    rows.forEach((r) => {
      if (!r.loading_area || !r.unloading_area) return;
      loadingSet.add(r.loading_area);
      if (!map[r.loading_area]) map[r.loading_area] = new Set();
      map[r.loading_area].add(r.unloading_area);
    });

    AREA_INDEX = {
      loadingList: Array.from(loadingSet),
      map, 
    };
  });
}

function apply_loading_query(frm) {
  if (!AREA_INDEX) return;
  frm.set_query("loading_area", () => ({
    filters: { name: ["in", AREA_INDEX.loadingList] },
  }));
}

function show_unloading(frm, show) {
  frm.set_df_property("unloading_area", "hidden", show ? 0 : 1);
  frm.toggle_enable("unloading_area", show);
  frm.refresh_field("unloading_area");
}

function apply_unloading_query(frm) {
  if (!AREA_INDEX) { show_unloading(frm, false); return; }

  const la = frm.doc.loading_area;
  if (!frm.doc.contract_of_carriage || !la) { show_unloading(frm, false); return; }

  const allowedUnloading = AREA_INDEX.map[la] ? Array.from(AREA_INDEX.map[la]) : [];

  frm.set_query("unloading_area", () => ({
    filters: { name: ["in", allowedUnloading] },
  }));

  if (allowedUnloading.length === 0) {
    frm.set_value("unloading_area", null);
    show_unloading(frm, false);
    return;
  }

  show_unloading(frm, true);

  if (frm.doc.unloading_area && !allowedUnloading.includes(frm.doc.unloading_area)) {
    frm.set_value("unloading_area", null);
  }
}

function open_start_dialog(frm) {
  const d = new frappe.ui.Dialog({
    title: "Start Loading Quantity",
    fields: [
      { label: "Quantity", fieldname: "quantity", fieldtype: "Float", reqd: 1 },
      { label: "Driver", fieldname: "driver", fieldtype: "Link", options: "Driver", reqd: 1 },
      { label: "Vehicle", fieldname: "vehicle", fieldtype: "Link", options: "Vehicle", reqd: 1 },
    ],
    primary_action_label: "Confirm",
    primary_action(values) {
      if (!values.quantity || values.quantity <= 0) {
        frappe.msgprint("Quantity must be greater than zero.");
        return;
      }
      d.hide();
      create_delivery_order(frm, values);
    },
  });

  d.show();
}

function create_delivery_order(frm, values) {
  frappe.call({
    method: "trackpro.trackpro.api.create_delivery_order",
    args: {
      download: frm.doc.name,
      contract: frm.doc.contract_of_carriage,
      driver: values.driver,
      vehicle: values.vehicle,
      quantity: values.quantity,
    },
    callback(r) {
      if (!r.exc) {
        frappe.msgprint("Delivery Order created: " + r.message);
        frappe.set_route("Form", "Delivery Order", r.message);
      }
    },
  });
}
