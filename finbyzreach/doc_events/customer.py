from  finbyzreach.utils.research import research_company
import frappe

def research_customer(self):
    if self.company_details:
        return
    research_company("Customer", self.name)
    
def after_insert(self):
    """Hook to research company and person details after lead creation."""
    frappe.enqueue(research_customer, doc=self)
    