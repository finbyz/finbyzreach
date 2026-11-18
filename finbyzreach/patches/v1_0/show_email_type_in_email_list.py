"""Show the email type as a column and filter on the Emails list (EM-40)."""
import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	if not frappe.db.exists("Custom Field", "Email Template-custom_email_type"):
		return
	for prop in ("in_list_view", "in_standard_filter"):
		make_property_setter("Email Template", "custom_email_type", prop, "1", "Check", validate_fields_for_doctype=False)
	frappe.clear_cache(doctype="Email Template")
