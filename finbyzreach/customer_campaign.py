"""Resolve Customer campaign recipients through their linked Contacts."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from finbyzreach.subscription_preferences import is_subscribed


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
	if not include:
		return []
	customers = {}
	for names in email_marketing._chunks(include):
		customers.update({row.name: row for row in frappe.get_all(
			"Customer", filters={"name": ["in", names]},
			fields=["name", "customer_name", "customer_primary_contact", "disabled"], limit_page_length=0,
		)})
	links_by_customer = {}
	for names in email_marketing._chunks(include):
		for row in frappe.get_all(
			"Dynamic Link",
			filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": ["in", names]},
			fields=["parent", "link_name"], limit_page_length=0,
		):
			links_by_customer.setdefault(row.link_name, set()).add(row.parent)
	mode = campaign.get("custom_contact_mode") or "Primary Contact"
	contacts_by_customer = {}
	for customer_name, customer in customers.items():
		linked = links_by_customer.get(customer_name, set())
		if mode == "Primary Contact":
			primary = customer.customer_primary_contact
			contacts_by_customer[customer_name] = [primary] if primary in linked else []
		else:
			contacts_by_customer[customer_name] = sorted(linked)
	linked_contacts = {name for names in contacts_by_customer.values() for name in names}
	contacts_by_name = {}
	for names in email_marketing._chunks(linked_contacts):
		contacts_by_name.update({row.name: row for row in frappe.get_all(
			"Contact", filters={"name": ["in", names]},
			fields=["name", "full_name", "email_id", "unsubscribed"], limit_page_length=0,
		)})
	normalized_by_contact = {
		name: email_marketing._normalized_email(contact.email_id)
		for name, contact in contacts_by_name.items()
	}
	contact_emails = {email for email in normalized_by_contact.values() if email}
	preference_statuses_by_email = {}
	topics = list({topic for topic in (
		campaign.get("custom_subscription_topic"), campaign.get("custom_content_topic")
	) if topic})
	if topics:
		for emails in email_marketing._chunks(contact_emails):
			for row in frappe.get_all(
				"Email Subscription Preference",
				filters={"email": ["in", emails], "subscription_topic": ["in", topics]},
				fields=["email", "subscription_topic", "status"], limit_page_length=0,
			):
				preference_statuses_by_email.setdefault(row.email, {})[row.subscription_topic] = row.status
	seen = set()
	global_unsubscribed = email_marketing._globally_unsubscribed_emails(contact_emails)
	customer_unsubscribed = email_marketing._reference_unsubscribed_pairs(include, "Customer")
	contact_unsubscribed = email_marketing._reference_unsubscribed_pairs(linked_contacts, "Contact")
	result = []
	for customer_name in sorted(include):
		customer = customers.get(customer_name)
		contacts = contacts_by_customer.get(customer_name, [])
		if not contacts:
			result.append(frappe._dict(
				lead=customer_name, contact=None, email="", normalized_email="",
				eligible=False, reason="Customer unavailable" if not customer else "No linked Contact",
				topic_unsubscribed=False,
			))
			continue
		for contact_name in dict.fromkeys(contacts):
			contact = contacts_by_name.get(contact_name)
			email = contact.email_id if contact else ""
			normalized = normalized_by_contact.get(contact_name) or ""
			preference_statuses = preference_statuses_by_email.get(normalized, {})
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
