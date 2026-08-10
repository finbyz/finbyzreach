import frappe
from frappe.utils.verified_command import verify_request
import hmac
import hashlib

def is_valid_signature():
	query_string = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
	signature_string = "&_signature="
	if query_string and signature_string in query_string:
		params, given_signature = query_string.split(signature_string)
		from frappe.utils.password import get_encryption_key
		secret = frappe.local.conf.get("secret") or get_encryption_key()
		computed_signature = hmac.new(secret.encode(), params.encode(), digestmod=hashlib.sha512).hexdigest()
		return hmac.compare_digest(given_signature, computed_signature)
	return False

def get_context(context):
	if not is_valid_signature():
		context.error_message = "This link is invalid or has expired."
		return context
		
	campaign_recipient = frappe.form_dict.get("campaign_recipient")
	if not campaign_recipient or not frappe.db.exists("Email Campaign", campaign_recipient):
		context.error_message = "This link is invalid or the campaign does not exist."
		return context
		
	recipient = frappe.get_doc("Email Campaign", campaign_recipient)
	lead = frappe.get_doc("Lead", recipient.recipient)
	
	all_topics = frappe.get_all("Subscription Topic", filters={"disabled": 0}, fields=["name", "description"])
	
	current_unsubscribed_rows = frappe.db.get_all(
		"Unsubscribe Topic Multi Select", 
		filters={"parent": recipient.recipient, "parentfield": "custom_unsubscribe_topics"},
		fields=["subscription_topic"]
	)
	unsubscribed_topics = {row.subscription_topic for row in current_unsubscribed_rows}
	
	current_topic = frappe.db.get_value("Campaign", recipient.campaign_name, "custom_subscription_topic")
	
	topics = []
	for topic in all_topics:
		topics.append({
			"name": topic.name,
			"description": topic.description,
			"unsubscribed": topic.name in unsubscribed_topics,
			"is_current": topic.name == current_topic
		})
		
	context.email = recipient.custom_normalized_email
	context.campaign_recipient = campaign_recipient
	context.topics = topics
	context.no_cache = True
