import frappe

from finbyzreach.preference_center import apply_design
from finbyzreach.subscription_preferences import LANGUAGES


def get_context(context):
	context.no_cache = True
	language = frappe.form_dict.get("lang")
	context.language = language if language in LANGUAGES else "de"
	preview = bool(frappe.form_dict.get("pc_preview"))
	apply_design(context, "confirm", context.language, preview=preview)
	context.preference = frappe.form_dict.get("preference")
	context.token = frappe.form_dict.get("token")
	context.valid_link = preview or bool(context.preference and context.token)
	return context
