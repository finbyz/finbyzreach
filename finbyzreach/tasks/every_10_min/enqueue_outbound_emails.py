import frappe
from frappe.core.doctype.communication.test_communication import make
from frappe.utils import now_datetime, add_to_date



def enqueue_outbound_emails():
    """
    Enqueue outbound emails that are scheduled to be sent in the next 10 minutes.
    Fetches unsent emails from 'Communication Email' doctype and processes them.
    """
    # Get the time window (next 10 minutes)
    current_time = now_datetime()
    end_time = add_to_date(current_time, minutes=10)
    
    # Fetch emails scheduled within the next 10 minutes
    emails = frappe.get_list(
        "Communication Email",
        filters={
            "status": ["in",["Queued", "Failed"]],
            "time": ["<=", end_time],
        },
        fields=["*"],
    )

    for email in emails:
        try:
            outbound_email = frappe.get_doc(email.parenttype, email.parent)
            if outbound_email.contact:
                email_id = frappe.get_value("Contact", outbound_email.contact, "email_id")

                if not email_id:
                    frappe.log_error(
                        f"No email found for contact {outbound_email.contact}",
                        "Enqueue Outbound Email"
                    )
                    continue

                sender = frappe.get_value("Email Account", outbound_email.sender, "email_id")
                if email.idx == 1:
                    thread = frappe.get_doc("Communication", outbound_email.communication)
                    comm = frappe.get_doc({
                        "doctype": "Communication",
                        "communication_type": "Communication",
                        "communication_medium": "Email",
                        "sent_or_received": "Sent",
                        "subject": email.subject,
                        "content": email.content,
                        "recipients": email_id,
                        "sender": sender,
                        "reference_doctype": "Outbound Email",
                        "reference_name": email.parent,
                        "email_account": outbound_email.sender
                    })
                    
                else:
                    thread = frappe.get_doc("Communication", outbound_email.communication)
                    comm = frappe.get_doc({
                        "doctype": "Communication",
                        "communication_type": "Communication",
                        "communication_medium": "Email",
                        "sent_or_received": "Sent",
                        "subject": f"Re: {email.subject or thread.subject}",
                        "content": email.content,
                        "recipients": thread.recipients,
                        "sender": thread.sender,
                        "reference_doctype": thread.reference_doctype,
                        "reference_name": thread.reference_name,
                        "in_reply_to": thread.name,
                        "email_account": thread.email_account
                    })
                    
                comm.insert()
                comm.send_email()
                outbound_email.save()
                
                
            frappe.db.set_value(
                "Communication Email",
                email.name,
                "status",
                "Sent"
            )
            frappe.db.commit()
        except Exception as e:
            frappe.log_error(
                message=frappe.get_traceback(),
                title=f"Error enqueueing email {email.name}"
            )
            
            frappe.db.set_value(
                "Communication Email",
                email.name,
                "status",
                "Failed"
            )
            frappe.db.commit()
            continue