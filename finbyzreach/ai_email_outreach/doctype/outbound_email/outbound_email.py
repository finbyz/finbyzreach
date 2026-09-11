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

        emails_objective = ""

        for i, schedule in enumerate(campaign_schedules, start=1):
            emails_objective += get_schedule_objective(schedule, i)

        input_data = {
            "emails_objective": emails_objective,
            "full_name": " ".join(filter(None, [contact.first_name, contact.last_name])),
            "company_name": contact.company_name,
            "website": website,
            "country": country,
            "customer_details": customer_details,
            "person_details": person_details,
            "number_of_emails": len(campaign_schedules)
        }

        # Get AI agent and generate emails
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

        self.set("communication_email", [])
        for idx, email in enumerate(drafted_emails):
            schedule = campaign_schedules[idx] if idx < len(campaign_schedules) else None
            send_after_days = (schedule.send_after or 0) if schedule else idx

            self.append("communication_email", {
                "subject": email.subject,
                "content": email.body,
                "time": add_days(base_time, send_after_days),
                "status": "Queued",
                "custom_branch_condition": schedule.get("custom_branch_condition") if schedule else None,
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


def get_schedule_objective(schedule, index):
    objective = (
        f"Email {index}. {(schedule.get('description') or '').strip()} "
        f"(Send After: {schedule.get('send_after') or 0} days"
    )
    branch_condition = schedule.get("custom_branch_condition")
    if branch_condition:
        objective += f", Branch Condition: {branch_condition}"
    return f"{objective})\n"
