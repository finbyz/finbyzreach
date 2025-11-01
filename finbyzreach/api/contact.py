from finbyzreach.utils.research import research_person
import frappe

@frappe.whitelist()
def research_contact(name):
    research_person(name)


@frappe.whitelist()
def add_to_ai_email_campaign(name,campaign=None):
    outbound_emails = frappe.get_doc({
        'doctype': 'Outbound Email',
        "ai_email_campaign": campaign or 'Default',
        "contact": name
    })
    outbound_emails.save()