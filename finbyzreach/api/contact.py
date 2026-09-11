from finbyzreach.utils.research import research_person
import frappe

@frappe.whitelist(methods=["POST"])
def research_contact(name):
    result = research_person(name, enforce_permissions=True)
    
    return {
        "status": "success",
        "contact": name,
        "result": result   
    }

@frappe.whitelist(methods=["POST"])
def add_to_ai_email_campaign(name,campaign=None):
    frappe.get_doc("Contact", name).check_permission("read")
    frappe.has_permission("Outbound Email", "create", throw=True)
    outbound_emails = frappe.get_doc({
        'doctype': 'Outbound Email',
        "ai_email_campaign": campaign or 'Default',
        "contact": name
    })
    outbound_emails.insert()
