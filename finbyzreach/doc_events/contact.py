from  finbyzreach.utils.research import research_person
import frappe


def research_contact(self):
    if not self.person_details:
        research_person(self.name)
    outbound_email = frappe.get_doc({
        "doctype":"Outbound Email",
        'contact':self.name,
        'ai_email_campaign': 'Default',
    })
    outbound_email.insert()


def after_insert(self,method):
    """Hook to research company and person details after lead creation."""
    frappe.enqueue(research_contact, self=self, job_name=f"Contact Research - {self.name}")
    