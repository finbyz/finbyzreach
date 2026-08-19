from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import formataddr
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from frappe.rate_limiter import rate_limit
import frappe
from bs4 import BeautifulSoup
from frappe import _
from frappe.core.doctype.communication.email import make
from frappe.utils import (
	add_to_date,
	cint,
	getdate,
	get_datetime,
	get_system_timezone,
	get_time,
	get_url,
	now_datetime,
	nowdate,
	parse_addr,
	slug,
	validate_email_address,
)
from frappe.utils.verified_command import get_signed_params, verify_request

from finbyzreach.email_template_builder.services import (
	get_campaign_snapshot,
	render_campaign_snapshot,
)


CLICK_METHOD = "finbyzreach.email_marketing.track_marketing_click"
UNSUBSCRIBE_METHOD = "finbyzreach.email_marketing.unsubscribe_marketing"
FILTER_OPERATORS = {
	"=",
	"!=",
	">",
	"<",
	">=",
	"<=",
	"like",
	"not like",
	"in",
	"not in",
	"between",
	"Between",
	"is",
	"Timespan",
	"previous",
	"next",
	"descendants of",
	"descendants of (inclusive)",
	"not descendants of",
	"ancestors of",
	"not ancestors of",
}
WEEKDAY_FIELDS = (
	"send_monday",
	"send_tuesday",
	"send_wednesday",
	"send_thursday",
	"send_friday",
	"send_saturday",
	"send_sunday",
)
TERMINAL_DELIVERY_STATUSES = ("Sent", "Failed", "Skipped", "Cancelled")
REPEAT_UNITS = ("Minutes", "Hours", "Days")
MAX_AUDIENCE_FILTERS = 50
MAX_AUDIENCE_FILTER_GROUPS = 25
MAX_EXCLUDED_EMAIL_GROUPS = 50
SCHEDULER_RECIPIENT_INSERT_FLAG = "email_campaign_scheduler_recipient_insert"
# Mirror Frappe's Email Queue safety model at the campaign-release boundary:
# allow a short undo window, recover abandoned work after the core retry window,
# and stop only when failures are both numerous and systemic.
DISPATCH_UNDO_WINDOW_SECONDS = 10
STALE_PROCESSING_AFTER_MINUTES = 15
DISPATCH_BATCH_FAILURE_THRESHOLD_PERCENT = 0.33
DISPATCH_BATCH_FAILURE_THRESHOLD_COUNT = 10
CAMPAIGN_COPY_COUNT_FIELDS = (
	"custom_candidate_count",
	"custom_eligible_count",
	"custom_excluded_count",
	"custom_queued_count",
	"custom_sent_count",
	"custom_failed_count",
	"custom_opened_count",
	"custom_clicked_count",
	"custom_replied_count",
	"custom_unsubscribed_count",
	"custom_batch_count",
)
CAMPAIGN_COPY_FROZEN_FIELDS = (																																																										
	"custom_first_scheduled_at",
	"custom_last_scheduled_at",
	"custom_template_mode",
	"custom_template_reference_doctype",
	"custom_snapshot_subject",
	"custom_snapshot_preheader",
	"custom_snapshot_html",
	"custom_snapshot_hash",
)



def _ensure_raw_html_delivery_markers(html):
	"""Add Frappe's per-recipient delivery markers to complete visual HTML."""
	html = str(html or "")
	parts = []
	if "<!--unsubscribe link here-->" not in html:
		parts.append("<!--unsubscribe link here-->")
	if "<!--email_open_check-->" not in html:
		parts.append('<div class="email-pixel"><!--email_open_check--></div>')
	if not parts:
		return html
	footer = '<div class="email-footer-container text-muted">' + "".join(parts) + "</div>"
	if re.search(r"</body\s*>", html, flags=re.IGNORECASE):
		return re.sub(r"</body\s*>", footer + "</body>", html, count=1, flags=re.IGNORECASE)
	return html + footer


class CampaignEmailBroadcastMixin:
	def validate(self):
		if _is_email_broadcast(self):
			validate_campaign(self)
		parent_validate = getattr(super(), "validate", None)
		if parent_validate:
			return parent_validate()


class EmailCampaignBroadcastMixin:
	def before_insert(self):
		# Keep ERPNext's standard Email Campaign workflow untouched.  Only rows
		# belonging to a Studio broadcast must be created by our frozen-audience
		# scheduler.
		if not self.campaign_name or not _is_email_broadcast(self.campaign_name):
			parent_before_insert = getattr(super(), "before_insert", None)
			if parent_before_insert:
				return parent_before_insert()
			return None
		if not frappe.flags.get(SCHEDULER_RECIPIENT_INSERT_FLAG):
			frappe.throw(
				_(
					"Direct Email Campaign creation is disabled. "
					"Create and schedule campaigns from Email Campaign Studio."
				),
				frappe.PermissionError,
			)

	def validate(self):
		if not self.campaign_name or not _is_email_broadcast(self.campaign_name):
			return super().validate()
		if not self.is_new():
			frappe.throw(
				_(
					"Email Campaign recipient records are read-only delivery logs. "
					"Manage the campaign from Email Campaign Studio."
				),
				frappe.PermissionError,
			)
		self.email_campaign_for = "Lead"
		if not self.campaign_name or not self.recipient:
			frappe.throw(_("Campaign and Lead are required for a broadcast recipient"))
		delivery_status = self.custom_delivery_status or "Planned"
		scheduled_at = self.custom_scheduled_at or now_datetime()
		self.start_date = getdate(scheduled_at)
		self.end_date = self.start_date
		self.status = (
			"Completed"
			if delivery_status in TERMINAL_DELIVERY_STATUSES
			else "Scheduled"
		)
		if delivery_status not in ("Skipped", "Cancelled"):
			email = self.custom_recipient_email or frappe.db.get_value("Lead", self.recipient, "email_id")
			if not _normalized_email(email):
				frappe.throw(_("Lead {0} has no valid email address").format(self.recipient))

	def update_status(self):
		if not self.campaign_name or not _is_email_broadcast(self.campaign_name):
			return super().update_status()
		delivery_status = self.custom_delivery_status or "Planned"
		expected = (
			"Completed"
			if delivery_status in TERMINAL_DELIVERY_STATUSES
			else "Scheduled"
		)
		if self.status != expected:
			self.db_set("status", expected, update_modified=False)


def _is_email_broadcast(campaign):
	fields = (
		"custom_email_template",
		"custom_lead_filters_json",
		"custom_subscription_topic",
	)
	if isinstance(campaign, str):
		values = frappe.db.get_value("Campaign", campaign, fields, as_dict=True)
		return bool(values and any(values.get(field) for field in fields))
	if any(campaign.get(field) for field in fields):
		return True
	# A scheduled broadcast must not be convertible back into a normal Campaign
	# by clearing its three marker fields in a crafted save request.  Consult the
	# persisted document whenever an existing in-memory document has no markers.
	name = campaign.get("name")
	if not name:
		return False
	is_new = getattr(campaign, "is_new", None)
	if callable(is_new) and is_new():
		return False
	return _is_email_broadcast(name)


def _system_zone():
	timezone_name = get_system_timezone() or "UTC"
	try:
		return ZoneInfo(timezone_name)
	except ZoneInfoNotFoundError:
		frappe.throw(_("The system timezone {0} is invalid").format(frappe.bold(timezone_name)))


def apply_campaign_defaults(doc):
	if not doc.custom_start_on:
		doc.custom_start_on = now_datetime() + timedelta(minutes=5)
	if doc.get("custom_batch_size") in (None, ""):
		doc.custom_batch_size = 100
	if doc.get("custom_repeat_every") in (None, ""):
		doc.custom_repeat_every = 1
	if doc.get("custom_repeat_unit") in (None, ""):
		doc.custom_repeat_unit = "Hours"
	doc.custom_utm_source = doc.custom_utm_source or "newsletter"
	doc.custom_utm_medium = doc.custom_utm_medium or "email"
	doc.custom_utm_campaign = slug(doc.campaign_name)


def _reset_duplicated_broadcast_state(doc):
	"""Turn copied scheduled/completed broadcast state into a safe Draft copy.

	Frappe's duplicate action copies custom fields too. A copied Campaign can
	therefore inherit a terminal broadcast status, frozen HTML snapshot and
	metrics. Saving that as-is is either blocked or, worse, misleading. We reset
	only when there is evidence of copied frozen state; a malicious/new document
	that simply sets ``Scheduled`` is still rejected by normal validation.
	"""
	if not doc.is_new() or (doc.custom_broadcast_status or "Draft") == "Draft":
		return

	has_copied_state = any(cint(doc.get(field)) for field in CAMPAIGN_COPY_COUNT_FIELDS) or any(
		doc.get(field) for field in CAMPAIGN_COPY_FROZEN_FIELDS
	)
	if not has_copied_state:
		return

	doc.custom_broadcast_status = "Draft"
	doc.custom_start_on = now_datetime() + timedelta(minutes=5)
	for field in CAMPAIGN_COPY_COUNT_FIELDS:
		setattr(doc, field, 0)
	for field in CAMPAIGN_COPY_FROZEN_FIELDS:
		setattr(doc, field, None)



def validate_campaign(doc, require_ready=False, skip_queued_check=False):
	apply_campaign_defaults(doc)
	_reset_duplicated_broadcast_state(doc)
	_system_zone()
	requested_status = doc.custom_broadcast_status or "Draft"
	if doc.is_new() and requested_status != "Draft":
		frappe.throw(_("New email broadcasts must start as Draft"))
	if require_ready and not doc.custom_subscription_topic:
		frappe.throw(_("Subscription Topic is required for an Email Broadcast"))
	if doc.custom_subscription_topic and frappe.db.get_value(
		"Subscription Topic", doc.custom_subscription_topic, "disabled"
	):
		frappe.throw(_("Subscription Topic {0} is disabled").format(doc.custom_subscription_topic))
	if require_ready and not doc.custom_email_template:
		frappe.throw(_("Email Template is required for an Email Broadcast"))
	if require_ready and not doc.custom_email_account:
		frappe.throw(_("Outgoing Email Account is required for an Email Broadcast"))
	if not doc.is_new():
		persisted_queued = frappe.db.get_value("Campaign", doc.name, "custom_queued")
		if persisted_queued and not skip_queued_check:
			frappe.throw(_("Cannot edit campaign while it is being queued for scheduling."))
		persisted_status = frappe.db.get_value("Campaign", doc.name, "custom_broadcast_status")
		if persisted_status and persisted_status != "Draft":
			frappe.throw(
				_("A scheduled campaign is immutable. Pause, resume, or cancel it using the campaign actions.")
			)
		if requested_status != (persisted_status or "Draft"):
			frappe.throw(_("Broadcast status can be changed only through campaign actions"))
	# Batch size and cadence remain scheduling inputs, but the application no
	# longer enforces a maximum batch, per-minute rate, pending-queue ceiling,
	# scheduler-resolution minimum, or daily campaign cap.
	if cint(doc.custom_batch_size) <= 0:
		frappe.throw(_("Emails per Batch must be greater than zero"))
	if cint(doc.custom_repeat_every) <= 0:
		frappe.throw(_("Repeat Every must be greater than zero"))
	if doc.custom_repeat_unit not in REPEAT_UNITS:
		frappe.throw(
			_("Repeat Unit must be one of: {0}").format(", ".join(REPEAT_UNITS))
		)
	if require_ready and not any(cint(doc.get(f"custom_{field}")) for field in WEEKDAY_FIELDS):
		frappe.throw(_("Select at least one sending weekday"))
	if cint(doc.custom_restrict_sending_window):
		if not doc.custom_window_start or not doc.custom_window_end:
			frappe.throw(_("Both start and end times are required for a sending window"))
		if get_time(doc.custom_window_start) >= get_time(doc.custom_window_end):
			frappe.throw(_("The sending window end must be later than its start"))

	if doc.custom_email_account:
		account = frappe.get_cached_doc("Email Account", doc.custom_email_account)
		account.check_permission("read")
		if not account.enable_outgoing:
			frappe.throw(
				_("Email Account {0} is not enabled for outgoing mail").format(doc.custom_email_account)
			)
		if cint(doc.custom_enable_open_tracking) and not cint(account.track_email_status):
			frappe.throw(
				_("Enable Track Email Status on Email Account {0}, or disable Track Opens.").format(
					doc.custom_email_account
				)
			)
	if doc.custom_reply_to:
		validate_email_address(doc.custom_reply_to, throw=True)
	if doc.custom_email_template and frappe.get_meta("Email Template").has_field(
		"custom_reference_doctype"
	):
		reference_doctype = frappe.db.get_value(
			"Email Template", doc.custom_email_template, "custom_reference_doctype"
		)
		if reference_doctype and reference_doctype != "Lead":
			frappe.throw(
				_("The selected template is configured for {0}, not Lead").format(reference_doctype)
			)
		doc.custom_template_reference_doctype = reference_doctype


def validate_lead_filters(filters_json, require_filters=False):
	try:
		filters = frappe.parse_json(filters_json or "[]")
	except (TypeError, ValueError):
		frappe.throw(_("Lead Filters must contain valid JSON"))
	if not isinstance(filters, list):
		frappe.throw(_("Lead Filters must be a list"))
	if len(filters) > MAX_AUDIENCE_FILTERS:
		frappe.throw(_("Use no more than {0} audience filters").format(MAX_AUDIENCE_FILTERS))
	if require_filters and not filters:
		frappe.throw(_("A dynamic segment needs at least one Lead filter"))

	meta = frappe.get_meta("Lead")
	standard_fields = {
		"name",
		"owner",
		"creation",
		"modified",
		"modified_by",
		"docstatus",
		"idx",
	}
	allowed_fields_by_doctype = {
		"Lead": standard_fields
		| {field.fieldname for field in meta.fields if field.fieldname}
	}
	for field in meta.fields:
		if field.fieldtype not in ("Table", "Table MultiSelect") or not field.options:
			continue
		child_meta = frappe.get_meta(field.options)
		if child_meta.istable:
			allowed_fields_by_doctype[field.options] = {
				child_field.fieldname
				for child_field in child_meta.fields
				if child_field.fieldname
			}
	normalized = []
	for item in filters:
		if not isinstance(item, (list, tuple)) or len(item) < 4:
			frappe.throw(_("Every Lead filter must have DocType, field, operator and value"))
		doctype, fieldname, operator, value = item[:4]
		if not all(isinstance(item_value, str) for item_value in (doctype, fieldname, operator)):
			frappe.throw(_("Filter DocType, field and operator must be text values"))
		allowed_fields = allowed_fields_by_doctype.get(doctype)
		if allowed_fields is None:
			frappe.throw(_("Audience filters may target only Lead or its child-table fields"))
		if fieldname not in allowed_fields:
			frappe.throw(
				_("Field {0}.{1} is not available for audience filtering").format(
					doctype, fieldname
				)
			)
		if operator not in FILTER_OPERATORS:
			frappe.throw(_("Filter operator {0} is not allowed").format(operator))
		normalized.append([doctype, fieldname, operator, value])
	return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


def validate_lead_filter_groups(filters_json, require_filters=False):
	"""Validate OR groups of regular Lead filters.

	A legacy flat filter list remains valid and is treated as one AND group.
	"""
	try:
		groups = frappe.parse_json(filters_json or "[]")
	except (TypeError, ValueError):
		frappe.throw(_("Lead Filter Groups must contain valid JSON"))
	if not isinstance(groups, list):
		frappe.throw(_("Lead Filter Groups must be a list"))
	if groups and isinstance(groups[0], (list, tuple)) and len(groups[0]) >= 4 and isinstance(groups[0][0], str):
		groups = [groups]
	if len(groups) > MAX_AUDIENCE_FILTER_GROUPS:
		frappe.throw(_("Use no more than {0} audience filter groups").format(MAX_AUDIENCE_FILTER_GROUPS))

	normalized = []
	filter_count = 0
	for group in groups:
		if not isinstance(group, list):
			frappe.throw(_("Every audience filter group must be a list"))
		if not group:
			continue
		filters = frappe.parse_json(validate_lead_filters(json.dumps(group)))
		filter_count += len(filters)
		if filter_count > MAX_AUDIENCE_FILTERS:
			frappe.throw(_("Use no more than {0} audience filters").format(MAX_AUDIENCE_FILTERS))
		normalized.append(filters)
	if require_filters and not normalized:
		frappe.throw(_("A dynamic segment needs at least one Lead filter group"))
	return json.dumps(normalized, separators=(",", ":"), ensure_ascii=False)


def validate_excluded_email_groups(groups_json):
	try:
		groups = frappe.parse_json(groups_json or "[]")
	except (TypeError, ValueError):
		frappe.throw(_("Excluded Email Groups must contain valid JSON"))
	if not isinstance(groups, list):
		frappe.throw(_("Excluded Email Groups must be a list"))
	if len(groups) > MAX_EXCLUDED_EMAIL_GROUPS:
		frappe.throw(
			_("Select no more than {0} excluded Email Groups").format(
				MAX_EXCLUDED_EMAIL_GROUPS
			)
		)
	normalized = []
	for group_name in groups:
		if not isinstance(group_name, str) or not group_name.strip():
			frappe.throw(_("Every excluded Email Group must be a document name"))
		group_name = group_name.strip()
		if group_name not in normalized:
			normalized.append(group_name)
	if not normalized:
		return normalized
	existing = set(
		frappe.get_all(
			"Email Group",
			filters={"name": ["in", normalized]},
			pluck="name",
			limit_page_length=0,
		)
	)
	missing = next((name for name in normalized if name not in existing), None)
	if missing:
		frappe.throw(_("Email Group {0} does not exist").format(frappe.bold(missing)))
	return normalized


def _lead_names_from_filters(filters_json, require_filters=False):
	normalized = validate_lead_filters(filters_json, require_filters=require_filters)
	filters = frappe.parse_json(normalized)
	if not filters:
		return []
	names = frappe.get_list(
		"Lead",
		filters=filters,
		pluck="name",
		distinct=True,
		limit=0,
		order_by="name asc",
	)
	return names


def _lead_names_from_filter_groups(filters_json, require_filters=False):
	groups = frappe.parse_json(validate_lead_filter_groups(filters_json, require_filters=require_filters))
	names = set()
	for group in groups:
		if len(group) == 1 and group[0][1] == "name" and group[0][2] == "in" and isinstance(group[0][3], list) and len(group[0][3]) > 0 and group[0][3][0] == "#STATIC_SEGMENT#":
			segment_name = group[0][3][1] if len(group[0][3]) > 1 else ""
			if segment_name:
				segment = frappe.get_doc("Reach Segment", segment_name)
				if segment.segment_type == "Static":
					names.update(frappe.parse_json(segment.static_leads_json or "[]"))
		else:
			names.update(_lead_names_from_filters(json.dumps(group)))
	return sorted(names)


def _chunks(values, size=500):
	values = list(values)
	for start in range(0, len(values), size):
		yield values[start : start + size]


def _normalized_email(value):
	address = parse_addr(str(value or ""))[1].strip()
	validated = validate_email_address(address, throw=False) if address else ""
	return str(validated or "").strip().lower()


def _email_group_addresses(group_name):
	return {
		_normalized_email(email)
		for email in frappe.get_all(
			"Email Group Member", filters={"email_group": group_name}, pluck="email", limit_page_length=0
		)
		if _normalized_email(email)
	}


def _linked_unsubscribed_leads(lead_names):
	result = set()
	for names in _chunks(lead_names):
		links = frappe.get_all(
			"Dynamic Link",
			filters={
				"parenttype": "Contact",
				"link_doctype": "Lead",
				"link_name": ["in", names],
			},
			fields=["parent", "link_name"],
			limit_page_length=0,
		)
		contacts = {row.parent for row in links}
		unsubscribed_contacts = set()
		if contacts:
			unsubscribed_contacts = set(
				frappe.get_all(
					"Contact",
					filters={"name": ["in", list(contacts)], "unsubscribed": 1},
					pluck="name",
					limit_page_length=0,
				)
			)
		result.update(row.link_name for row in links if row.parent in unsubscribed_contacts)
	return result


def _globally_unsubscribed_emails(emails):
	result = set()
	for values in _chunks(emails):
		result.update(
			_normalized_email(email)
			for email in frappe.get_all(
				"Email Unsubscribe",
				filters={"email": ["in", values], "global_unsubscribe": 1},
				pluck="email",
				limit_page_length=0,
			)
		)
	return result


def _reference_unsubscribed_pairs(lead_names):
	result = set()
	for names in _chunks(lead_names):
		for row in frappe.get_all(
			"Email Unsubscribe",
			filters={
				"reference_doctype": "Lead",
				"reference_name": ["in", names],
			},
			fields=["reference_name", "email"],
			limit_page_length=0,
		):
			if normalized := _normalized_email(row.email):
				result.add((row.reference_name, normalized))
	return result


def _topic_unsubscribed_leads(lead_names, subscription_topic):
	if not subscription_topic:
		return set()
	result = set()
	for names in _chunks(lead_names):
		result.update(
			frappe.get_all(
				"Unsubscribe Topic Multi Select",
				filters={
					"parenttype": "Lead",
					"parentfield": "custom_unsubscribe_topics",
					"parent": ["in", names],
					"subscription_topic": subscription_topic,
				},
				pluck="parent",
				limit_page_length=0,
			)
		)
	return result


def test_recipient_exclusion(email, subscription_topic=None):
	"""Return a suppression reason when a campaign test address is opted out."""
	normalized_email = _normalized_email(email)
	if not normalized_email:
		return _("Missing or invalid email")
	# Bypassed: campaign emails now skip the global Email Unsubscribe list
	# via get_unsubscribed_user_emails() patch in hooks.py.  Topic-wise filtering is the
	# sole authority for campaign suppression.
	# if normalized_email in _globally_unsubscribed_emails([normalized_email]):
	# 	return _("Globally unsubscribed")

	leads = frappe.get_all(
		"Lead",
		filters={"email_id": normalized_email},
		fields=["name", "disabled", "unsubscribed", "status"],
		limit_page_length=0,
	)
	lead_names = [row.name for row in leads]
	if any(cint(row.disabled) for row in leads):
		return _("Lead disabled")
	if any(cint(row.unsubscribed) for row in leads):
		return _("Lead unsubscribed")
	if any(row.status == "Do Not Contact" for row in leads):
		return _("Do Not Contact")
	if lead_names and _linked_unsubscribed_leads(lead_names):
		return _("Linked Contact unsubscribed")
	# Bypassed: see get_unsubscribed_user_emails() patch in hooks.py.
	# if lead_names and any(
	# 	lead_name == reference and normalized_email == unsubscribed_email
	# 	for reference, unsubscribed_email in _reference_unsubscribed_pairs(lead_names)
	# 	for lead_name in lead_names
	# ):
	# 	return _("Unsubscribed from Lead emails")
	if subscription_topic and lead_names:
		if _topic_unsubscribed_leads(lead_names, subscription_topic):
			return _("Unsubscribed from topic {0}").format(subscription_topic)

	contact_names = frappe.get_all(
		"Contact Email",
		filters={"email_id": normalized_email},
		pluck="parent",
		limit_page_length=0,
	)
	if contact_names and frappe.db.exists(
		"Contact", {"name": ["in", list(set(contact_names))], "unsubscribed": 1}
	):
		return _("Contact unsubscribed")
	return None


def resolve_campaign_audience(campaign):
	if isinstance(campaign, str):
		campaign = frappe.get_doc("Campaign", campaign)
	include_leads = set(campaign.get("studio_include_leads") or [])
	if not include_leads:
		include_leads.update(
			_lead_names_from_filter_groups(campaign.get("custom_lead_filters_json"), require_filters=True)
		)
	exclude_leads = set(campaign.get("studio_exclude_leads") or [])
	if not exclude_leads and campaign.get("custom_exclude_filters_json"):
		exclude_leads.update(
			_lead_names_from_filter_groups(campaign.get("custom_exclude_filters_json"))
		)
	exclude_emails = set()
	for group_name in validate_excluded_email_groups(
		campaign.get("custom_exclude_email_groups_json")
	):
		exclude_emails.update(_email_group_addresses(group_name))

	if not include_leads:
		return []
	rows = []
	for names in _chunks(sorted(include_leads)):
		rows.extend(
			frappe.get_list(
				"Lead",
				filters={"name": ["in", names]},
				fields=["name", "email_id", "status", "unsubscribed", "disabled"],
				limit=0,
			)
		)
	rows_by_name = {row.name: row for row in rows}
	linked_unsubscribed = _linked_unsubscribed_leads(include_leads)
	normalized_by_lead = {
		name: _normalized_email(rows_by_name.get(name).email_id if rows_by_name.get(name) else "")
		for name in include_leads
	}
	# Bypassed: see get_unsubscribed_user_emails() patch in hooks.py.
	# global_unsubscribed = _globally_unsubscribed_emails(
	# 	{email for email in normalized_by_lead.values() if email}
	# )
	global_unsubscribed = set()
	# Bypassed: see get_unsubscribed_user_emails() patch in hooks.py.
	# reference_unsubscribed = _reference_unsubscribed_pairs(include_leads)
	reference_unsubscribed = set()
	topic_unsubscribed = _topic_unsubscribed_leads(
		include_leads, campaign.get("custom_subscription_topic")
	)
	topic_unsubscribed_emails = {
		normalized_by_lead.get(lead_name)
		for lead_name in topic_unsubscribed
		if normalized_by_lead.get(lead_name)
	}
	seen_emails = set()
	result = []
	for lead_name in sorted(include_leads):
		lead = rows_by_name.get(lead_name)
		email = lead.email_id if lead else ""
		normalized = normalized_by_lead.get(lead_name) or ""
		reason = None
		if not lead:
			reason = "Lead unavailable"
		elif lead_name in exclude_leads:
			reason = "Excluded by Lead filters"
		elif cint(lead.disabled):
			reason = "Lead disabled"
		elif cint(lead.unsubscribed):
			reason = "Lead unsubscribed"
		elif lead.status == "Do Not Contact":
			reason = "Do Not Contact"
		elif lead_name in linked_unsubscribed:
			reason = "Linked Contact unsubscribed"
		elif not normalized:
			reason = "Missing or invalid email"
		elif normalized in exclude_emails:
			reason = "Excluded by Email Group"
		elif normalized in global_unsubscribed:
			reason = "Globally unsubscribed"
		elif (lead_name, normalized) in reference_unsubscribed:
			reason = "Unsubscribed from Lead emails"
		elif lead_name in topic_unsubscribed or normalized in topic_unsubscribed_emails:
			reason = _("Unsubscribed from topic {0}").format(
				campaign.get("custom_subscription_topic")
			)
		elif normalized in seen_emails:
			reason = "Duplicate email"
		else:
			seen_emails.add(normalized)
		result.append(
			frappe._dict(
				lead=lead_name,
				email=email,
				normalized_email=normalized,
				eligible=not reason,
				reason=reason,
				topic_unsubscribed=(
					lead_name in topic_unsubscribed
					or normalized in topic_unsubscribed_emails
				),
			)
		)
	return result


def preview_campaign_audience(campaign):
	resolved = resolve_campaign_audience(campaign)
	reasons = Counter(row.reason for row in resolved if row.reason)
	return {
		"candidate_count": len(resolved),
		"eligible_count": sum(1 for row in resolved if row.eligible),
		"excluded_count": sum(1 for row in resolved if not row.eligible),
		"excluded_reasons": dict(reasons),
	}


def _selected_weekdays(campaign):
	return {
		index
		for index, field in enumerate(WEEKDAY_FIELDS)
		if cint(campaign.get(f"custom_{field}"))
	}


def _interval(campaign):
	amount = cint(campaign.custom_repeat_every)
	if campaign.custom_repeat_unit == "Minutes":
		return timedelta(minutes=amount)
	if campaign.custom_repeat_unit == "Hours":
		return timedelta(hours=amount)
	if campaign.custom_repeat_unit == "Days":
		return timedelta(days=amount)
	frappe.throw(_("Unsupported repeat unit: {0}").format(campaign.custom_repeat_unit))


def _normalize_local_datetime(value, timezone):
	if value.tzinfo is None:
		value = value.replace(tzinfo=timezone)
	else:
		value = value.astimezone(timezone)
	return value.astimezone(UTC).astimezone(timezone)


def _next_valid_slot(value, campaign, timezone):
	allowed_days = _selected_weekdays(campaign)
	window_start = (
		get_time(campaign.custom_window_start)
		if cint(campaign.custom_restrict_sending_window)
		else None
	)
	window_end = (
		get_time(campaign.custom_window_end)
		if cint(campaign.custom_restrict_sending_window)
		else None
	)
	value = _normalize_local_datetime(value, timezone)
	for _unused in range(15):
		if value.weekday() not in allowed_days:
			value = (value + timedelta(days=1)).replace(
				hour=window_start.hour if window_start else value.hour,
				minute=window_start.minute if window_start else value.minute,
				second=0,
				microsecond=0,
			)
			continue
		if window_start and value.time().replace(tzinfo=None) < window_start:
			value = value.replace(
				hour=window_start.hour,
				minute=window_start.minute,
				second=0,
				microsecond=0,
			)
		if window_end and value.time().replace(tzinfo=None) > window_end:
			value = (value + timedelta(days=1)).replace(
				hour=window_start.hour,
				minute=window_start.minute,
				second=0,
				microsecond=0,
			)
			continue
		return _normalize_local_datetime(value, timezone)
	frappe.throw(_("Could not calculate a valid sending slot"))


def calculate_batch_slots(campaign, batch_count, start_local=None):
	timezone = _system_zone()
	if start_local is None:
		start_local = get_datetime(campaign.custom_start_on)
	else:
		start_local = _normalize_local_datetime(start_local, timezone)
	current = _next_valid_slot(start_local, campaign, timezone)
	interval = _interval(campaign)
	slots = []
	for index in range(batch_count):
		if index:
			current = _next_valid_slot(current + interval, campaign, timezone)
		# Frappe stores and compares Datetime values in the configured system
		# timezone. Strip the timezone only after calculating the local slot.
		slots.append(current.replace(tzinfo=None))
	return slots



def calculate_delivery_batches(campaign, recipient_count, start_local=None):
	"""Split recipients into user-configured batches without application caps.

	The configured batch size, repeat interval, allowed weekdays and optional
	sending window still determine the schedule. Frappe's Email Queue and the
	selected email provider remain responsible for actual SMTP throughput.
	"""
	recipient_count = max(0, cint(recipient_count))
	if not recipient_count:
		return []

	batch_size = max(1, cint(campaign.custom_batch_size))
	batch_count = (recipient_count + batch_size - 1) // batch_size
	slots = calculate_batch_slots(campaign, batch_count, start_local=start_local)
	batches = []
	remaining = recipient_count
	for number, scheduled_at in enumerate(slots, start=1):
		size = min(batch_size, remaining)
		batches.append(
			frappe._dict(
				number=number,
				size=size,
				scheduled_at=scheduled_at,
			)
		)
		remaining -= size
	return batches


def _snapshot_values(snapshot):
	return {
		"custom_template_mode": snapshot.mode,
		"custom_template_reference_doctype": snapshot.reference_doctype,
		"custom_snapshot_subject": snapshot.subject,
		"custom_snapshot_preheader": snapshot.preheader,
		"custom_snapshot_html": snapshot.html,
		"custom_snapshot_hash": snapshot.content_hash,
	}


def _recipient_values(campaign, row, batch_number=0, scheduled_at=None):
	delivery_status = "Planned" if row.eligible else "Skipped"
	return {
		"doctype": "Email Campaign",
		"campaign_name": campaign.name,
		"status": "Scheduled" if row.eligible else "Completed",
		"start_date": getdate(scheduled_at or campaign.custom_start_on),
		"end_date": getdate(scheduled_at or campaign.custom_start_on),
		"email_campaign_for": "Lead",
		"recipient": row.lead,
		"custom_delivery_status": delivery_status,
		"custom_scheduled_at": scheduled_at,
		"custom_batch_number": batch_number,
		"custom_recipient_email": row.email,
		"custom_normalized_email": row.normalized_email,
		"custom_excluded_reason": row.reason,
	}


def _insert_scheduled_recipient(values):
	previous = frappe.flags.get(SCHEDULER_RECIPIENT_INSERT_FLAG)
	frappe.flags[SCHEDULER_RECIPIENT_INSERT_FLAG] = True
	try:
		return frappe.get_doc(values).insert(ignore_permissions=True)
	finally:
		frappe.flags[SCHEDULER_RECIPIENT_INSERT_FLAG] = previous


def _reschedule_recipient_batches(recipients, batches, retry=False):
	# One database update per delivery batch; recipient rows preserve their identity.
	recipient_table = frappe.qb.DocType("Email Campaign")
	cursor = 0
	for batch in batches:
		names = [row.name for row in recipients[cursor : cursor + batch.size]]
		cursor += batch.size
		if not names:
			continue
		query = (
			frappe.qb.update(recipient_table)
			.set(recipient_table.custom_scheduled_at, batch.scheduled_at)
			.set(recipient_table.custom_batch_number, batch.number)
			.where(recipient_table.name.isin(names))
		)
		if retry:
			query = (
				query.set(recipient_table.status, "Scheduled")
				.set(recipient_table.custom_delivery_status, "Planned")
				.set(recipient_table.custom_email_queue, None)
				.set(recipient_table.custom_error_message, None)
			)
		query.run()

def schedule_campaign(campaign_name):
    try:
        _schedule_campaign_internal(campaign_name)
    except Exception:
        frappe.db.rollback()
        frappe.log_error(
            title=f"Campaign Scheduling Failed: {campaign_name}",
            message=frappe.get_traceback(),
        )
        frappe.db.set_value(
            "Campaign",
            campaign_name,
            "custom_queued",
            0,
            update_modified=False,
        )
        frappe.db.commit()
        raise
    else:
        frappe.db.set_value(
            "Campaign",
            campaign_name,
            "custom_queued",
            0,
            update_modified=False,
        )

def _schedule_campaign_internal(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status != "Draft":
		frappe.throw(_("Only a Draft broadcast can be scheduled"))
	if frappe.db.exists("Email Campaign", {"campaign_name": campaign.name}):
		frappe.throw(
			_("This campaign already has delivery history and cannot be scheduled again. Retry failed recipients or create a new campaign.")
		)
	validate_campaign(campaign, require_ready=True, skip_queued_check=True)
	validate_lead_filter_groups(campaign.custom_lead_filters_json, require_filters=True)
	validate_lead_filter_groups(campaign.custom_exclude_filters_json)
	validate_excluded_email_groups(campaign.custom_exclude_email_groups_json)
	start_slot = calculate_batch_slots(campaign, 1)[0]
	if start_slot < now_datetime() - timedelta(minutes=1):
		frappe.throw(_("Campaign start time cannot be in the past"))

	snapshot = get_campaign_snapshot(
		campaign.custom_email_template,
		campaign.custom_subject_override,
	)
	if snapshot.reference_doctype and snapshot.reference_doctype != "Lead":
		frappe.throw(_("Campaign templates must use Lead personalization"))
	resolved = resolve_campaign_audience(campaign)
	eligible = [row for row in resolved if row.eligible]
	if not eligible:
		frappe.throw(_("No eligible recipients remain after exclusions"))
	frappe.db.set_value("Campaign", campaign.name, "custom_broadcast_status", "Preparing Audience")
	frappe.db.delete(
		"Email Campaign",
		{"campaign_name": campaign.name},
	)
	batches = calculate_delivery_batches(campaign, len(eligible))
	batch_count = len(batches)
	slots = [batch.scheduled_at for batch in batches]
	cursor = 0
	for batch in batches:
		for row in eligible[cursor : cursor + batch.size]:
			_insert_scheduled_recipient(
				_recipient_values(
					campaign,
					row,
					batch_number=batch.number,
					scheduled_at=batch.scheduled_at,
				)
			)
		cursor += batch.size
	for row in (item for item in resolved if not item.eligible):
		_insert_scheduled_recipient(_recipient_values(campaign, row))

	values = {
		**_snapshot_values(snapshot),
		"custom_broadcast_status": "Scheduled",
		"custom_candidate_count": len(resolved),
		"custom_eligible_count": len(eligible),
		"custom_excluded_count": len(resolved) - len(eligible),
		"custom_batch_count": batch_count,
		"custom_first_scheduled_at": slots[0],
		"custom_last_scheduled_at": slots[-1],
	}
	frappe.db.set_value("Campaign", campaign.name, values)
	return {"message": _("Campaign scheduled"), **values}


@frappe.whitelist(methods=["POST"])
def pause_campaign(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status not in ("Scheduled", "Sending"):
		frappe.throw(_("Only a scheduled or sending campaign can be paused"))
	campaign.db_set("custom_broadcast_status", "Paused")
	return {"message": _("Campaign paused. Already queued emails may still be sent.")}


@frappe.whitelist(methods=["POST"])
def resume_campaign(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status != "Paused":
		frappe.throw(_("Only a paused campaign can be resumed"))
	planned = frappe.get_all(
		"Email Campaign",
		filters={
			"campaign_name": campaign.name,
			"custom_delivery_status": "Planned",
		},
		fields=["name"],
		order_by="custom_batch_number asc, name asc",
		limit=0,
	)
	if planned:
		start = datetime.now(_system_zone()) + timedelta(minutes=1)
		batches = calculate_delivery_batches(campaign, len(planned), start_local=start)
		_reschedule_recipient_batches(planned, batches)
		frappe.db.set_value(
			"Campaign",
			campaign.name,
			{
				"custom_broadcast_status": "Scheduled",
				"custom_last_scheduled_at": batches[-1].scheduled_at,
			},
		)
	else:
		campaign.db_set("custom_broadcast_status", "Sending")
		refresh_campaign_metrics(campaign.name)
	return {"message": _("Campaign resumed from the next valid sending slot")}


@frappe.whitelist(methods=["POST"])
def cancel_campaign(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status not in ("Scheduled", "Sending", "Paused"):
		frappe.throw(_("This campaign cannot be cancelled"))
	recipient = frappe.qb.DocType("Email Campaign")
	(
		frappe.qb.update(recipient)
		.set(recipient.custom_delivery_status, "Cancelled")
		.set(recipient.status, "Completed")
		.where(recipient.campaign_name == campaign.name)
		.where(recipient.custom_delivery_status.isin(["Planned", "Processing"]))
	).run()
	campaign.db_set("custom_broadcast_status", "Cancelled")
	refresh_campaign_metrics(campaign.name)
	queued = frappe.db.count(
		"Email Campaign",
		{"campaign_name": campaign.name, "custom_delivery_status": "Queued"},
	)
	return {
		"message": _("Campaign cancelled. {0} already queued email(s) may still be sent.").format(queued),
		"queued_count": queued,
	}


@frappe.whitelist(methods=["POST"])
def retry_failed_recipients(campaign_name):
	"""Retry only terminal failures while preserving sent/skipped recipient history."""
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status != "Failed":
		frappe.throw(_("Only a failed campaign can retry failed recipients"))
	if frappe.db.count(
		"Email Campaign",
		{
			"campaign_name": campaign.name,
			"custom_delivery_status": ["in", ["Planned", "Processing", "Queued"]],
		},
	):
		frappe.throw(_("Wait for active recipients to finish before retrying failures"))

	failed = frappe.get_all(
		"Email Campaign",
		filters={"campaign_name": campaign.name, "custom_delivery_status": "Failed"},
		fields=["name", "custom_email_queue"],
		order_by="custom_batch_number asc, name asc",
		limit=0,
	)
	if not failed:
		frappe.throw(_("This campaign has no failed recipients to retry"))

	start = datetime.now(_system_zone()) + timedelta(minutes=1)
	batches = calculate_delivery_batches(campaign, len(failed), start_local=start)
	_reschedule_recipient_batches(failed, batches, retry=True)
	frappe.db.set_value(
		"Campaign",
		campaign.name,
		{
			"custom_broadcast_status": "Scheduled",
			"custom_failed_count": 0,
		},
	)
	return {
		"message": _("{0} failed recipient(s) scheduled for retry").format(len(failed)),
		"retried_count": len(failed),
	}


def _append_utm(url, source, medium, campaign, content):
	parsed = urlparse(url)
	if parsed.scheme not in ("http", "https") or not parsed.netloc:
		return url
	query = parse_qsl(parsed.query, keep_blank_values=True)
	existing_content = next((value for key, value in query if key == "utm_content" and value), None)
	query = [(key, value) for key, value in query if key not in {"utm_source", "utm_medium", "utm_campaign", "utm_content"}]
	query.extend(
		[
			("utm_source", source),
			("utm_medium", medium),
			("utm_campaign", campaign),
			("utm_content", existing_content or content),
		]
	)
	return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def decorate_campaign_links(html, campaign, recipient_name, track_clicks=None):
	soup = BeautifulSoup(html or "", "html.parser")
	track_clicks = (
		cint(campaign.custom_enable_click_tracking)
		if track_clicks is None
		else cint(track_clicks)
	)
	for index, link in enumerate(soup.find_all("a"), start=1):
		href = str(link.get("href") or "").strip()
		if CLICK_METHOD in href or UNSUBSCRIBE_METHOD in href or "view_email" in href:
			continue
		final_url = _append_utm(
			href,
			campaign.custom_utm_source,
			campaign.custom_utm_medium,
			campaign.custom_utm_campaign,
			f"link-{index}",
		)
		if final_url == href:
			continue
		if track_clicks:
			params = get_signed_params(
				{"campaign_recipient": recipient_name, "url": final_url}
			)
			final_url = get_url(f"/api/method/{CLICK_METHOD}?{params}")
		link["href"] = final_url
	return str(soup)


def _sender(campaign):
	account = frappe.get_cached_doc("Email Account", campaign.custom_email_account)
	return (
		formataddr((campaign.custom_sender_name, account.email_id))
		if campaign.custom_sender_name
		else account.email_id
	)


def _log_event(
	event_type,
	recipient,
	communication=None,
	url=None,
	metadata=None,
	check_existing=True,
	check_table=True,
):
	if check_table and not frappe.db.table_exists("Email Tracking Event"):
		return
	if check_existing:
		filters = {
			"event_type": event_type,
			"marketing_campaign_recipient": recipient.name,
			"url": url or ["in", ["", None]],
		}
		if frappe.db.exists("Email Tracking Event", filters):
			return
	frappe.get_doc(
		{
			"doctype": "Email Tracking Event",
			"event_type": event_type,
			"event_time": now_datetime(),
			"marketing_email_campaign": recipient.campaign_name,
			"marketing_campaign_recipient": recipient.name,
			"lead": recipient.recipient,
			"communication": communication,
			"url": url,
			"metadata_json": json.dumps(
				metadata or {},
				separators=(",", ":"),
				sort_keys=True,
			),
		}
	).insert(ignore_permissions=True)


def _current_recipient_exclusion(recipient, campaign):
	if cint(recipient.custom_unsubscribed):
		return _("Recipient unsubscribed")
	if not campaign.custom_subscription_topic or frappe.db.get_value(
		"Subscription Topic", campaign.custom_subscription_topic, "disabled"
	):
		return _("Subscription Topic unavailable or disabled")
	lead = frappe.db.get_value(
		"Lead",
		recipient.recipient,
		["disabled", "unsubscribed", "status"],
		as_dict=True,
	)
	if not lead:
		return _("Lead unavailable")
	if cint(lead.disabled):
		return _("Lead disabled")
	if cint(lead.unsubscribed):
		return _("Lead unsubscribed")
	if lead.status == "Do Not Contact":
		return _("Do Not Contact")
	if recipient.recipient in _linked_unsubscribed_leads([recipient.recipient]):
		return _("Linked Contact unsubscribed")
	normalized_email = _normalized_email(recipient.custom_recipient_email)
	# Bypassed: see get_unsubscribed_user_emails() patch in hooks.py.
	# if normalized_email in _globally_unsubscribed_emails([normalized_email]):
	# 	return _("Globally unsubscribed")
	# Bypassed: see get_unsubscribed_user_emails() patch in hooks.py.
	# if (recipient.recipient, normalized_email) in _reference_unsubscribed_pairs(
	# 	[recipient.recipient]
	# ):
	# 	return _("Unsubscribed from Lead emails")
	topic_leads = [recipient.recipient]
	if recipient.custom_recipient_email:
		topic_leads.extend(
			frappe.get_all(
				"Lead",
				filters={"email_id": recipient.custom_recipient_email},
				pluck="name",
				limit_page_length=0,
			)
		)
	if _topic_unsubscribed_leads(
		list(dict.fromkeys(topic_leads)), campaign.custom_subscription_topic
	):
		return _("Unsubscribed from topic {0}").format(campaign.custom_subscription_topic)
	return None


def _dispatch_recipient(recipient, campaign):
	if recipient.custom_email_queue and frappe.db.exists(
		"Email Queue", recipient.custom_email_queue
	):
		frappe.db.set_value(
			"Email Campaign",
			recipient.name,
			{
				"custom_delivery_status": "Queued",
				"custom_released_at": now_datetime(),
				"custom_error_message": None,
			},
		)
		return
	lead = frappe.get_doc("Lead", recipient.recipient)
	preview_url = get_url(
		f"/view_email?{get_signed_params({'campaign_recipient': recipient.name})}"
	)
	rendered = render_campaign_snapshot(
		campaign.custom_snapshot_subject,
		campaign.custom_snapshot_html,
		lead,
		extra_context={"email_preview_url": preview_url},
	)
	html = decorate_campaign_links(rendered.html, campaign, recipient.name)
	delivery_html = (																																	
		_ensure_raw_html_delivery_markers(html)
		if campaign.custom_template_mode == "Visual"
		else html
	)
	communication = None
	if recipient.custom_communication and frappe.db.exists(
		"Communication", recipient.custom_communication
	):
		communication = frappe.get_doc("Communication", recipient.custom_communication)
	else:
		comm = make(
			doctype="Lead",
			name=lead.name,
			subject=rendered.subject,
			content=html,
			sender=_sender(campaign),
			recipients=[recipient.custom_recipient_email],
			communication_medium="Email",
			sent_or_received="Sent",
			send_email=False,
			email_template=campaign.custom_email_template,
			send_after=recipient.custom_scheduled_at,
			raw_html=campaign.custom_template_mode == "Visual",
			add_css=campaign.custom_template_mode != "Visual",
		)
		communication = frappe.get_doc("Communication", comm["name"])
		communication.append(
			"timeline_links",
			{"link_doctype": "Campaign", "link_name": campaign.name},
		)
		communication.save(ignore_permissions=True)
	queue = frappe.sendmail(
		recipients=[recipient.custom_recipient_email],
		sender=_sender(campaign),
		reply_to=campaign.custom_reply_to or None,
		subject=rendered.subject,
		content=delivery_html,
		reference_doctype="Lead",
		reference_name=lead.name,
		communication=communication.name,
		send_after=recipient.custom_scheduled_at,
		unsubscribe_message=_("Unsubscribe"),
		unsubscribe_method=f"/api/method/{UNSUBSCRIBE_METHOD}",
		unsubscribe_params={"campaign_recipient": recipient.name},
		raw_html=campaign.custom_template_mode == "Visual",
		add_css=campaign.custom_template_mode != "Visual",
	)
	if not queue:
		frappe.throw(_("Frappe did not create an Email Queue record"))
	if not cint(campaign.custom_enable_open_tracking):
		queue.message = str(queue.message or "").replace("<!--email_open_check-->", "")
		queue.db_set("message", queue.message, update_modified=False)
	frappe.db.set_value(
		"Email Campaign",
		recipient.name,
		{
			"custom_communication": communication.name,
			"custom_email_queue": queue.name,
			"custom_delivery_status": "Queued",
			"custom_released_at": now_datetime(),
			"custom_error_message": None,
		},
	)
	_log_event("Queued", recipient, communication=communication.name)


def _reset_stale_processing_recipients():
	recipient_table = frappe.qb.DocType("Email Campaign")
	active_campaigns = frappe.get_all(
		"Campaign",
		filters={"custom_broadcast_status": ["in", ["Scheduled", "Sending", "Paused"]]},
		pluck="name",
		limit=0,
	)
	if active_campaigns:
		(
			frappe.qb.update(recipient_table)
			.set(recipient_table.custom_delivery_status, "Planned")
			.where(recipient_table.campaign_name.isin(active_campaigns))
			.where(recipient_table.custom_delivery_status == "Processing")
			.where(
				recipient_table.modified
				<= now_datetime() - timedelta(minutes=STALE_PROCESSING_AFTER_MINUTES)
			)
		).run()
	cancelled_campaigns = frappe.get_all(
		"Campaign",
		filters={"custom_broadcast_status": "Cancelled"},
		pluck="name",
		limit=0,
	)
	if cancelled_campaigns:
		(
			frappe.qb.update(recipient_table)
			.set(recipient_table.custom_delivery_status, "Cancelled")
			.set(recipient_table.status, "Completed")
			.where(recipient_table.campaign_name.isin(cancelled_campaigns))
			.where(recipient_table.custom_delivery_status == "Processing")
		).run()


def dispatch_due_marketing_batches():
	# Respect Frappe's global email switches, but do not impose an additional
	# campaign-level batch, rate, daily, or pending-queue cap. All due recipients
	# are handed to Frappe Email Queue in this scheduler pass.
	if frappe.are_emails_muted() or cint(frappe.db.get_default("suspend_email_queue")):
		return
	_reset_stale_processing_recipients()
	now = now_datetime()
	active_campaigns = frappe.get_all(
		"Campaign",
		filters={"custom_broadcast_status": ["in", ["Scheduled", "Sending"]]},
		pluck="name",
		limit=0,
	)
	if not active_campaigns:
		return
	rows = frappe.get_all(
		"Email Campaign",
		filters={
			"campaign_name": ["in", active_campaigns],
			"custom_delivery_status": "Planned",
			"custom_scheduled_at": ["<=", now],
			"creation": [
				"<",
				add_to_date(now, seconds=-DISPATCH_UNDO_WINDOW_SECONDS),
			],
		},
		fields=["name", "campaign_name"],
		order_by="custom_scheduled_at asc, custom_batch_number asc, name asc",
		limit=0,
	)
	affected_campaigns = set()
	failures_by_campaign = Counter()
	recipients_by_campaign = Counter(row.campaign_name for row in rows)
	halted_campaigns = set()
	locked_campaigns = {}
	for row in rows:
		if row.campaign_name in halted_campaigns:
			continue
		savepoint = f"email_broadcast_{hashlib.md5(row.name.encode()).hexdigest()[:16]}"
		frappe.db.savepoint(savepoint)
		try:
			# This scheduler pass is one transaction. Lock each Campaign once while
			# all due recipient rows are handed to Frappe Email Queue.
			campaign = locked_campaigns.get(row.campaign_name)
			if campaign is None:
				campaign = frappe.get_doc("Campaign", row.campaign_name, for_update=True)
				locked_campaigns[row.campaign_name] = campaign
			if campaign.custom_broadcast_status not in ("Scheduled", "Sending"):
				continue
			recipient = frappe.get_doc("Email Campaign", row.name, for_update=True)
			if recipient.custom_delivery_status != "Planned":
				continue
			exclusion_reason = _current_recipient_exclusion(recipient, campaign)
			if exclusion_reason:
				frappe.db.set_value(
					"Email Campaign",
					recipient.name,
					{
						"status": "Completed",
						"custom_delivery_status": "Skipped",
						"custom_excluded_reason": exclusion_reason,
					},
				)
				affected_campaigns.add(row.campaign_name)
				continue
			recipient.db_set("custom_delivery_status", "Processing")
			if campaign.custom_broadcast_status == "Scheduled":
				campaign.db_set(
					"custom_broadcast_status",
					"Sending",
					update_modified=False,
				)
				campaign.custom_broadcast_status = "Sending"
			_dispatch_recipient(recipient, campaign)
		except Exception:
			frappe.db.rollback(save_point=savepoint)
			failure_traceback = frappe.get_traceback()
			frappe.db.set_value(
				"Email Campaign",
				row.name,
				{
					"status": "Completed",
					"custom_delivery_status": "Failed",
					"custom_error_message": failure_traceback[-1000:],
				},
			)
			frappe.log_error(
				failure_traceback,
				f"Email broadcast dispatch failed - {row.name}",
			)
			failures_by_campaign[row.campaign_name] += 1
			failure_count = failures_by_campaign[row.campaign_name]
			batch_count = recipients_by_campaign[row.campaign_name]
			if (
				failure_count / batch_count
				> DISPATCH_BATCH_FAILURE_THRESHOLD_PERCENT
				and failure_count > DISPATCH_BATCH_FAILURE_THRESHOLD_COUNT
			):
				halted_campaigns.add(row.campaign_name)
				frappe.db.set_value(
					"Campaign",
					row.campaign_name,
					"custom_broadcast_status",
					"Paused",
				)
		affected_campaigns.add(row.campaign_name)
	for campaign_name in affected_campaigns:
		refresh_campaign_metrics(campaign_name)


def sync_marketing_email_statuses():
	queued_rows = frappe.get_all(
		"Email Campaign",
		filters={
			"custom_delivery_status": "Queued",
			"custom_email_queue": ["is", "set"],
		},
		fields=[
			"name",
			"campaign_name",
			"recipient",
			"custom_email_queue",
			"custom_communication",
			"custom_opened",
			"custom_delivery_status",
		],
		order_by="modified asc",
		limit=500,
	)
	# Frappe records an open by updating Communication directly with db.set_value;
	# that does not run document hooks.  Join only Communications already marked
	# read so old unopened messages never occupy or starve this bounded scan.
	opened_rows = frappe.db.sql(
		"""
			select
				ec.name, ec.campaign_name, ec.recipient, ec.custom_email_queue,
				ec.custom_communication, ec.custom_opened,
				ec.custom_delivery_status, comm.read_by_recipient_on
			from `tabEmail Campaign` ec
			inner join `tabCommunication` comm
				on comm.name = ec.custom_communication
			where ec.custom_opened = 0
				and ec.custom_delivery_status in ('Queued', 'Sent')
				and comm.read_by_recipient = 1
			order by comm.read_by_recipient_on asc, ec.name asc
			limit 500
		""",
		as_dict=True,
	)
	rows_by_name = {row.name: row for row in queued_rows}
	for row in opened_rows:
		if row.name in rows_by_name:
			rows_by_name[row.name].read_by_recipient_on = row.read_by_recipient_on
		else:
			rows_by_name[row.name] = row
	rows = list(rows_by_name.values())
	queue_names = sorted({row.custom_email_queue for row in rows if row.custom_email_queue})
	queues_by_name = {}
	if queue_names:
		queues_by_name = {
			row.name: row
			for row in frappe.get_all(
				"Email Queue",
				filters={"name": ["in", queue_names]},
				fields=["name", "status", "error"],
				limit_page_length=0,
			)
		}
	communication_names = sorted(
		{row.custom_communication for row in rows if row.custom_communication}
	)
	communications_by_name = {}
	if communication_names:
		communications_by_name = {
			row.name: row
			for row in frappe.get_all(
				"Communication",
				filters={"name": ["in", communication_names]},
				fields=["name", "read_by_recipient", "read_by_recipient_on"],
				limit_page_length=0,
			)
		}
	open_event_names = set()
	if frappe.db.table_exists("Email Tracking Event"):
		candidates = [
			row.name
			for row in rows
			if not row.custom_opened
			and (
				row.get("read_by_recipient_on")
				or (
					(row.custom_communication and communications_by_name.get(row.custom_communication))
					and communications_by_name[row.custom_communication].read_by_recipient
				)
			)
		]
		if candidates:
			open_event_names = set(candidates) - set(
				frappe.get_all(
					"Email Tracking Event",
					filters={
						"event_type": "Opened",
						"marketing_campaign_recipient": ["in", candidates],
					},
					pluck="marketing_campaign_recipient",
					limit_page_length=0,
				)
			)
	affected_campaigns = set()
	for row in rows:
		updates = {}
		if row.custom_delivery_status == "Queued":
			queue = queues_by_name.get(row.custom_email_queue)
			if not queue:
				updates.update(
					{
						"status": "Completed",
						"custom_delivery_status": "Failed",
						"custom_error_message": _("Email Queue record is missing"),
					}
				)
			elif queue.status == "Sent":
				updates.update({"status": "Completed", "custom_delivery_status": "Sent"})
			elif queue.status == "Error":
				updates.update(
					{
						"status": "Completed",
						"custom_delivery_status": "Failed",
						"custom_error_message": queue.error,
					}
				)
		if row.get("read_by_recipient_on"):
			updates.update(
				{
					"custom_opened": 1,
					"custom_opened_on": row.read_by_recipient_on,
				}
			)
		elif row.custom_communication:
			communication = communications_by_name.get(row.custom_communication)
			if communication and communication.read_by_recipient and not row.custom_opened:
				updates.update(
					{
						"custom_opened": 1,
						"custom_opened_on": communication.read_by_recipient_on
						or now_datetime(),
					}
				)
		if updates:
			frappe.db.set_value(
				"Email Campaign",
				row.name,
				updates,
				update_modified=False,
			)
			affected_campaigns.add(row.campaign_name)
			if updates.get("custom_opened") and row.name in open_event_names:
				_log_event(
					"Opened",
					frappe._dict(row),
					communication=row.custom_communication,
					check_existing=False,
					check_table=False,
				)
	for campaign_name in affected_campaigns:
		refresh_campaign_metrics(campaign_name)


def _queued_delivery_status_updates(recipient):
	if (
		getattr(recipient, "custom_delivery_status", None) != "Queued"
		or not getattr(recipient, "custom_email_queue", None)
	):
		return {}
	queue_status = frappe.db.get_value(
		"Email Queue",
		recipient.custom_email_queue,
		"status",
	)
	if queue_status is None:
		return {
			"status": "Completed",
			"custom_delivery_status": "Failed",
			"custom_error_message": _("Email Queue record is missing"),
		}
	if queue_status == "Sent":
		return {"status": "Completed", "custom_delivery_status": "Sent"}
	if queue_status == "Error":
		return {
			"status": "Completed",
			"custom_delivery_status": "Failed",
			"custom_error_message": frappe.db.get_value(
				"Email Queue",
				recipient.custom_email_queue,
				"error",
			),
		}
	return {}


def refresh_campaign_metrics(campaign_name):
	if not frappe.db.exists("Campaign", campaign_name):
		return {}
	base = {"campaign_name": campaign_name}
	counts = {
		"custom_queued_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_delivery_status": "Queued"},
		),
		"custom_sent_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_delivery_status": "Sent"},
		),
		"custom_failed_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_delivery_status": "Failed"},
		),
		"custom_opened_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_opened": 1},
		),
		"custom_clicked_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_clicked": 1},
		),
		"custom_replied_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_replied": 1},
		),
		"custom_unsubscribed_count": frappe.db.count(
			"Email Campaign",
			{**base, "custom_unsubscribed": 1},
		),
	}
	frappe.db.set_value("Campaign", campaign_name, counts, update_modified=False)
	remaining = frappe.db.count(
		"Email Campaign",
		{
			**base,
			"custom_delivery_status": [
				"in",
				["Planned", "Processing", "Queued"],
			],
		},
	)
	status = frappe.db.get_value("Campaign", campaign_name, "custom_broadcast_status")
	if not remaining and status in ("Scheduled", "Sending", "Paused"):
		final_status = "Failed" if counts["custom_failed_count"] else "Completed"
		frappe.db.set_value(
			"Campaign",
			campaign_name,
			"custom_broadcast_status",
			final_status,
		)
	return counts


@frappe.whitelist(methods=["POST"])
def send_campaign_test(campaign_name, recipient, sample_lead):
	recipient = str(recipient or "").strip()
	validate_email_address(recipient, throw=True)
	if any(character in recipient for character in (",", ";", "\n", "\r")):
		frappe.throw(_("Send a test to one email address at a time"))
	from finbyzreach.email_template_builder.api import _check_test_email_rate_limit

	_check_test_email_rate_limit()
	campaign = frappe.get_doc("Campaign", campaign_name)
	campaign.check_permission("email")
	if not _is_email_broadcast(campaign):
		frappe.throw(_("This Campaign is not an Email Campaign Studio broadcast"))
	exclusion_reason = test_recipient_exclusion(
		recipient, campaign.custom_subscription_topic
	)
	if exclusion_reason:
		frappe.throw(
			_("Test email blocked by recipient suppression: {0}").format(exclusion_reason)
		)
	lead = frappe.get_doc("Lead", sample_lead)
	lead.check_permission("read")
	frozen = campaign.custom_broadcast_status != "Draft"
	if frozen and not (
		campaign.custom_snapshot_subject and campaign.custom_snapshot_html
	):
		frappe.throw(_("The frozen campaign content is unavailable. A test email cannot be sent safely."))
	if frozen:
		snapshot = frappe._dict(
			mode=campaign.custom_template_mode or "Standard",
			subject=campaign.custom_snapshot_subject,
			html=campaign.custom_snapshot_html,
		)
	else:
		snapshot = get_campaign_snapshot(
			campaign.custom_email_template,
			campaign.custom_subject_override,
		)
	test_params = {"is_test": "1", "campaign": campaign.name}
	if lead and hasattr(lead, "name"):
		test_params["lead"] = lead.name
	preview_url = get_url(f"/view_email?{get_signed_params(test_params)}")

	rendered = render_campaign_snapshot(
		snapshot.subject,
		snapshot.html,
		lead,
		extra_context={"email_preview_url": preview_url},
	)
	html = decorate_campaign_links(rendered.html, campaign, "test", track_clicks=0)
	queue = frappe.sendmail(
		recipients=[recipient],
		sender=_sender(campaign),
		reply_to=campaign.custom_reply_to or None,
		subject=f"[TEST] {rendered.subject}",
		content=html,
		reference_doctype="Campaign",
		reference_name=campaign.name,
		raw_html=snapshot.mode == "Visual",
		add_css=snapshot.mode != "Visual",
		add_unsubscribe_link=0,
	)
	return {"status": "queued", "email_queue": queue.name if queue else None}


@frappe.whitelist()
def preview_campaign_audience_api(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name)
	campaign.check_permission("read")
	return preview_campaign_audience(campaign)


@frappe.whitelist(methods=["POST"])
def refresh_campaign_metrics_api(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name)
	campaign.check_permission("write")
	return refresh_campaign_metrics(campaign.name)


@frappe.whitelist(allow_guest=True, methods=["GET"])
def track_marketing_click(campaign_recipient=None, url=None):
	if not url or urlparse(url).scheme not in ("http", "https") or not urlparse(url).netloc:
		frappe.local.response["http_status_code"] = 400
		return _("Invalid URL")
	if not frappe.in_test and not verify_request():
		frappe.local.response["http_status_code"] = 403
		return _("Invalid tracking signature")
	if campaign_recipient and frappe.db.exists("Email Campaign", campaign_recipient):
		recipient = frappe.get_doc("Email Campaign", campaign_recipient, for_update=True)
		now = now_datetime()
		updates = _queued_delivery_status_updates(recipient)
		updates.update({
			"custom_clicked": 1,
			"custom_clicked_on": recipient.custom_clicked_on or now,
		})
		if not recipient.custom_opened:
			updates.update({"custom_opened": 1, "custom_opened_on": now})
		frappe.db.set_value(
			"Email Campaign",
			recipient.name,
			updates,
			update_modified=False,
		)
		if recipient.custom_communication:
			frappe.db.set_value(
				"Communication",
				recipient.custom_communication,
				{
					"delivery_status": "Clicked",
					"read_by_recipient": 1,
					"read_by_recipient_on": now,
				},
				update_modified=False,
			)
		_log_event(
			"Clicked",
			recipient,
			communication=recipient.custom_communication,
			url=url,
		)
		refresh_campaign_metrics(recipient.campaign_name)
		frappe.db.commit()
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = url


@frappe.whitelist(allow_guest=True, methods=["GET"])
def unsubscribe_marketing(**kwargs):
	query_string = getattr(frappe.request, "query_string", b"").decode("utf-8")
	url = f"/manage_subscriptions?{query_string}"
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = url

@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=60*10)
def update_subscription_preferences(campaign_recipient, email, unsubscribed_topics, signed_query_string=None, **kwargs):
	if frappe.in_test:
		pass
	elif not signed_query_string:
		frappe.throw(_("Invalid or expired link"), frappe.PermissionError)
	else:
		from frappe.utils.verified_command import _sign_message
		import hmac
		from urllib.parse import parse_qs

		signature_string = "&_signature="
		if signature_string not in signed_query_string:
			frappe.throw(_("Invalid or expired link"), frappe.PermissionError)
			
		params, given_signature = signed_query_string.split(signature_string)
		computed_signature = _sign_message(params)
		
		if not hmac.compare_digest(given_signature, computed_signature):
			frappe.throw(_("Invalid link signature"), frappe.PermissionError)
			
		parsed_params = parse_qs(params)
		if parsed_params.get("campaign_recipient", [""])[0] != campaign_recipient:
			frappe.throw(_("Invalid or expired link"), frappe.PermissionError)

	if not campaign_recipient or not frappe.db.exists("Email Campaign", campaign_recipient):
		frappe.throw(_("This campaign recipient could not be found."), frappe.DoesNotExistError)

	recipient = frappe.get_doc("Email Campaign", campaign_recipient, for_update=True)
	if email and _normalized_email(email) != recipient.custom_normalized_email:
		frappe.throw(_("Invalid email for this recipient"), frappe.PermissionError)

	if isinstance(unsubscribed_topics, str):
		unsubscribed_topics = frappe.parse_json(unsubscribed_topics)
	if not isinstance(unsubscribed_topics, list):
		unsubscribed_topics = []

	lead_name = recipient.recipient
	
	# new_unsubscribed_topics is exactly what the user selected in the UI
	new_unsubscribed_topics = unsubscribed_topics
	
	# Fetch currently unsubscribed topics directly from the DB
	current_unsubscribed_rows = frappe.db.get_all(
		"Unsubscribe Topic Multi Select", 
		filters={"parent": lead_name, "parentfield": "custom_unsubscribe_topics"},
		fields=["name", "subscription_topic"]
	)
	current_unsubscribed_topics = {row.subscription_topic for row in current_unsubscribed_rows}
	
	# Find topics to remove from unsubscribed list and topics to add
	topics_to_remove = current_unsubscribed_topics - set(new_unsubscribed_topics)
	topics_to_add = set(new_unsubscribed_topics) - current_unsubscribed_topics
	
	if topics_to_remove:
		frappe.db.delete("Unsubscribe Topic Multi Select", {
			"parent": lead_name,
			"parentfield": "custom_unsubscribe_topics",
			"subscription_topic": ("in", list(topics_to_remove))
		})
		
	for topic in topics_to_add:
		frappe.get_doc({
			"doctype": "Unsubscribe Topic Multi Select",
			"parent": lead_name,
			"parenttype": "Lead",
			"parentfield": "custom_unsubscribe_topics",
			"subscription_topic": topic
		}).db_insert()
	
	now = now_datetime()
	recipient_updates = _queued_delivery_status_updates(recipient)
	
	was_unsubscribed = cint(recipient.custom_unsubscribed)
	is_unsubscribed = (recipient.campaign_name and frappe.db.get_value("Campaign", recipient.campaign_name, "custom_subscription_topic") in unsubscribed_topics)
	
	if is_unsubscribed and not was_unsubscribed:
		recipient_updates.update({
			"custom_unsubscribed": 1,
			"custom_unsubscribed_on": recipient.custom_unsubscribed_on or now,
		})
	elif not is_unsubscribed and was_unsubscribed:
		recipient_updates.update({
			"custom_unsubscribed": 0,
		})
		
	if recipient_updates:
		frappe.db.set_value("Email Campaign", recipient.name, recipient_updates, update_modified=False)
		
	if is_unsubscribed and recipient.custom_communication:
		frappe.db.set_value(
			"Communication",
			recipient.custom_communication,
			"delivery_status",
			"Recipient Unsubscribed",
			update_modified=False,
		)
		
	if is_unsubscribed and not was_unsubscribed:
		_log_event("Unsubscribed", recipient, communication=recipient.custom_communication)
		
	refresh_campaign_metrics(recipient.campaign_name)
	
	return "success"


from frappe.email.doctype.email_queue.email_queue import QueueBuilder as _QueueBuilder
_original_get_unsubscribed_user_emails = _QueueBuilder.get_unsubscribed_user_emails


def get_unsubscribed_user_emails(self):
	"""Campaign broadcasts use per-topic unsubscribe (Lead.custom_unsubscribe_topics)
	as the sole suppression authority; skip Frappe's global/reference Email
	Unsubscribe list only for emails dispatched through unsubscribe_marketing,
	matching the exclusion logic in _current_recipient_exclusion.
	"""
	if self._unsubscribe_method == f"/api/method/{UNSUBSCRIBE_METHOD}":
		return []
	return _original_get_unsubscribed_user_emails(self)


def communication_after_insert(doc, method=None):
	if doc.communication_medium != "Email" or doc.sent_or_received != "Received":
		return
	parent_communication = doc.in_reply_to
	if not parent_communication and doc.message_id:
		parent_communication = frappe.db.get_value(
			"Communication",
			{
				"message_id": doc.message_id,
				"sent_or_received": "Sent",
			},
			"name",
		)
	if not parent_communication:
		return
	recipient_name = frappe.db.get_value(
		"Email Campaign",
		{
			"custom_communication": parent_communication,
		},
		"name",
	)
	if not recipient_name:
		return
	recipient = frappe.get_doc("Email Campaign", recipient_name)
	frappe.db.set_value(
		"Email Campaign",
		recipient.name,
		{
			"custom_replied": 1,
			"custom_replied_on": doc.creation or now_datetime(),
		},
		update_modified=False,
	)
	_log_event("Replied", recipient, communication=doc.name)
	refresh_campaign_metrics(recipient.campaign_name)
