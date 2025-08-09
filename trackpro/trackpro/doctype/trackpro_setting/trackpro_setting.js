frappe.ui.form.on("TrackPRO Setting", {
    refresh(frm) {
        set_filters(frm);
    },
    company(frm) {
        set_filters(frm);
    }
});

function set_filters(frm) {
    const company = frm.doc.company || frappe.defaults.get_user_default("Company");

    frm.set_query("income_account", () => ({
        filters: {
            company: company,
            root_type: "Income",
            is_group: 0
        }
    }));

    frm.set_query("cost_account", () => ({
        filters: {
            company: company,
            root_type: ["in", ["Expense", "Cost of Goods Sold"]],
            is_group: 0
        }
    }));

    frm.set_query("item", () => ({
        filters: {
            is_sales_item: 1,
            is_stock_item: 0,
            disabled: 0
        }
    }));

    frm.set_query("cost_center", () => ({
        filters: {
            company: company,
            is_group: 0
        }
    }));
}
