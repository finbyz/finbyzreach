from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist()
def research_lead(name):
    research_company("Lead", name)
