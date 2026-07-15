from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist(methods=["POST"])
def research_customer(name):
    doc = frappe.get_doc("Customer", name)
    if doc.get("customer_details"):
        return {"status": "skipped", "customer": name, "message": "Customer research already exists"}
    result = research_company("Customer", name)
    return {"status": "success", "customer": name, "result": result}
