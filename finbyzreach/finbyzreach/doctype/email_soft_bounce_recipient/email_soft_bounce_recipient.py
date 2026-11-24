"""Exact mailbox projection of current soft-bounced Communications."""
import frappe
from frappe.model.document import Document


class EmailSoftBounceRecipient(Document):
	pass


def on_doctype_update():
	frappe.db.add_index("Email Soft Bounce Recipient", ["email", "message_created_on"],
		"soft_bounce_email_date")
