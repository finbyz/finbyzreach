import frappe

from finbyzreach.utils.research import research_person


def get_default_ai_email_campaign():
    campaign = frappe.db.get_value(
        "AI Email Campaign",
        {"is_default": 1, "status": ["in", ["Active", "Draft"]]},
        "name",
    )
    if campaign:
        return campaign
    return frappe.db.get_value("AI Email Campaign", {"campaign_name": "Default"}, "name")


def research_contact(self):
    if not self.person_details:
        research_person(self.name)
    campaign = get_default_ai_email_campaign()
    if not campaign:
        frappe.log_error(
            title="Contact Research Campaign Missing",
            message="No default AI Email Campaign exists for automatic contact outreach.",
        )
        return
    outbound_email = frappe.get_doc({
        "doctype":"Outbound Email",
        'contact':self.name,
        'ai_email_campaign': campaign,
    })
    outbound_email.insert(ignore_permissions=True)


def after_insert(self,method):
    """Hook to research company and person details after lead creation."""
    frappe.enqueue(research_contact, self=self, job_name=f"Contact Research - {self.name}")
