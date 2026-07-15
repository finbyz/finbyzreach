from finbyzreach.utils.research import research_company
import frappe

@frappe.whitelist(methods=["POST"])
def research_lead(name):
    result = research_company("Lead", name)
    return {"status": "success", "lead": name, "result": result}
