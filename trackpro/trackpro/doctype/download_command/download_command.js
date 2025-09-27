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
      !["Closed", "Completed", "Finished"].includes(frm.doc.status)
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

/* ---------------- Delivery Order Dialog + API (with trailer + dedup confirm) ---------------- */

// رسائل ثابتة لا تختفي حتى يضغط المستخدم OK
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

// Server helpers
function get_active_vehicle_for_driver(driver) {
  return frappe.call({
    method: "trackpro.trackpro.api.get_active_vehicle_for_driver",
    args: { driver },
  });
}
function get_active_driver_for_vehicle(vehicle) {
  return frappe.call({
    method: "trackpro.trackpro.api.get_active_driver_for_vehicle",
    args: { vehicle },
  });
}
// NEW: جلب الذيل المرتبط بالرأس (إن وُجد)
function get_active_trailer_for_head(head) {
  return frappe.call({
    method: "trackpro.trackpro.api.get_active_trailer_for_head",
    args: { head },
  });
}

function open_start_dialog(frm) {
  const d = new frappe.ui.Dialog({
    title: __("Create Delivery Order"),
    fields: [
      {
        label: __("Transported By"),
        fieldname: "transported_by",
        fieldtype: "Select",
        options: ["", "Own Fleet", "External Carrier"],
        default: "",
        reqd: 1,
      },

      { fieldtype: "Section Break", label: __("Basic") },
      { label: __("Quantity"), fieldname: "quantity", fieldtype: "Float", reqd: 1 },

      // Own Fleet
      { fieldtype: "Section Break", label: __("Own Fleet"),
        depends_on: "eval: doc.transported_by === 'Own Fleet'" },

      { label: __("Driver"), fieldname: "driver", fieldtype: "Link", options: "Driver",
        depends_on: "eval: doc.transported_by === 'Own Fleet'",
        mandatory_depends_on: "eval: doc.transported_by === 'Own Fleet'"},
      { label: __("Vehicle (Head)"), fieldname: "vehicle", fieldtype: "Link", options: "Vehicle",
        depends_on: "eval: doc.transported_by === 'Own Fleet'",
        mandatory_depends_on: "eval: doc.transported_by === 'Own Fleet'"},
      // يظهر فقط لو الرأس مرتبط بذيل – هنسيطر عليه بالكود (hidden افتراضيًا)
      { label: __("Trailer"), fieldname: "fleet_trailer", fieldtype: "Link", options: "Vehicle",
        read_only: 1, hidden: 1 },

      // External Carrier
      { fieldtype: "Section Break", label: __("External Carrier"),
        depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Supplier"), fieldname: "supplier", fieldtype: "Link", options: "Supplier",
        depends_on: "eval: doc.transported_by === 'External Carrier'",
        mandatory_depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Driver Iqama/ID"), fieldname: "external_driver_iqama", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier'",
        mandatory_depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Driver Name"), fieldname: "external_driver_name", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Driver License No."), fieldname: "external_driver_license", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Vehicle Type"), fieldname: "external_vehicle_type", fieldtype: "Select",
        options: ["Truck", "Tractor + Trailer"],
        depends_on: "eval: doc.transported_by === 'External Carrier'",
        mandatory_depends_on: "eval: doc.transported_by === 'External Carrier'" },
      { label: __("Vehicle Plate No."), fieldname: "external_vehicle_plate", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier' && doc.external_vehicle_type === 'Truck'",
        mandatory_depends_on: "eval: doc.transported_by === 'External Carrier' && doc.external_vehicle_type === 'Truck'" },
      { label: __("Head Plate No."), fieldname: "external_head_plate", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier' && doc.external_vehicle_type === 'Tractor + Trailer'",
        mandatory_depends_on: "eval: doc.transported_by === 'External Carrier' && doc.external_vehicle_type === 'Tractor + Trailer'" },
      { label: __("Trailer Plate No."), fieldname: "external_trailer_plate", fieldtype: "Data",
        depends_on: "eval: doc.transported_by === 'External Carrier' && doc.external_vehicle_type === 'Tractor + Trailer'" },
    ],
    primary_action_label: __("Confirm"),
    primary_action: async (values) => {
      if (!values.quantity || values.quantity <= 0) {
        stickyMsg("Validation", "Quantity must be greater than zero."); return;
      }
      if (!values.transported_by) {
        stickyMsg("Validation", "Please choose 'Transported By'."); return;
      }
      if (values.transported_by === "Own Fleet") {
        if (!values.driver || !values.vehicle) {
          stickyMsg("Validation", "Driver and Vehicle are required for 'Own Fleet'."); return;
        }
      } else if (values.transported_by === "External Carrier") {
        if (!values.supplier) { stickyMsg("Validation", "Supplier is required."); return; }
        if (!values.external_driver_iqama) { stickyMsg("Validation", "Driver Iqama/ID is required."); return; }
        if (!values.external_vehicle_type) { stickyMsg("Validation", "Vehicle Type is required."); return; }
        if (values.external_vehicle_type === "Truck") {
          if (!values.external_vehicle_plate) { stickyMsg("Validation", "Vehicle Plate No. is required for 'Truck'."); return; }
        } else if (values.external_vehicle_type === "Tractor + Trailer") {
          if (!values.external_head_plate) { stickyMsg("Validation", "Head Plate No. is required for 'Tractor + Trailer'."); return; }
        }
      }
      d.hide();
      create_delivery_order(frm, values);
    },
  });

  // ====== Flags & helpers to منع التكرار ======
  let suppress_partner_onchange = false;   // يمنع onchange للطرف التاني عند التعيين البرمجي
  let confirm_open = false;                // يمنع فتح confirm مرتين
  function confirmOnce(html, yes) {
    if (confirm_open) return;
    confirm_open = true;
    frappe.confirm(__(html),
      () => { confirm_open = false; yes && yes(); },
      () => { confirm_open = false; }
    );
  }
  async function updateTrailerField(headVehicle) {
    const fld = d.fields_dict["fleet_trailer"];
    if (!headVehicle) {
      d.set_value("fleet_trailer", "");
      d.toggle_display("fleet_trailer", false);
      return;
    }
    const { message: trailer } = await get_active_trailer_for_head(headVehicle);
    if (trailer) {
      d.set_value("fleet_trailer", trailer);
      d.toggle_display("fleet_trailer", true);
      // read-only enforced already
    } else {
      d.set_value("fleet_trailer", "");
      d.toggle_display("fleet_trailer", false);
    }
  }

  // ====== Own Fleet onchange (مع منع التكرار + عرض الذيل) ======
  d.fields_dict["driver"].df.onchange = async function () {
    const driver = d.get_value("driver");
    if (!driver) return;
    if (suppress_partner_onchange) return;

    const { message: autoVehicle } = await get_active_vehicle_for_driver(driver);
    const currentVehicle = d.get_value("vehicle");

    if (!autoVehicle) {
      stickyMsg("No Active Assignment", "This driver has no active vehicle assignment.", () => {
        d.set_value("driver", ""); 
        updateTrailerField(null);
      });
      return;
    }

    if (!currentVehicle) {
      suppress_partner_onchange = true;
      d.set_value("vehicle", autoVehicle);
      suppress_partner_onchange = false;
      updateTrailerField(autoVehicle);
      return;
    }

    if (currentVehicle !== autoVehicle) {
      confirmOnce(
        `Selected driver is assigned to vehicle <b>${autoVehicle}</b>.<br>
         Replace current vehicle <b>${currentVehicle}</b> with <b>${autoVehicle}</b>?`,
        () => {
          suppress_partner_onchange = true;
          d.set_value("vehicle", autoVehicle);
          suppress_partner_onchange = false;
          updateTrailerField(autoVehicle);
        }
      );
    } else {
      updateTrailerField(autoVehicle);
    }
  };

  d.fields_dict["vehicle"].df.onchange = async function () {
    const vehicle = d.get_value("vehicle");
    if (!vehicle) { updateTrailerField(null); return; }
    if (suppress_partner_onchange) return;

    const { message: autoDriver } = await get_active_driver_for_vehicle(vehicle);
    const currentDriver = d.get_value("driver");

    if (!autoDriver) {
      stickyMsg("No Active Assignment", "This vehicle has no active driver assignment.", () => {
        d.set_value("vehicle", "");
        updateTrailerField(vehicle); // still try trailer on this head
      });
      return;
    }

    if (!currentDriver) {
      suppress_partner_onchange = true;
      d.set_value("driver", autoDriver);
      suppress_partner_onchange = false;
      updateTrailerField(vehicle);
      return;
    }

    if (currentDriver !== autoDriver) {
      confirmOnce(
        `Selected vehicle is assigned to driver <b>${autoDriver}</b>.<br>
         Replace current driver <b>${currentDriver}</b> with <b>${autoDriver}</b>?`,
        () => {
          suppress_partner_onchange = true;
          d.set_value("driver", autoDriver);
          suppress_partner_onchange = false;
          updateTrailerField(vehicle);
        }
      );
    } else {
      updateTrailerField(vehicle);
    }
  };

  d.show();
}

function create_delivery_order(frm, values) {
  frappe.call({
    method: "trackpro.trackpro.api.create_delivery_order",
    args: {
      download: frm.doc.name,
      contract: frm.doc.contract_of_carriage,
      quantity: values.quantity,
      transported_by: values.transported_by,

      // Own Fleet
      driver: values.driver || null,
      vehicle: values.vehicle || null,

      // External Carrier
      supplier: values.supplier || null,
      driver_name: values.external_driver_name || null,
      driver_iqama_number: values.external_driver_iqama || null,
      driver_license_number: values.external_driver_license || null,
      vehicle_configuration: values.external_vehicle_type || null,
      vehicle_plate_number: values.external_vehicle_type === "Truck" ? (values.external_vehicle_plate || null) : null,
      tractor_plate_number: values.external_vehicle_type === "Tractor + Trailer" ? (values.external_head_plate || null) : null,
      trailer_plate_number: values.external_vehicle_type === "Tractor + Trailer" ? (values.external_trailer_plate || null) : null,
    },
    callback(r) {
      if (r && r.exc) {
        stickyMsg("Server Error", r._server_messages || r.exception || __("Unknown error"));
        return;
      }
      frappe.msgprint(__("Delivery Order created: ") + r.message);
      frappe.set_route("Form", "Delivery Order", r.message);
    },
  });
}
