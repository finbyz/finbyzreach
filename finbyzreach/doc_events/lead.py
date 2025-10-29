from  finbyzreach.utils.research import research_company
import frappe

def research_lead(self):
    if self.company_details:
        return
    research_company("Lead", self.name)
    
def after_insert(self,method):
    """Hook to research company and person details after lead creation."""
    frappe.enqueue(research_lead, self=self, job_name=f"Lead Research - {self.name}")
    
