from typing import Dict
import frappe
from frappe.model.document import Document
from frappe.utils import now_datetime, add_days, get_datetime
import json
import re
from frappe.contacts.doctype.contact.contact import get_contacts_linking_to

class OutboundEmail(Document):
    def after_insert(self):
        frappe.enqueue(self.draft_emails, queue='long', timeout=300,job_name=f"Draft Emails for Outbound Email {self.name}")
        # self.draft_emails()
    
    
    def get_message_id(self) -> str:
        if self.communication:
            message_id = frappe.get_value("Communication", self.communication, "message_id")
            return message_id
        
    def draft_emails(self):
        contact = frappe.get_doc('Contact', self.contact)
        customer_details = None
        person_details = contact.person_details
        website = ''
        country = ''
        link = None
        for link in contact.links:
            customer_details = frappe.get_value(link.link_doctype, link.link_name, 'customer_details')
            if customer_details:
                link = link
                break
        if link and link.link_doctype == 'Lead':
            website = frappe.get_value('Lead', link.link_name, 'website') or ''
            country = frappe.get_value('Lead', link.link_name, 'country') or ''
            
        
        if not person_details:
            frappe.throw("Insufficient data in Contact to generate emails. Needs person_details.")
            return
        
        email_campaign = frappe.get_doc('AI Email Campaign', self.ai_email_campaign)
        
        email_accounts = email_campaign.email_accounts
        campaign_schedules = email_campaign.campaign_schedules
        
        emails_objective = ""
        
        for i, schedule in enumerate(campaign_schedules, start=1):
            emails_objective += (
                f"Email {i}. {schedule.description.strip()} "
                f"(Send After: {schedule.send_after} days)\n"
            )
        
        input_data = {
            "emails_objective": emails_objective,
            "full_name": f"{contact.first_name} {contact.last_name}",
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
        if email_accounts:
            existing_count = frappe.db.count('Outbound Email', {
                'ai_email_campaign': self.ai_email_campaign
            })
            sender_index = existing_count % len(email_accounts)
            sender = email_accounts[sender_index].email_account
        else:
            frappe.throw("No email accounts configured in the campaign")
        self.sender = sender
        # Calculate send times based on campaign schedules
        base_time = now_datetime()
        
        for idx, email in enumerate(email_list_output.emails):
            if idx < len(campaign_schedules):
                schedule = campaign_schedules[idx]
                send_after_days = schedule.send_after or 0
            else:
                send_after_days = idx 
            
            # Calculate scheduled time
            scheduled_time = add_days(base_time, send_after_days)
            
            self.append("communication_email",{
                "subject": email.subject,
                "content": email.body,
                "time": scheduled_time,
                "status": "Queued",
            })
            self.save()
        self.reload()