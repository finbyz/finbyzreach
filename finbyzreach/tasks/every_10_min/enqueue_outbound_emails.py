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
                message_id = outbound_email.get_message_id()
                email_id = frappe.get_value("Contact", outbound_email.contact, "email_id")

                if not email_id:
                    frappe.log_error(
                        f"No email found for contact {outbound_email.contact}",
                        "Enqueue Outbound Email"
                    )
                    continue
                comm = make(
                    recipients=[email_id],
                    subject= email.subject,
                    content= email.content,
                    doctype= email.parenttype,
                    name= email.parent,
                    send_email=True,
                    in_reply_to=message_id,
                    references=message_id,
                    reply_to=outbound_email.sender
                )
                if email.idx == 1:
                    outbound_email.update({
                        "communication": comm.get("name")
                    })
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