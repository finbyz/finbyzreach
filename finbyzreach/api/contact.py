from finbyzreach.utils.research import research_person
import frappe

@frappe.whitelist()
def research_contact(name):
    research_person(name)
