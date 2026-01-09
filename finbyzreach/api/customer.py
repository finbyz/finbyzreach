from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist()
def research_customer(name, doctype="Customer"):
    doc = frappe.get_doc(doctype, name)
    
    # Check appropriate field based on doctype
    if doctype == "Customer":
        if doc.customer_details:
            return
    else:  # Lead
        if doc.company_details:
            return
    
    research_company(doctype, name)
