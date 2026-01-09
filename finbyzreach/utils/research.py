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
        
    # get agent from Followup Settings
    settings = frappe.get_single("Followup Settings")
    if not settings.company_research_agent:
        frappe.throw("AI Agent not configured. Please set 'company_research_agent' in Followup Settings.")
    company_research_service = AgentService(settings.company_research_agent)

    result = company_research_service.invoke(**lead_info)

    # Save to appropriate field based on doctype
    if party_type == "Customer":
        doc.customer_details = getattr(result, "company_overview", "") or ""
    else:  # Lead
        doc.company_details = getattr(result, "company_overview", "") or ""
    
    if hasattr(doc, "industry") and not doc.industry:
        doc.industry = getattr(result, "industry_type", "") or ""

    if hasattr(doc, "country") and not doc.country:
        doc.country = getattr(result, "country", "") or ""

    if hasattr(doc, "state") and not doc.state:
        doc.state = getattr(result, "state", "") or ""

    if hasattr(doc, "city") and not doc.city:
        doc.city = getattr(result, "city", "") or ""

    if hasattr(doc, "website") and not doc.website:
        website_value = getattr(result, "website", "") or ""
        if website_value:
            doc.website = website_value

    if hasattr(doc, "designation") and not doc.designation:
        doc.designation = getattr(result, "designation", "") or ""

    if hasattr(doc, "no_of_employees") and not doc.no_of_employees:
        doc.no_of_employees = getattr(result, "no_of_employees", "") or ""

    if hasattr(doc, "type") and not doc.type:
        doc.type = getattr(result, "lead_type", "") or ""
    
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
    if not setting.person_research_agent:
        frappe.throw("AI Agent not configured. Please set 'person_research_agent' in Followup Settings.")
    person_research_service = AgentService(setting.person_research_agent)

    # Call research agent
    result = person_research_service.invoke(**lead_info)

    # Update contact with research info
    contact.person_research = result.research_summary
    contact.linkedin_profile = (
        result.linkedin_profile if getattr(result, "linkedin_profile", "").startswith("http") else None
    )
    contact.save(ignore_permissions=True)

    return result
