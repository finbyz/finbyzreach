import frappe

from finbyzreach.subscription_preferences import LANGUAGES, topic_rows
from finbyzreach.www.manage_subscriptions import get_copy


def get_context(context):
	context.no_cache = True
	context.embedded = frappe.form_dict.get("embed") == "1"
	language = frappe.form_dict.get("lang") or "en"
	context.language = language if language in LANGUAGES else "en"
	context.copy = get_copy(context.language)
	context.topics = topic_rows(None, context.language)
	return context
