from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist()
def research_customer(name):
    research_company("Customer", name)
