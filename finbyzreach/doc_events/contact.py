from  finbyzreach.utils.research import research_person
import frappe


def research_contact(self):
    if self.person_details:
        return
    research_person("Customer", self.name, self.name)

def after_insert(self):
    """Hook to research company and person details after lead creation."""
    frappe.enqueue(research_contact, doc=self)
    