import frappe

from finbyzreach.preference_center import apply_design
from finbyzreach.subscription_preferences import LANGUAGES, topic_rows


def get_context(context):
	context.no_cache = True
	context.embedded = frappe.form_dict.get("embed") == "1"
	language = frappe.form_dict.get("lang") or "de"
	context.language = language if language in LANGUAGES else "de"
	# Texts, styles, theme and sections come from the published design (draft in editor preview).
	apply_design(context, "subscribe", context.language, preview=bool(frappe.form_dict.get("pc_preview")))
	context.topics = topic_rows(None, context.language)
	return context
