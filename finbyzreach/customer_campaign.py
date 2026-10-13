"""Resolve Customer campaign recipients through their linked Contacts."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from finbyzreach.subscription_preferences import is_subscribed, statuses


def contact_for_customer(customer_name, contact_name):
	if not customer_name or not contact_name:
		return False
	return bool(frappe.db.exists("Dynamic Link", {
		"parenttype": "Contact", "parent": contact_name,
		"link_doctype": "Customer", "link_name": customer_name,
	}))


def customer_contacts(customer, mode):
	if mode == "Primary Contact":
		name = customer.customer_primary_contact
		return [name] if contact_for_customer(customer.name, name) else []
	return frappe.get_all(
		"Dynamic Link",
		filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer.name},
		pluck="parent", order_by="parent asc", limit_page_length=0,
	)


def resolve_customer_audience(campaign):
	from finbyzreach import email_marketing

	include = set(campaign.get("studio_include_leads") or [])
	if not include:
		include.update(email_marketing._lead_names_from_filter_groups(
			campaign.get("custom_lead_filters_json"), require_filters=True, audience_doctype="Customer"
		))
	exclude = set(campaign.get("studio_exclude_leads") or [])
	if not exclude and campaign.get("custom_exclude_filters_json"):
		exclude.update(email_marketing._lead_names_from_filter_groups(
			campaign.get("custom_exclude_filters_json"), audience_doctype="Customer"
		))
	exclude_emails = set()
	for group in email_marketing.validate_excluded_email_groups(campaign.get("custom_exclude_email_groups_json")):
		exclude_emails.update(email_marketing._email_group_addresses(group))
	seen = set()
	linked_contacts = set()
	if include:
		linked_contacts.update(frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": ["in", list(include)]},
			pluck="parent", limit_page_length=0,
		))
	contact_emails = (frappe.get_all(
		"Contact", filters={"name": ["in", list(linked_contacts)]},
		pluck="email_id", limit_page_length=0,
	) if linked_contacts else [])
	global_unsubscribed = email_marketing._globally_unsubscribed_emails(contact_emails)
	customer_unsubscribed = email_marketing._reference_unsubscribed_pairs(include, "Customer")
	contact_unsubscribed = email_marketing._reference_unsubscribed_pairs(linked_contacts, "Contact")
	result = []
	for customer_name in sorted(include):
		customer = frappe.db.get_value(
			"Customer", customer_name,
			["name", "customer_name", "customer_primary_contact", "disabled"], as_dict=True,
		)
		contacts = customer_contacts(customer, campaign.get("custom_contact_mode") or "Primary Contact") if customer else []
		if not contacts:
			result.append(frappe._dict(
				lead=customer_name, contact=None, email="", normalized_email="",
				eligible=False, reason="Customer unavailable" if not customer else "No linked Contact",
				topic_unsubscribed=False,
			))
			continue
		for contact_name in dict.fromkeys(contacts):
			contact = frappe.db.get_value("Contact", contact_name, ["name", "full_name", "email_id", "unsubscribed"], as_dict=True)
			email = contact.email_id if contact else ""
			normalized = email_marketing._normalized_email(email)
			preference_statuses = statuses(normalized) if normalized and (
				campaign.get("custom_subscription_topic") or campaign.get("custom_content_topic")
			) else {}
			reason = None
			unconfirmed_topic = None
			if customer_name in exclude:
				reason = "Excluded by Customer filters"
			elif cint(customer.disabled):
				reason = "Customer disabled"
			elif not contact:
				reason = "Contact unavailable"
			elif cint(contact.unsubscribed):
				reason = "Contact unsubscribed"
			elif not normalized:
				reason = "Missing or invalid email"
			elif normalized in exclude_emails:
				reason = "Excluded by Email Group"
			elif normalized in global_unsubscribed:
				reason = "Globally unsubscribed"
			elif (customer_name, normalized) in customer_unsubscribed or (contact_name, normalized) in contact_unsubscribed:
				reason = "Unsubscribed from Customer or Contact emails"
			elif campaign.get("custom_subscription_topic") and preference_statuses.get(campaign.custom_subscription_topic) != "Subscribed":
				unconfirmed_topic = campaign.custom_subscription_topic
				reason = _("No confirmed subscription to {0}").format(campaign.custom_subscription_topic)
			elif campaign.get("custom_content_topic") and preference_statuses.get(campaign.custom_content_topic) != "Subscribed":
				unconfirmed_topic = campaign.custom_content_topic
				reason = _("No confirmed subscription to {0}").format(campaign.custom_content_topic)
			elif normalized in seen:
				reason = "Duplicate email"
			else:
				seen.add(normalized)
			result.append(frappe._dict(
				lead=customer_name, contact=contact_name, email=email,
				normalized_email=normalized, eligible=not reason, reason=reason,
				topic_unsubscribed=bool(unconfirmed_topic and preference_statuses.get(unconfirmed_topic) == "Unsubscribed"),
			))
	return result


def current_customer_exclusion(recipient, campaign):
	from finbyzreach import email_marketing

	customer = frappe.db.get_value("Customer", recipient.recipient, ["disabled"], as_dict=True)
	if not customer:
		return _("Customer unavailable")
	if cint(customer.disabled):
		return _("Customer disabled")
	contact_name = recipient.get("custom_contact")
	if not contact_for_customer(recipient.recipient, contact_name):
		return _("Contact no longer linked to Customer")
	contact = frappe.db.get_value("Contact", contact_name, ["email_id", "unsubscribed"], as_dict=True)
	if not contact or cint(contact.unsubscribed):
		return _("Contact unavailable or unsubscribed")
	if email_marketing._normalized_email(contact.email_id) != recipient.custom_normalized_email:
		return _("Contact email changed")
	if recipient.custom_normalized_email in email_marketing._globally_unsubscribed_emails([recipient.custom_normalized_email]):
		return _("Globally unsubscribed")
	if ((recipient.recipient, recipient.custom_normalized_email) in email_marketing._reference_unsubscribed_pairs([recipient.recipient], "Customer")
		or (contact_name, recipient.custom_normalized_email) in email_marketing._reference_unsubscribed_pairs([contact_name], "Contact")):
		return _("Unsubscribed from Customer or Contact emails")
	if not is_subscribed(recipient.custom_normalized_email, campaign.custom_subscription_topic):
		return _("No confirmed subscription to {0}").format(campaign.custom_subscription_topic)
	if campaign.get("custom_content_topic") and not is_subscribed(recipient.custom_normalized_email, campaign.custom_content_topic):
		return _("No confirmed subscription to {0}").format(campaign.custom_content_topic)
	return None
