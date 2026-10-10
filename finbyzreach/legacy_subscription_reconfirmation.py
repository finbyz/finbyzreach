"""Preview and request DOI for unverified legacy Lead subscriptions.

Run after migration with ``bench --site SITE execute
finbyzreach.legacy_subscription_reconfirmation.reconfirm_legacy_leads``.
The default is a read-only preview. Pass ``--kwargs '{"dry_run": false}'``
to request confirmation emails for eligible addresses.
"""

import frappe

from finbyzreach.email_marketing import test_recipient_exclusion
from finbyzreach.subscription_preferences import normalize_email, request_subscription, statuses


def reconfirm_legacy_leads(dry_run=True, topic_mapping=None):
	"""Never treat a legacy checkbox as confirmed consent.

	``topic_mapping`` optionally maps old Contact Subscription names to current
	Subscription Topic names. Unmapped names match only when identical.
	"""
	if isinstance(topic_mapping, str):
		topic_mapping = frappe.parse_json(topic_mapping)
	if topic_mapping is None:
		topic_mapping = {}
	if not isinstance(topic_mapping, dict) or not all(
		isinstance(old, str) and isinstance(new, str) for old, new in topic_mapping.items()
	):
		frappe.throw("topic_mapping must be an object of old and new topic names")
	if isinstance(dry_run, str):
		dry_run = dry_run.lower() not in ("0", "false", "no")

	active = set(frappe.get_all("Subscription Topic", filters={"disabled": 0}, pluck="name", limit_page_length=0))
	counts = {
		"legacy_rows": 0,
		"eligible": 0,
		"confirmation_requested": 0,
		"skipped_missing_email": 0,
		"skipped_unmapped_or_disabled": 0,
		"skipped_opted_out": 0,
		"skipped_existing_preference": 0,
	}
	seen = set()
	for row in frappe.get_all(
		"Subscription Multi Select",
		filters={"parenttype": "Lead", "parentfield": "custom_subscriptions"},
		fields=["parent", "subscription"],
		limit_page_length=0,
	):
		counts["legacy_rows"] += 1
		topic = topic_mapping.get(row.subscription, row.subscription)
		if topic not in active:
			counts["skipped_unmapped_or_disabled"] += 1
			continue
		lead = frappe.db.get_value("Lead", row.parent, ["email_id", "unsubscribed", "disabled", "status"], as_dict=True)
		if not lead or not lead.email_id:
			counts["skipped_missing_email"] += 1
			continue
		try:
			email = normalize_email(lead.email_id)
		except frappe.ValidationError:
			counts["skipped_missing_email"] += 1
			continue
		key = (email, topic)
		if key in seen:
			continue
		seen.add(key)
		if statuses(email).get(topic):
			counts["skipped_existing_preference"] += 1
			continue
		if (
			lead.unsubscribed or lead.disabled or lead.status == "Do Not Contact"
			or frappe.db.exists("Unsubscribe Topic Multi Select", {
				"parent": row.parent,
				"parentfield": "custom_unsubscribe_topics",
				"subscription_topic": topic,
			})
			or test_recipient_exclusion(email)
		):
			counts["skipped_opted_out"] += 1
			continue
		counts["eligible"] += 1
		if not dry_run:
			request_subscription(email, topic, "Legacy Lead reconfirmation")
			counts["confirmation_requested"] += 1
	counts["dry_run"] = bool(dry_run)
	return counts
