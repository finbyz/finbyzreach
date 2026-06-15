from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist(methods=["POST"])
def research_customer(doc):
    if doc.get("company_details"):
        return
    research_company("Customer", doc.get("name"))
