import frappe
from frappe import _


def execute(filters=None):
	filters = frappe._dict(filters or {})
	criteria = {}
	for key in ("subscription_topic", "status", "email"):
		if filters.get(key):
			criteria[key] = filters[key]
	topic_categories = {
		row.name: row.category
		for row in frappe.get_all("Subscription Topic", fields=["name", "category"], limit_page_length=0)
	}
	if filters.get("category"):
		matching_topics = [name for name, category in topic_categories.items() if category == filters.category]
		if filters.get("subscription_topic"):
			if filters.subscription_topic not in matching_topics:
				criteria["subscription_topic"] = ["=", ""]
		else:
			criteria["subscription_topic"] = ["in", matching_topics] if matching_topics else ["=", ""]
	rows = frappe.get_all(
		"Email Subscription Preference",
		filters=criteria,
		fields=["email", "subscription_topic", "status", "requested_on", "confirmed_on", "unsubscribed_on"],
		order_by="email asc, subscription_topic asc",
		limit_page_length=0,
	)
	emails = list({row.email for row in rows})
	leads = {}
	contacts = {}
	for start in range(0, len(emails), 500):
		chunk = emails[start:start + 500]
		for row in frappe.get_all("Lead", filters={"email_id": ["in", chunk]}, fields=["name", "email_id"], limit_page_length=0):
			leads.setdefault(row.email_id.lower(), row.name)
		for row in frappe.get_all("Contact Email", filters={"email_id": ["in", chunk]}, fields=["parent", "email_id"], limit_page_length=0):
			contacts.setdefault(row.email_id.lower(), row.parent)
	columns = [
		{"fieldname": "email", "label": _("Email"), "fieldtype": "Data", "width": 230},
		{"fieldname": "subscription_topic", "label": _("Subscription Type or Topic"), "fieldtype": "Link", "options": "Subscription Topic", "width": 220},
		{"fieldname": "category", "label": _("Category"), "fieldtype": "Data", "width": 120},
		{"fieldname": "status", "label": _("Status"), "fieldtype": "Data", "width": 125},
		{"fieldname": "lead", "label": _("Lead"), "fieldtype": "Link", "options": "Lead", "width": 180},
		{"fieldname": "contact", "label": _("Contact"), "fieldtype": "Link", "options": "Contact", "width": 180},
		{"fieldname": "confirmed_on", "label": _("Confirmed On"), "fieldtype": "Datetime", "width": 170},
		{"fieldname": "unsubscribed_on", "label": _("Unsubscribed On"), "fieldtype": "Datetime", "width": 170},
	]
	for row in rows:
		row.category = topic_categories.get(row.subscription_topic, "")
		row.lead = leads.get(row.email)
		row.contact = contacts.get(row.email)
	return columns, rows
