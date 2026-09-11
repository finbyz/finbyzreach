from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist(methods=["POST"])
def research_lead(name):
    return research_company("Lead", name, enforce_permissions=True)
