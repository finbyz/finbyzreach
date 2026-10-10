import frappe


def get_context(context):
	context.no_cache = True
	context.preference = frappe.form_dict.get("preference")
	context.token = frappe.form_dict.get("token")
	context.valid_link = bool(context.preference and context.token)
	return context
