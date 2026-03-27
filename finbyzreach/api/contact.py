from finbyzreach.utils.research import research_person
import frappe

@frappe.whitelist()
def research_contact(name):
    result = research_person(name)
    frappe.db.commit() 
    
    return {
        "status": "success",
        "contact": name,
        "result": result   
    }

@frappe.whitelist()
def add_to_ai_email_campaign(name,campaign=None):
    outbound_emails = frappe.get_doc({
        'doctype': 'Outbound Email',
        "ai_email_campaign": campaign or 'Default',
        "contact": name
    })
    outbound_emails.save()