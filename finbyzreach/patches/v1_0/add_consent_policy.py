"""Keep existing DOI behavior; add the protected system email type and failure index."""
import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	for doctype in ("subscription_topic", "email_delivery_suppression", "email_subscription_preference", "email_subscription_event"):
		frappe.reload_doc("finbyzreach", "doctype", doctype)
	frappe.reload_doc("finbyzreach", "page", "subscriptions_consent")
	create_custom_fields({"Email Template": [{"fieldname": "custom_email_type", "fieldtype": "Link", "label": "Email type", "options": "Subscription Topic", "insert_after": "custom_folder", "module": "Email Template Builder"}]}, update=True)
	if not frappe.db.exists("Subscription Topic", "Transactional"):
		frappe.get_doc(dict(doctype="Subscription Topic", topic_name="Transactional", category="System", consent_required=0, double_opt_in=0, deliver_while_pending=0, description="Service information. No advertising content; marketing opt-outs do not block delivery.")).insert(ignore_permissions=True)
	frappe.db.add_index("Email Subscription Preference", ["email", "subscription_topic", "status"], "subscription_address_type_status")
	from finbyzreach.consent import capture_delivery_failure
	cursor = ""
	while True:
		rows = frappe.get_all("Communication", filters={"name": [">", cursor], "sent_or_received": "Sent", "delivery_status": ["in", ["Bounced", "Marked As Spam"]]}, fields=["name", "recipients", "sent_or_received", "delivery_status"], order_by="name asc", limit_page_length=500)
		if not rows:
			break
		for row in rows:
			capture_delivery_failure(row)
		cursor = rows[-1].name
	for doctype in ("Workspace Sidebar", "Sidebar"):
		if not frappe.db.exists("DocType", doctype):
			continue
		for name in frappe.get_all(doctype, filters={"name": ["in", ["Megasol Marketing Sidebar", "Megasol Marketing"]]}, pluck="name"):
			sidebar = frappe.get_doc(doctype, name)
			changed = False
			for item in sidebar.get("items") or []:
				if item.get("link_to") == "Subscription Topic":
					item.update({"label": "Subscriptions & consent", "link_to": "subscriptions-consent", "link_type": "Page"})
					changed = True
			if changed:
				sidebar.save(ignore_permissions=True)
	frappe.clear_cache(doctype="Subscription Topic")
	frappe.clear_cache(doctype="Email Template")
