from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist()
def research_lead(doc):
    if doc.get("company_details"):
        return
    research_company("Lead", doc.get("name"))
