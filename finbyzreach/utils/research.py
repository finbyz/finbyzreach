from finbyzai.ai.agent.agent_service import AgentService
import frappe

def research_company(party_type: str,party_name: str,**kwargs) -> str:
    """Research about a lead or customer using internal data or fallback to Perplexity."""
    doc = frappe.get_doc(party_type, {"name": party_name})
    
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
    setting = frappe.get_single("Followup Settings")
    company_research_service = AgentService(setting.company_research_agent)

    result = company_research_service.invoke(**lead_info)

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
    
    doc.save()
    return result


def research_person(contact_name: str) -> str:
    """Research about a person using internal data or fallback to Perplexity.
    Automatically detects linked Lead or Customer from the Contact.
    """
    contact = frappe.get_doc("Contact", contact_name)

    # Find linked Lead or Customer
    party_type, party_doc = None, None
    for link in contact.links or []:
        if link.link_doctype in ["Lead", "Customer"]:
            party_type = link.link_doctype
            party_doc = frappe.get_doc(link.link_doctype, link.link_name)
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
    setting = frappe.get_single("Followup Settings")
    person_research_service = AgentService(setting.person_research_agent)

    # Call research agent
    result = person_research_service.invoke(**lead_info)

    # Update contact with research info
    contact.person_details = result.research_summary
    contact.linkedin_profile = (
        result.linkedin_profile if getattr(result, "linkedin_profile", "").startswith("http") else None
    )
    contact.save(ignore_permissions=True)

    return result
