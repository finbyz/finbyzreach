from finbyzreach.utils.research import research_person
import frappe

@frappe.whitelist(methods=["POST"])
def research_contact(name):
    result = research_person(name)
    
    return {
        "status": "success",
        "contact": name,
        "result": result   
    }

@frappe.whitelist(methods=["POST"])
def add_to_ai_email_campaign(name,campaign=None):
    outbound_emails = frappe.get_doc({
        'doctype': 'Outbound Email',
        "ai_email_campaign": campaign or 'Default',
        "contact": name
    })
    outbound_emails.save()