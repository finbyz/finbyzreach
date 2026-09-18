from typing import Dict
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, add_days, get_datetime
import json
import re
from frappe.contacts.doctype.contact.contact import get_contacts_linking_to

class OutboundEmail(Document):
    def after_insert(self):
        # enqueue_after_commit keeps the worker from racing the insert: without it the
        # job can start before this transaction is committed and read a doc that is not
        # there yet (or gets rolled back under it).
        frappe.enqueue(
            self.draft_emails,
            queue='long',
            timeout=300,
            enqueue_after_commit=True,
            job_name=f"Draft Emails for Outbound Email {self.name}",
        )
    
    
    def get_message_id(self) -> str:
        if self.communication:
            message_id = frappe.get_value("Communication", self.communication, "message_id")
            return message_id
        
    def draft_emails(self):
        """Generate the campaign's email sequence for this contact.

        Runs as a background job. Any failure is recorded on the document so a
        stuck draft is visible instead of silently sitting in "Drafting" forever
        while the every-10-minute prepare job keeps re-picking it.
        """
        try:
            self._draft_emails()
        except Exception:
            frappe.db.rollback()
            self.mark_drafting_failed(frappe.get_traceback())
            raise

    def mark_drafting_failed(self, traceback):
        frappe.log_error(
            title=f"Outbound Email Drafting Failed - {self.name}",
            message=traceback,
        )
        values = {}
        if frappe.db.has_column("Outbound Email", "custom_ai_outreach_status"):
            values["custom_ai_outreach_status"] = "Failed"
        if frappe.db.has_column("Outbound Email", "custom_stop_reason"):
            values["custom_stop_reason"] = "Failed while generating emails"
        if values:
            frappe.db.set_value("Outbound Email", self.name, values, update_modified=False)
            frappe.db.commit()

    def _draft_emails(self):
        contact = frappe.get_doc('Contact', self.contact)
        customer_details = None
        person_details = contact.person_details
        website = ''
        country = ''
        party_link = None
        for link in contact.links:
            if link.link_doctype not in ('Lead', 'Customer'):
                continue
            party_link = party_link or link
            customer_details = frappe.get_value(link.link_doctype, link.link_name, 'customer_details')
            if customer_details:
                party_link = link
                break
        if party_link and party_link.link_doctype == 'Lead':
            website = frappe.get_value('Lead', party_link.link_name, 'website') or ''
            country = frappe.get_value('Lead', party_link.link_name, 'country') or ''

        if not person_details:
            frappe.throw("Insufficient data in Contact to generate emails. Needs person_details.")

        email_campaign = frappe.get_doc('AI Email Campaign', self.ai_email_campaign)

        email_accounts = email_campaign.email_accounts
        campaign_schedules = email_campaign.campaign_schedules

        if not email_accounts:
            frappe.throw("No email accounts configured in the campaign")
        if not campaign_schedules:
            frappe.throw("No campaign schedules configured in the campaign")

        # A step with a template is rendered, not written. Only the remaining
        # steps are sent to the agent, renumbered so it is never asked for a
        # step it should not produce.
        ai_schedules = [s for s in campaign_schedules if not s.get("email_template")]

        emails_objective = ""
        for i, schedule in enumerate(ai_schedules, start=1):
            emails_objective += get_schedule_objective(schedule, i)

        input_data = {
            "emails_objective": emails_objective,
            "full_name": " ".join(filter(None, [contact.first_name, contact.last_name])),
            "company_name": contact.company_name,
            "website": website,
            "country": country,
            "customer_details": customer_details,
            "person_details": person_details,
            "number_of_emails": len(ai_schedules)
        }

        drafted_emails = []
        if ai_schedules:
            agent = frappe.get_doc("AI Agent", email_campaign.ai_agent)
            agent_service = agent.agent_service
            email_list_output = agent_service.invoke(**input_data)

            drafted_emails = getattr(email_list_output, "emails", None) or []
            if not drafted_emails:
                frappe.throw(f"Agent {email_campaign.ai_agent} returned no emails")

        # The agent call above takes tens of seconds. Anything that touched this
        # document meanwhile (the every-10-minute outreach scheduler, a desk
        # auto-save) would otherwise make the save below fail with
        # TimestampMismatchError and lose the whole generated sequence.
        self.reload()

        existing_count = frappe.db.count('Outbound Email', {
            'ai_email_campaign': self.ai_email_campaign
        })
        sender_index = existing_count % len(email_accounts)
        self.sender = email_accounts[sender_index].email_account

        # Calculate send times based on campaign schedules
        base_time = now_datetime()

        # Build in schedule order and take content from whichever source the step
        # uses. Iterating the schedules rather than the agent's output also stops
        # the rows silently misaligning when the agent returns fewer emails than
        # there are steps.
        template_context = self.get_template_context(contact, party_link, email_campaign)
        ai_queue = list(drafted_emails)

        self.set("communication_email", [])
        for schedule in campaign_schedules:
            if schedule.get("email_template"):
                rendered = frappe.get_doc("Email Template", schedule.email_template).get_formatted_email(
                    template_context
                )
                subject, content = rendered.get("subject"), rendered.get("message")
            elif ai_queue:
                email = ai_queue.pop(0)
                subject, content = email.subject, email.body
            else:
                continue

            self.append("communication_email", {
                "subject": subject,
                "content": content,
                "time": add_days(base_time, schedule.send_after or 0),
                "status": "Queued",
                "custom_branch_condition": schedule.get("custom_branch_condition"),
            })

        # A successful re-draft must clear a previous failure, otherwise the doc
        # stays "Failed" and the prepare step skips it forever.
        if frappe.db.has_column("Outbound Email", "custom_ai_outreach_status"):
            if self.get("custom_ai_outreach_status") == "Failed":
                self.custom_ai_outreach_status = "Drafting"
        if frappe.db.has_column("Outbound Email", "custom_stop_reason"):
            if self.get("custom_stop_reason") == "Failed while generating emails":
                self.custom_stop_reason = None

        # Save once, after the whole sequence is built. Saving inside the loop
        # published half-drafted sequences that the outreach scheduler could pick
        # up and start sending.
        self.save(ignore_permissions=True)


    def get_template_context(self, contact, party_link, email_campaign):
        """Variables an Email Template can use.

        Every key is always present, because a missing key renders as empty in
        Jinja without complaining, which hides mistakes in a template.
        """
        lead = {}
        if party_link and party_link.link_doctype == "Lead":
            lead = frappe.db.get_value(
                "Lead", party_link.link_name,
                ["name", "lead_name", "company_name", "website", "city", "country"],
                as_dict=True,
            ) or {}

        context = {
            "doctype": "Outbound Email",
            "name": self.name,
            "campaign_name": email_campaign.campaign_name,
            "first_name": contact.first_name or "",
            "last_name": contact.last_name or "",
            "full_name": " ".join(filter(None, [contact.first_name, contact.last_name])),
            "email_id": contact.email_id or "",
            "company_name": contact.company_name or lead.get("company_name") or "",
            "salutation_lettertext": "",
            "lead_name": lead.get("name") or "",
            "website": lead.get("website") or "",
            "city": lead.get("city") or "",
            "country": lead.get("country") or "",
            "role": "",
            "project_id": "",
            "project_title": "",
            "street": "",
            "postcode": "",
            "town": "",
            "planstage_name": "",
            "projecttype_name": "",
            "rooftype_name": "",
            "project_value": 0,
        }
        context.update(self.get_infomanager_context(lead.get("name")))
        return context

    def get_infomanager_context(self, lead_name):
        """Project details for the lead, when the lead came from Infomanager.

        Resolved through Infomanager Company.lead, so no extra field on Lead is
        needed. Returns an empty dict when the app or the link is absent.
        """
        if not lead_name or not frappe.db.has_table("Infomanager Company"):
            return {}

        company = frappe.db.get_value("Infomanager Company", {"lead": lead_name},
                                      ["name", "salutation_lettertext"], as_dict=True)
        if not company:
            return {}

        # Lead with the project most worth writing about: a solar signal first,
        # then a granted permit, then the largest build value.
        row = frappe.db.sql("""
            select p.name, p.title, p.street, p.postcode, p.town, p.planstage_name,
                   p.projecttype_name, p.rooftype_name, p.value, pp.roletype_name,
                   exists(select 1 from `tabInfomanager Project Detail` d
                          where d.parent = p.name
                            and d.detailtype_name in ('Solarenergie', 'Flachdach', 'Dachbegrünungen')) as solar
            from `tabInfomanager Project Participant` pp
            join `tabInfomanager Project` p on p.name = pp.parent
            where pp.company = %s
            order by solar desc, (p.planstage_name = 'Baubewilligung erteilt') desc, p.value desc
            limit 1
        """, company.name, as_dict=True)

        context = {"salutation_lettertext": company.salutation_lettertext or ""}
        if row:
            p = row[0]
            context.update({
                "role": p.roletype_name or "",
                "project_id": p.name,
                "project_title": p.title or "",
                "street": p.street or "",
                "postcode": p.postcode or "",
                "town": p.town or "",
                "planstage_name": p.planstage_name or "",
                "projecttype_name": p.projecttype_name or "",
                "rooftype_name": p.rooftype_name or "",
                "project_value": p.value or 0,
            })
        return context


def get_schedule_objective(schedule, index):
    objective = (
        f"Email {index}. {(schedule.get('description') or '').strip()} "
        f"(Send After: {schedule.get('send_after') or 0} days"
    )
    branch_condition = schedule.get("custom_branch_condition")
    if branch_condition:
        objective += f", Branch Condition: {branch_condition}"
    return f"{objective})\n"
