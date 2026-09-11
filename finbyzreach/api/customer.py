from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist(methods=["POST"])
def research_customer(doc=None, name=None):
    if doc:
        doc = frappe.parse_json(doc)
        name = doc.get("name")
        if doc.get("company_details"):
            return
    if not name:
        return
    return research_company("Customer", name, enforce_permissions=True)
