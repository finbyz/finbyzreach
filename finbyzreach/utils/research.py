import frappe
from frappe import _

from finbyzai.ai.agent.agent_service import AgentService

SUPPORTED_RESEARCH_PARTIES = {"Lead", "Customer"}


def _get_agent_name(fieldname: str):
    """The follow-up job is configured on Lead Followup Setting; Followup Settings is the older place."""
    for doctype in ("Lead Followup Setting", "Followup Settings"):
        if frappe.db.exists("DocType", doctype):
            value = frappe.db.get_single_value(doctype, fieldname)
            if value:
                return value
    return None


def research_company(party_type: str, party_name: str, enforce_permissions: bool = False, **kwargs) -> str:
    """Research about a lead or customer using internal data or fallback to Perplexity."""
    if party_type not in SUPPORTED_RESEARCH_PARTIES:
        frappe.throw(_("Research is supported only for Lead and Customer."))

    doc = frappe.get_doc(party_type, party_name)
    if enforce_permissions:
        doc.check_permission("read")
        doc.check_permission("write")
    
    lead_info = {}
    if party_type == "Lead":
        lead_info = {
            "full_name" : f"{doc.salutation or ''} {doc.first_name or ''} {doc.last_name or ''}".strip(),
            "company" : doc.company_name or "",
            "website" : doc.website or "",
            "country" : doc.country or kwargs.get("country"),
            "city" : doc.city or kwargs.get("city"),
            "state" : doc.state or kwargs.get("state"),
            "territory" : doc.territory or kwargs.get("territory"),
        }
    else:  # Customer
        lead_info = {
            "full_name" : doc.customer_name or "",
            "company" : doc.customer_name or "",
            "website": doc.website or kwargs.get('website'),
            "country" : kwargs.get("country"),
            "city" : kwargs.get("city"),
            "state" : kwargs.get("state"),
            "territory" : doc.territory or kwargs.get("territory"),
        }
        
    # get prompt template from settings
    company_agent = _get_agent_name("company_research_agent")
    if not company_agent:
        frappe.throw("Please set Company Research Agent in Lead Followup Setting.")
    company_research_service = AgentService(company_agent)

    # The Company Research prompt asks the model to pick from these lists.
    lead_type_field = frappe.get_meta("Lead").get_field("type")
    lead_types = [o.strip() for o in (lead_type_field.options or "").split("\n") if o.strip()] if lead_type_field else []
    lead_info["available_lead_types"] = ", ".join(lead_types) or "Client, Channel Partner, Consultant"
    lead_info["available_industry_types"] = ", ".join(frappe.get_all("Industry Type", pluck="name", limit=200))

    result = company_research_service.invoke(**lead_info)
    frappe.logger("finbyzreach").info(f"Company research result: {frappe.as_json(result)}")

    doc.customer_details = result.company_overview
    doc.industry = result.industry_type

    if not doc.get("country"):
        doc.country = result.country

    if not doc.get("state"):
        doc.state = result.state

    if not doc.get("city"):
        doc.city = result.city

    if not doc.get("website"):
        doc.website = result.website

    if hasattr(doc, "designation") and not doc.get("designation"):
        doc.designation = result.designation

    if hasattr(doc, "no_of_employees") and not doc.get("no_of_employees"):
        doc.no_of_employees = result.no_of_employees

    if hasattr(doc, "type") and not doc.get("type"):
        doc.type = result.lead_type
    
    doc.save(ignore_permissions=not enforce_permissions)
    return result


def research_person(contact_name: str, enforce_permissions: bool = False) -> str:
    """Research about a person using internal data or fallback to Perplexity.
    Automatically detects linked Lead or Customer from the Contact.
    """
    contact = frappe.get_doc("Contact", contact_name)
    if enforce_permissions:
        contact.check_permission("read")
        contact.check_permission("write")

    # Find linked Lead or Customer
    party_type, party_doc = None, None
    for link in contact.links or []:
        if link.link_doctype in ["Lead", "Customer"]:
            party_type = link.link_doctype
            party_doc = frappe.get_doc(link.link_doctype, link.link_name)
            if enforce_permissions:
                party_doc.check_permission("read")
            break

    # Collect company / lead info
    lead_info = {}
    if party_doc:
        lead_info = {
            "website": getattr(party_doc, "website", "") or "",
            "country": getattr(party_doc, "country", "") or "",
            "city": getattr(party_doc, "city", "") or "",
            "territory": getattr(party_doc, "territory", "") or "",
        }
    else:
         lead_info = {
            "website": contact.get("email_id", "").split("@")[1] if contact.get("email_id") and "@" in contact.get("email_id") else "",
            "country": "",
            "city": "",
            "territory": "",
        }

    lead_info.update({
        "company": contact.company_name or (party_doc.customer_name if party_type == "Customer" else party_doc.company_name if party_doc else ""),
        "full_name": " ".join(filter(None, [contact.first_name, contact.middle_name, contact.last_name])),
    })
    # Get agent service from Followup Settings
    person_agent = _get_agent_name("person_research_agent")
    if not person_agent:
        frappe.throw("Please set Person Research Agent in Lead Followup Setting.")
    person_research_service = AgentService(person_agent)

    # Call research agent
    result = person_research_service.invoke(**lead_info)

    # Save to contact
    contact.person_research = result.research_summary
    contact.linkedin_profile = result.linkedin_profile
    contact.save(ignore_permissions=not enforce_permissions)
    
    return result
