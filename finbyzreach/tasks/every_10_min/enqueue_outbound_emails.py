import frappe
from frappe.core.doctype.communication.email import get_message_id
from frappe.utils import now_datetime, add_to_date


def enqueue_email(sender,email):
    sender_email_id = frappe.get_value("Email Account", sender, "email_id")
    if email.idx == 1:
        message_id = get_message_id()[1:-1]
        comm = frappe.get_doc({
            "doctype": "Communication",
            "communication_type": "Communication",
            "communication_medium": "Email",
            "sent_or_received": "Sent",
            "subject": email.subject,
            "content": email.content,
            "recipients": email.email_id,
            "sender": sender_email_id,
            "reference_doctype": "Outbound Email",
            "reference_name": email.parent,
            "email_account": sender,
            "message_id": message_id
        })
    else:
        thread = frappe.get_doc("Communication", email.get("thread_id"))
        is_replied = frappe.get_all(
            "Communication",
            filters={
                "message_id": thread.message_id,
                "sender": ["like", f"%{email.email_id}%"]
            },
            pluck="name"
        )

        is_replied = bool(is_replied)
        if is_replied:
            email.is_replied = is_replied
            return
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
            "email_account": thread.email_account,
            "message_id": thread.message_id
        })
        
    comm.insert()
    comm.send_email()
    return comm


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
                email.update({"email_id" : email_id})
                if not email_id:
                    frappe.log_error(
                        f"No email found for contact {outbound_email.contact}",
                        "Enqueue Outbound Email"
                    )
                    continue
                email.update({"thread_id": outbound_email.communication})
                comm = enqueue_email(sender=outbound_email.sender,email=email)
                
                if comm and email.idx == 1:
                    outbound_email.update({
                            "communication" : comm.name
                    })
                if not comm:
                    outbound_email.replied = True
                    outbound_email.save()
                
            frappe.db.set_value(
                "Communication Email",
                email.name,
                "status",
                "Sent"
            )
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
            continue