frappe.ui.form.on("Contract of Carriage", {
  onload(frm) {
    apply_doc_date_guards(frm);
  },

  refresh(frm) {
    apply_doc_date_guards(frm);

    if (
      !frm.is_new() &&
      frm.doc.docstatus === 1 &&
      ["Not Started", "In Progress"].includes(frm.doc.status) &&
      !["Closed", "Completed", "Finished"].includes(frm.doc.status)
    ) {
      frm.add_custom_button(__("Close Contract"), () => {
        frappe.confirm("Are you sure you want to close this contract permanently?", () => {
          frappe.call({
            method: "trackpro.trackpro.api.closed_status",
            args: { contract: frm.doc.name },
            callback(r) {
              if (r.message) {
                frappe.msgprint(__("The contract has been closed."));
                frm.reload_doc();
              }
            },
          });
        });
      });
    }

    if (!frm.is_new() && frm.doc.docstatus === 1 && !["Closed", "Completed"].includes(frm.doc.status)) {
      frm.add_custom_button("Create Download Command", function () {
        open_start_dialog(frm);
      });
    }

    frm.set_query("unloading_area", "loading_and_unloading_areas", (doc, cdt, cdn) => {
      const row = locals[cdt][cdn] || {};
      return row.loading_area ? { filters: { name: ["!=", row.loading_area] } } : {};
    });
  },

  start_date(frm) {
    apply_doc_date_guards(frm);
    if (frm.doc.end_date && frm.doc.start_date && frm.doc.end_date < frm.doc.start_date) {
      frappe.msgprint("End Date cannot be earlier than Start Date.");
      frm.set_value("end_date", null);
    }
  },

  end_date(frm) {
    if (!frm.doc.start_date) {
      frappe.msgprint("Please select the Start Date first.");
      frm.set_value("end_date", null);
      return;
    }
    if (frm.doc.end_date && frm.doc.end_date < frm.doc.start_date) {
      frappe.msgprint("End Date cannot be earlier than Start Date.");
      frm.set_value("end_date", null);
    }
  },
});

frappe.ui.form.on("Area", {
  loading_area(frm, cdt, cdn) {
    validate_area_row(frm, cdt, cdn);
  },
  unloading_area(frm, cdt, cdn) {
    validate_area_row(frm, cdt, cdn);
  },
  form_render(frm, cdt, cdn) {
    const row = locals[cdt][cdn] || {};
    if (row.loading_area) {
      frm.set_query("unloading_area", "loading_and_unloading_areas", () => ({
        filters: { name: ["!=", row.loading_area] },
      }));
    }
  },
});

function apply_doc_date_guards(frm) {
  frm.toggle_enable("end_date", !!frm.doc.start_date);
}

function validate_area_row(frm, cdt, cdn) {
  const row = locals[cdt][cdn];

  if (row.loading_area && row.unloading_area && row.loading_area === row.unloading_area) {
    frappe.msgprint("Unloading Area cannot be the same as the Loading Area.");
    frappe.model.set_value(cdt, cdn, "unloading_area", null);
    return;
  }

  if (row.loading_area && row.unloading_area) {
    const duplicate = (frm.doc.loading_and_unloading_areas || []).some((r) => {
      return r.name !== row.name && r.loading_area === row.loading_area && r.unloading_area === row.unloading_area;
    });
    if (duplicate) {
      frappe.msgprint(`Path (${row.loading_area} → ${row.unloading_area}) is duplicated in the table.`);
      frappe.model.set_value(cdt, cdn, "unloading_area", null);
    }
  }
}

function open_start_dialog(frm) {
  const area_rows = frm.doc.loading_and_unloading_areas || [];
  const area_options = area_rows.map((area) => `${area.loading_area} → ${area.unloading_area}`);

  const d = new frappe.ui.Dialog({
    title: "Start Loading Quantity",
    fields: [
      {
        label: "Quantity",
        fieldname: "quantity",
        fieldtype: "Float",
        default: frm.doc.remaining_quantity_download,
        reqd: 1,
      },
      {
        label: "Loading Area → Unloading Area",
        fieldname: "selected_path",
        fieldtype: "Select",
        options: area_options,
        reqd: 1,
      },
      {
        label: "Download Command Start Date",
        fieldname: "start_date",
        fieldtype: "Date",
        default: frappe.datetime.get_today(),
        reqd: 1,
      },
      {
        label: "Download Command End Date",
        fieldname: "end_date",
        fieldtype: "Date",
        reqd: 1,
      },
    ],
    primary_action_label: "Confirm",
    primary_action(values) {
      if (!values.selected_path) {
        frappe.msgprint("Please choose a path (Loading → Unloading) first.");
        return;
      }
      const parts = values.selected_path.split("→");
      if (!parts || parts.length !== 2) {
        frappe.msgprint("Invalid path.");
        return;
      }

      if (!values.start_date) {
        frappe.msgprint("Please select the Download Command Start Date first.");
        return;
      }
      if (values.end_date && values.end_date < values.start_date) {
        frappe.msgprint("Download Command End Date cannot be earlier than Start Date.");
        return;
      }

      const [loading_area, unloading_area] = parts.map((v) => v.trim());
      d.hide();
      create_download_command(frm, {
        quantity: values.quantity,
        start_date: values.start_date,
        end_date: values.end_date,
        loading_area,
        unloading_area,
      });
    },
  });

  d.get_field("end_date").df.onchange = () => {
    const sv = d.get_value("start_date");
    const ev = d.get_value("end_date");
    if (!sv) {
      frappe.msgprint("Please select the Download Command Start Date first.");
      d.set_value("end_date", null);
      return;
    }
    if (ev && sv && ev < sv) {
      frappe.msgprint("Download Command End Date cannot be earlier than Start Date.");
      d.set_value("end_date", null);
    }
  };

  d.show();
}

function create_download_command(frm, values) {
  frappe.call({
    method: "trackpro.trackpro.api.create_download_command",
    args: {
      contract: frm.doc.name,
      quantity: values.quantity,
      start_date: values.start_date,
      end_date: values.end_date,
      loading_area: values.loading_area,
      unloading_area: values.unloading_area,
    },
    callback(r) {
      if (!r.exc) {
        frappe.msgprint("Download Command created: " + r.message);
        frappe.set_route("Form", "Download Command", r.message);
      }
    },
  });
}
