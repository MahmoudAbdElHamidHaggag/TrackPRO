import frappe
from frappe import _

REQUIRES_FIELD = "custom_requires_vehicle"  

def vehicle_must_exist(doc, method=None):

    rows = getattr(doc, "accounts", None) or [doc]


    meta = frappe.get_meta("Journal Entry Account")
    veh_field = "vehicle"
    if not meta.get_field(veh_field):
        veh_field = next(
            (df.fieldname for df in meta.fields
             if df.fieldtype == "Link" and df.options == "Vehicle"),
            None
        )
    if not veh_field:
        return  

    for r in rows:
        account = getattr(r, "account", None)
        if not account:
            continue


        requires = 0
        if frappe.db.has_column("Account", REQUIRES_FIELD):
            requires = frappe.get_cached_value("Account", account, REQUIRES_FIELD) or 0


        if int(requires) == 1 and not r.get(veh_field):
            frappe.throw(
                _("Row {0}: Vehicle is required for account {1}.").format(
                    getattr(r, "idx", 1), account
                ),
                title=_("Missing Vehicle")
            )
