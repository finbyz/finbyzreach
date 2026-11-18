"""EM-36: opens and clicks of marketing emails appear on the Lead, Contact or Customer timeline."""
import frappe
from frappe import _

TIMELINE_EVENTS = ("Opened", "Clicked")


def log_email_event(doc, method=None):
	"""After an Email Tracking Event is saved: add one line to the person's timeline."""
	if doc.get("event_type") not in TIMELINE_EVENTS:
		return
	targets = []
	if doc.get("lead"):
		targets.append(("Lead", doc.lead))
	if doc.get("contact"):
		targets.append(("Contact", doc.contact))
	recipient = doc.get("marketing_campaign_recipient")
	if recipient and frappe.db.get_value("Email Campaign", recipient, "email_campaign_for") == "Customer":
		customer = frappe.db.get_value("Email Campaign", recipient, "recipient")
		if customer:
			targets.append(("Customer", customer))
	if not targets:
		return
	campaign = frappe.db.get_value("Campaign", doc.get("marketing_email_campaign"), "campaign_name") or doc.get("marketing_email_campaign") or ""
	subject = frappe.db.get_value("Communication", doc.get("communication"), "subject") if doc.get("communication") else ""
	what = _("Opened the email") if doc.event_type == "Opened" else _("Clicked a link in the email")
	text = what + (f" “{subject}”" if subject else "") + (f" ({campaign})" if campaign else "") + "."
	if doc.event_type == "Clicked" and doc.get("url"):
		text += " " + _("Link: {0}").format(doc.url)
	for doctype, name in targets:
		if not frappe.db.exists(doctype, name):
			continue
		try:
			frappe.get_doc({
				"doctype": "Comment", "comment_type": "Info", "reference_doctype": doctype,
				"reference_name": name, "content": text,
			}).insert(ignore_permissions=True)
		except Exception:
			frappe.log_error(title="Email timeline note failed")
