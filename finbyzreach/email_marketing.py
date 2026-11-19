from __future__ import annotations

import hashlib
import hmac
import json
import re
from html import escape
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
from finbyzreach.subscription_preferences import is_subscribed, recipient_urls


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
from finbyzreach.consent import email_policy, consent_exclusion, suppressed_addresses

FEEDBACK_DELIVERY_STATUSES = ("Bounced", "Soft-Bounced", "Marked As Spam")
TERMINAL_DELIVERY_STATUSES = ("Sent", "Failed", "Skipped", "Cancelled", *FEEDBACK_DELIVERY_STATUSES)
REPEAT_UNITS = ("Minutes", "Hours", "Days")
MAX_AUDIENCE_FILTERS = 50
MAX_AUDIENCE_FILTER_GROUPS = 25
MAX_EXCLUDED_EMAIL_GROUPS = 50
SCHEDULER_RECIPIENT_INSERT_FLAG = "email_campaign_scheduler_recipient_insert"
# Mirror Frappe's Email Queue safety model at the campaign-release boundary:
# allow a short undo window, recover abandoned work after the core retry window,
# and stop only when failures are both numerous and systemic.
DISPATCH_UNDO_WINDOW_SECONDS = 10
DEFAULT_DISPATCH_LIMIT = 200
DEFAULT_PENDING_QUEUE_LIMIT = 2000
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
	"custom_schedule_timezone",
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
	if "<!--email_open_check-->" not in html:
		parts.append('<div class="email-pixel"><!--email_open_check--></div>')
	if not parts:
		return html
	footer = '<div class="email-footer-container text-muted">' + "".join(parts) + "</div>"
	if re.search(r"</body\s*>", html, flags=re.IGNORECASE):
		return re.sub(r"</body\s*>", footer + "</body>", html, count=1, flags=re.IGNORECASE)
	return html + footer


def _insert_email_footer(html, footer):
	"""Keep compliance links inside a complete visual HTML document."""
	if re.search(r"</body\s*>", html, flags=re.IGNORECASE):
		return re.sub(r"</body\s*>", lambda match: footer + match.group(0), html, count=1, flags=re.IGNORECASE)
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
		audience_doctype = frappe.db.get_value("Campaign", self.campaign_name, "custom_audience_doctype") or "Lead"
		self.email_campaign_for = audience_doctype
		if not self.campaign_name or not self.recipient:
			frappe.throw(_("Campaign and recipient are required for a broadcast recipient"))
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
			email = self.custom_recipient_email or (frappe.db.get_value("Lead", self.recipient, "email_id") if audience_doctype == "Lead" else "")
			if not _normalized_email(email):
				frappe.throw(_("Recipient {0} has no valid email address").format(self.recipient))

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


SETTINGS_DOCTYPE = "Subscription Center Settings"
WINDOW_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


def default_sending_window():
	"""The one default sending window (rule 4.5): used by new emails and, as a starting point, workflows.

	Settings that were never saved read as empty, so each value has a fallback:
	off, 08:00-17:00, Monday to Friday. An end before the start is an overnight window.
	"""
	def value(fieldname):
		try:
			return frappe.db.get_single_value(SETTINGS_DOCTYPE, fieldname)
		except Exception:
			return None

	def clock(raw, fallback):
		text = str(raw or fallback)
		return text if text.count(":") == 2 else text + ":00"

	saved = any(value(f"default_send_{day}") is not None for day in WINDOW_DAYS)
	weekdays = [i for i, day in enumerate(WINDOW_DAYS) if cint(value(f"default_send_{day}"))] if saved else [0, 1, 2, 3, 4]
	return {
		"enabled": cint(value("default_window_enabled")),
		"start": clock(value("default_window_start"), "08:00:00"),
		"end": clock(value("default_window_end"), "17:00:00"),
		"weekdays": weekdays or [0, 1, 2, 3, 4],
		"timezone": "Europe/Zurich",
	}


def _system_zone():
	timezone_name = get_system_timezone() or "UTC"
	try:
		return ZoneInfo(timezone_name)
	except ZoneInfoNotFoundError:
		frappe.throw(_("The system timezone {0} is invalid").format(frappe.bold(timezone_name)))


def _campaign_zone(campaign):
	"""Keep sending weekdays and windows in the timezone chosen in Studio."""
	name = campaign.get("custom_schedule_timezone") or get_system_timezone()
	try:
		return ZoneInfo(name)
	except ZoneInfoNotFoundError:
		frappe.throw(_("The campaign timezone {0} is invalid").format(frappe.bold(name)))


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
	audience_doctype = doc.get("custom_audience_doctype") or "Lead"
	if audience_doctype not in ("Lead", "Contact", "Customer"):
		frappe.throw(_("Audience type must be Lead, Contact or Customer"))
	if audience_doctype == "Customer":
		if doc.get("custom_contact_mode") not in ("Primary Contact", "All Linked Contacts"):
			frappe.throw(_("Choose which Customer Contacts should receive the campaign"))
		if doc.get("custom_personalization_doctype") not in ("Customer", "Contact"):
			frappe.throw(_("Customer campaigns must personalize with Customer or Contact"))
	elif doc.get("custom_personalization_doctype") not in (None, "", audience_doctype):
		frappe.throw(_("Lead campaigns must use Lead personalization"))
	_system_zone()
	requested_status = doc.custom_broadcast_status or "Draft"
	if doc.is_new() and requested_status != "Draft":
		frappe.throw(_("New email broadcasts must start as Draft"))
	if require_ready and not doc.custom_subscription_topic:
		frappe.throw(_("Mailing Type is required for an Email Broadcast"))
	if doc.custom_subscription_topic and frappe.db.get_value(
		"Subscription Topic", doc.custom_subscription_topic, "disabled"
	):
		frappe.throw(_("Subscription Topic {0} is disabled").format(doc.custom_subscription_topic))
	if require_ready:
		if not email_policy(doc.custom_subscription_topic).available:
			frappe.throw(_("Select an active mailing type"))
		if doc.get("custom_content_topic") and frappe.db.get_value("Subscription Topic", doc.custom_content_topic, "category") != "Topic":
			frappe.throw(_("Select an active content topic"))
		if doc.get("custom_content_topic") and frappe.db.get_value("Subscription Topic", doc.custom_content_topic, "disabled"):
			frappe.throw(_("The selected content topic is disabled"))
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
		if get_time(doc.custom_window_start) == get_time(doc.custom_window_end):
			# An end before the start is an overnight window, e.g. 22:00 to 06:00 (rule 4.5).
			frappe.throw(_("The sending window start and end must be different"))

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
		personalization_doctype = doc.get("custom_personalization_doctype") or (doc.get("custom_audience_doctype") or "Lead")
		if reference_doctype and reference_doctype != personalization_doctype:
			frappe.throw(
				_("The selected template is configured for {0}, not {1}").format(reference_doctype, personalization_doctype)
			)
		doc.custom_template_reference_doctype = reference_doctype


def validate_lead_filters(filters_json, require_filters=False, audience_doctype="Lead"):
	from finbyzreach.segment_service import AUDIENCE_TYPES
	if audience_doctype not in AUDIENCE_TYPES:
		frappe.throw(_("Unsupported campaign audience"))
	try:
		filters = frappe.parse_json(filters_json or "[]")
	except (TypeError, ValueError):
		frappe.throw(_("Audience filters must contain valid JSON"))
	if not isinstance(filters, list):
		frappe.throw(_("Audience filters must be a list"))
	if len(filters) > MAX_AUDIENCE_FILTERS:
		frappe.throw(_("Use no more than {0} audience filters").format(MAX_AUDIENCE_FILTERS))
	if require_filters and not filters:
		frappe.throw(_("A dynamic segment needs at least one {0} filter").format(audience_doctype))

	meta = frappe.get_meta(audience_doctype)
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
		audience_doctype: standard_fields
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
			frappe.throw(_("Audience filters may target only {0} or its child-table fields").format(audience_doctype))
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


def validate_lead_filter_groups(filters_json, require_filters=False, audience_doctype="Lead"):
	"""Validate OR groups of audience filters.

	A legacy flat filter list remains valid and is treated as one AND group.
	"""
	from finbyzreach.segment_service import AUDIENCE_TYPES
	if audience_doctype not in AUDIENCE_TYPES:
		frappe.throw(_("Unsupported campaign audience"))
	try:
		groups = frappe.parse_json(filters_json or "[]")
	except (TypeError, ValueError):
		frappe.throw(_("Audience filter groups must contain valid JSON"))
	if not isinstance(groups, list):
		frappe.throw(_("Audience filter groups must be a list"))
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
		filters = frappe.parse_json(validate_lead_filters(json.dumps(group), audience_doctype=audience_doctype))
		filter_count += len(filters)
		if filter_count > MAX_AUDIENCE_FILTERS:
			frappe.throw(_("Use no more than {0} audience filters").format(MAX_AUDIENCE_FILTERS))
		normalized.append(filters)
	if require_filters and not normalized:
		frappe.throw(_("A dynamic segment needs at least one {0} filter group").format(audience_doctype))
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


def _lead_names_from_filters(filters_json, require_filters=False, audience_doctype="Lead"):
	normalized = validate_lead_filters(filters_json, require_filters=require_filters, audience_doctype=audience_doctype)
	filters = frappe.parse_json(normalized)
	if not filters:
		return []
	names = frappe.get_list(
		audience_doctype,
		filters=filters,
		pluck="name",
		distinct=True,
		limit=0,
		order_by="name asc",
	)
	return names


def _lead_names_from_filter_groups(filters_json, require_filters=False, audience_doctype="Lead"):
	groups = frappe.parse_json(validate_lead_filter_groups(filters_json, require_filters=require_filters, audience_doctype=audience_doctype))
	names = set()
	for group in groups:
		if (len(group) == 1 and group[0][1:3] == ["name", "in"]
			and isinstance(group[0][3], list) and len(group[0][3]) == 2
			and group[0][3][0] in ("#STATIC_SEGMENT#", "#REACH_SEGMENT#")):
			from finbyzreach.segment_service import member_names
			segment = frappe.get_doc("Reach Segment", group[0][3][1])
			segment.check_permission("read")
			from finbyzreach.segments import require_ready
			require_ready(segment)
			if segment.get("archived"):
				frappe.throw(_("Archived segments cannot be used for mailings"))
			if (segment.get("audience_doctype") or "Lead") != audience_doctype:
				frappe.throw(_("Selected segment targets a different audience type"))
			names.update(member_names(segment))
		else:
			names.update(_lead_names_from_filters(json.dumps(group), audience_doctype=audience_doctype))
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


def _reference_unsubscribed_pairs(lead_names, audience_doctype="Lead"):
	result = set()
	for names in _chunks(lead_names):
		for row in frappe.get_all(
			"Email Unsubscribe",
			filters={
				"reference_doctype": audience_doctype,
				"reference_name": ["in", names],
			},
			fields=["reference_name", "email"],
			limit_page_length=0,
		):
			if normalized := _normalized_email(row.email):
				result.add((row.reference_name, normalized))
	return result


def test_recipient_exclusion(email, subscription_topic=None, audience_doctype="Lead"):
	"""Return a suppression reason when a campaign test address is opted out."""
	normalized_email = _normalized_email(email)
	if not normalized_email:
		return _("Missing or invalid email")
	if not subscription_topic:
		# Hard bounces and spam complaints block every email, typed or not (rule 4.2).
		blocks = suppressed_addresses([normalized_email])
		if normalized_email in blocks:
			return _(blocks[normalized_email])
	if subscription_topic:
		policy = email_policy(subscription_topic)
		# EM-28: a test goes to a reviewer, not to the audience. An explicit opt-out, bounce or
		# spam complaint blocks it; a missing or pending subscription does not.
		status = frappe.db.get_value("Email Subscription Preference", {"email": normalized_email, "subscription_topic": subscription_topic}, "status")
		if status == "Unsubscribed" and cint(policy.consent_required):
			return _("Unsubscribed from {0}").format(subscription_topic)
		reason = consent_exclusion(normalized_email, subscription_topic, policy=policy, status="Subscribed", status_loaded=True)
		if reason:
			return reason
		if not cint(policy.consent_required):
			return None

	if normalized_email in _globally_unsubscribed_emails([normalized_email]):
		return _("Globally unsubscribed")

	if audience_doctype == "Customer":
		contact_names = set(frappe.get_all("Contact Email", filters={"email_id": normalized_email}, pluck="parent", limit_page_length=0))
		contact_names.update(frappe.get_all("Contact", filters={"email_id": normalized_email}, pluck="name", limit_page_length=0))
		if contact_names and frappe.db.exists("Contact", {"name": ["in", list(contact_names)], "unsubscribed": 1}):
			return _("Contact unsubscribed")
		if contact_names:
			contact_optouts = _reference_unsubscribed_pairs(contact_names, "Contact")
			if any((name, normalized_email) in contact_optouts for name in contact_names):
				return _("Unsubscribed from Customer or Contact emails")
			customer_names = set(frappe.get_all("Dynamic Link", filters={
				"parenttype": "Contact", "parent": ["in", list(contact_names)],
				"link_doctype": "Customer",
			}, pluck="link_name", limit_page_length=0))
			customer_optouts = _reference_unsubscribed_pairs(customer_names, "Customer")
			if any((name, normalized_email) in customer_optouts for name in customer_names):
				return _("Unsubscribed from Customer or Contact emails")
		return None
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
	if any(unsubscribed_email == normalized_email for _, unsubscribed_email in _reference_unsubscribed_pairs(lead_names)):
		return _("Unsubscribed from Lead emails")
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
	if campaign.get("custom_audience_doctype") == "Customer":
		from finbyzreach.customer_campaign import resolve_customer_audience
		return resolve_customer_audience(campaign)
	audience_doctype = campaign.get("custom_audience_doctype") or "Lead"
	include_leads = set(campaign.get("studio_include_leads") or [])
	if not include_leads:
		include_leads.update(
			_lead_names_from_filter_groups(campaign.get("custom_lead_filters_json"), require_filters=True, audience_doctype=audience_doctype)
		)
	exclude_leads = set(campaign.get("studio_exclude_leads") or [])
	if not exclude_leads and campaign.get("custom_exclude_filters_json"):
		exclude_leads.update(
			_lead_names_from_filter_groups(campaign.get("custom_exclude_filters_json"), audience_doctype=audience_doctype)
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
				audience_doctype,
				filters={"name": ["in", names]},
				fields=["name", "email_id", "status", "unsubscribed"] + (["disabled"] if audience_doctype == "Lead" else []),
				limit=0,
			)
		)
	rows_by_name = {row.name: row for row in rows}
	linked_unsubscribed = _linked_unsubscribed_leads(include_leads) if audience_doctype == "Lead" else set()
	normalized_by_lead = {
		name: _normalized_email(rows_by_name.get(name).email_id if rows_by_name.get(name) else "")
		for name in include_leads
	}
	mailing_type = campaign.get("custom_subscription_topic")
	policy = email_policy(mailing_type)
	blocks = suppressed_addresses(normalized_by_lead.values())
	preference_rows = []
	if mailing_type:
		for emails in _chunks(list(set(normalized_by_lead.values()) - {""})):
			preference_rows.extend(frappe.get_all(
				"Email Subscription Preference",
				filters={"email": ["in", emails]},
				fields=["email", "subscription_topic", "status"],
				limit_page_length=0,
			))
	preference_statuses = {(row.email, row.subscription_topic): row.status for row in preference_rows}
	global_unsubscribed = _globally_unsubscribed_emails(
		{email for email in normalized_by_lead.values() if email}
	)
	reference_unsubscribed = _reference_unsubscribed_pairs(include_leads, audience_doctype)
	topic_unsubscribed = set()
	topic_unsubscribed_emails = {
		row.email for row in preference_rows
		if row.subscription_topic == mailing_type and row.status == "Unsubscribed"
	}
	seen_emails = set()
	result = []
	for lead_name in sorted(include_leads):
		lead = rows_by_name.get(lead_name)
		email = lead.email_id if lead else ""
		normalized = normalized_by_lead.get(lead_name) or ""
		reason = None
		policy_reason = consent_exclusion(normalized, mailing_type, policy=policy, status=preference_statuses.get((normalized, mailing_type)), status_loaded=True, suppressions=blocks) if mailing_type else None
		if not lead:
			reason = "Lead unavailable"
		elif lead_name in exclude_leads:
			reason = "Excluded by exclusion filters or segments"
		elif cint(lead.disabled):
			reason = "Lead disabled"
		elif cint(policy.consent_required) and (cint(lead.unsubscribed)):
			reason = "Lead unsubscribed"
		elif cint(policy.consent_required) and (lead.status == "Do Not Contact"):
			reason = "Do Not Contact"
		elif cint(policy.consent_required) and (lead_name in linked_unsubscribed):
			reason = "Linked Contact unsubscribed"
		elif not normalized:
			reason = "Missing or invalid email"
		elif normalized in blocks:
			reason = blocks[normalized]
		elif normalized in exclude_emails:
			reason = "Excluded by Email Group"
		elif cint(policy.consent_required) and (normalized in global_unsubscribed):
			reason = "Globally unsubscribed"
		elif cint(policy.consent_required) and ((lead_name, normalized) in reference_unsubscribed):
			reason = "Unsubscribed from Lead emails"
		elif policy_reason:
			reason = policy_reason
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


def window_allows(local_dt, allowed_days, window_start=None, window_end=None):
	"""True when a local datetime may send. An end before the start is an overnight
	window: hours after midnight belong to the evening the window opened, so the
	weekday check uses that evening's day (22:00-06:00 on Friday includes Sat 03:00)."""
	if window_start is None or window_end is None:
		return local_dt.weekday() in allowed_days
	moment = local_dt.time().replace(tzinfo=None)
	if window_start < window_end:
		return local_dt.weekday() in allowed_days and window_start <= moment <= window_end
	if moment >= window_start:
		return local_dt.weekday() in allowed_days
	if moment <= window_end:
		return (local_dt - timedelta(days=1)).weekday() in allowed_days
	return False


def _next_valid_slot(value, campaign, timezone):
	allowed_days = _selected_weekdays(campaign)
	restricted = cint(campaign.custom_restrict_sending_window)
	window_start = get_time(campaign.custom_window_start) if restricted else None
	window_end = get_time(campaign.custom_window_end) if restricted else None
	value = _normalize_local_datetime(value, timezone)
	if window_allows(value, allowed_days, window_start, window_end):
		return value
	if window_start is None:
		# No time window: the next allowed weekday at the same time of day.
		for days in range(1, 8):
			candidate = _normalize_local_datetime((value + timedelta(days=days)).replace(second=0, microsecond=0), timezone)
			if candidate.weekday() in allowed_days:
				return candidate
		frappe.throw(_("Could not calculate a valid sending slot"))
	# Otherwise the next time the window opens on an allowed weekday.
	opening = value.replace(hour=window_start.hour, minute=window_start.minute, second=0, microsecond=0)
	if opening <= value:
		opening += timedelta(days=1)
	for _unused in range(15):
		if opening.weekday() in allowed_days:
			return _normalize_local_datetime(opening, timezone)
		opening += timedelta(days=1)
	frappe.throw(_("Could not calculate a valid sending slot"))


def calculate_batch_slots(campaign, batch_count, start_local=None):
	system_zone = _system_zone()
	campaign_zone = _campaign_zone(campaign)
	if start_local is None:
		start_local = get_datetime(campaign.custom_start_on)
	if start_local.tzinfo is None:
		start_local = start_local.replace(tzinfo=system_zone)
	current = _next_valid_slot(start_local.astimezone(campaign_zone), campaign, campaign_zone)
	interval = _interval(campaign)
	slots = []
	for index in range(batch_count):
		if index:
			current = _next_valid_slot(current + interval, campaign, campaign_zone)
		# Datetime fields are stored in the system timezone. Weekdays and
		# optional sending hours remain local to the campaign's timezone.
		slots.append(current.astimezone(system_zone).replace(tzinfo=None))
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


MAX_ATTACHMENT_BYTES = 12 * 1024 * 1024  # EM-18: all attachments of one email together
MAX_ATTACHMENT_FILES = 10


# EM-18: Studio marks the files it adds for the email. Files added in the Campaign form
# sidebar have no mark, so they stay internal and never go to recipients.
MAIL_ATTACHMENT_FIELD = "mail_attachment"


def campaign_attachment_files(campaign_name):
	"""Files Studio attached to a campaign for the email, oldest first (EM-18)."""
	if not campaign_name:
		return []
	return frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": "Campaign",
			"attached_to_name": campaign_name,
			"attached_to_field": MAIL_ATTACHMENT_FIELD,
			"is_folder": 0,
		},
		fields=["name", "file_name", "file_size", "file_url", "is_private"],
		order_by="creation asc",
		limit_page_length=0,
	)


def check_attachment_limit(files):
	"""Throw when the files together are over 12 MB or there are too many of them."""
	files = list(files or [])
	if len(files) > MAX_ATTACHMENT_FILES:
		frappe.throw(_("Attach at most {0} files to one email.").format(MAX_ATTACHMENT_FILES), title=_("Too many attachments"))
	total = sum(cint(row.get("file_size")) for row in files)
	if total > MAX_ATTACHMENT_BYTES:
		frappe.throw(
			_("The attachments are {0} MB together. The limit is {1} MB for one email.").format(
				round(total / 1048576, 1), MAX_ATTACHMENT_BYTES // 1048576
			),
			title=_("Attachments too large"),
		)
	return total


def studio_attachment_rows(file_names, campaign_name=None):
	"""Return the File rows a user may send with a campaign email, or throw.

	A file qualifies when the user uploaded it and it is not attached to any document yet,
	or when Studio already attached it to this campaign for the email.
	"""
	names = list(dict.fromkeys(str(name).strip() for name in (file_names or []) if str(name or "").strip()))
	rows = []
	for name in names:
		row = frappe.db.get_value(
			"File",
			name,
			["name", "file_name", "file_size", "attached_to_doctype", "attached_to_name", "attached_to_field", "owner", "is_folder"],
			as_dict=True,
		)
		if not row or row.is_folder:
			frappe.throw(_("Attachment {0} was not found.").format(name))
		if not _is_studio_attachment(row, campaign_name):
			frappe.throw(
				_("Attachment {0} cannot be sent. Upload the file in Studio to attach it to this email.").format(row.file_name or name),
				frappe.PermissionError,
			)
		rows.append(row)
	check_attachment_limit(rows)
	return rows


def _is_studio_attachment(row, campaign_name):
	if campaign_name and (row.attached_to_doctype, row.attached_to_name, row.attached_to_field) == ("Campaign", campaign_name, MAIL_ATTACHMENT_FIELD):
		return True
	return not row.attached_to_doctype and not row.attached_to_name and row.owner == frappe.session.user


def set_campaign_attachments(campaign, file_names):
	"""Make the listed uploaded files the campaign's attachments, and drop removed ones (EM-18)."""
	rows = studio_attachment_rows(file_names, campaign.name)
	keep = {row.name for row in rows}
	for existing in campaign_attachment_files(campaign.name):
		if existing.name not in keep:
			frappe.delete_doc("File", existing.name, ignore_permissions=True)
	for row in rows:
		if (row.attached_to_doctype, row.attached_to_name) != ("Campaign", campaign.name):
			frappe.db.set_value(
				"File",
				row.name,
				{"attached_to_doctype": "Campaign", "attached_to_name": campaign.name, "attached_to_field": MAIL_ATTACHMENT_FIELD},
				update_modified=False,
			)
	return [{"name": row.name, "file_name": row.file_name, "file_size": cint(row.file_size)} for row in rows]


def _mail_attachments(campaign_name):
	return [{"fid": row.name} for row in campaign_attachment_files(campaign_name)]


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
	audience_doctype = campaign.get("custom_audience_doctype") or "Lead"
	return {
		"doctype": "Email Campaign",
		"campaign_name": campaign.name,
		"status": "Scheduled" if row.eligible else "Completed",
		"start_date": getdate(scheduled_at or campaign.custom_start_on),
		"end_date": getdate(scheduled_at or campaign.custom_start_on),
		"email_campaign_for": audience_doctype,
		"recipient": row.lead,
		"custom_contact": row.get("contact") or (row.lead if audience_doctype == "Contact" else None),
		"custom_delivery_status": delivery_status,
		"custom_scheduled_at": scheduled_at,
		"custom_batch_number": batch_number,
		"custom_recipient_email": row.email,
		"custom_normalized_email": row.normalized_email,
		"custom_excluded_reason": row.reason,
		"custom_topic_unsubscribed": cint(row.get("topic_unsubscribed")),
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
    from finbyzreach.campaign_preparation import process
    try:
        return process(campaign_name)
    except Exception:
        frappe.db.rollback()
        frappe.log_error(title=f"Campaign Scheduling Failed: {campaign_name}", message=frappe.get_traceback())
        frappe.db.set_value("Campaign", campaign_name, "custom_queued", 0, update_modified=False)
        frappe.db.commit()
        raise


def validate_schedule_preflight(campaign, eligible_count=None):
	"""Check predictable scheduling failures before Studio enqueues work.

	The worker repeats this check because related records may change while it waits.
	"""
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status != "Draft":
		frappe.throw(_("Only a Draft broadcast can be scheduled"))
	if frappe.db.exists("Email Campaign", {"campaign_name": campaign.name}):
		frappe.throw(
			_("This campaign already has delivery history and cannot be scheduled again. Retry failed recipients or create a new campaign.")
		)
	validate_campaign(campaign, require_ready=True, skip_queued_check=True)
	audience_doctype = campaign.get("custom_audience_doctype") or "Lead"
	validate_lead_filter_groups(campaign.custom_lead_filters_json, require_filters=True, audience_doctype=audience_doctype)
	validate_lead_filter_groups(campaign.custom_exclude_filters_json, audience_doctype=audience_doctype)
	validate_excluded_email_groups(campaign.custom_exclude_email_groups_json)
	calculate_batch_slots(campaign, 1)
	if eligible_count is not None and cint(eligible_count) <= 0:
		frappe.throw(_("No eligible recipients remain after exclusions"))
	snapshot = get_campaign_snapshot(
		campaign.custom_email_template,
		campaign.custom_subject_override,
		preheader_override=campaign.get("custom_preheader_override"),
	)
	personalization_doctype = campaign.get("custom_personalization_doctype") or audience_doctype
	if snapshot.reference_doctype and snapshot.reference_doctype != personalization_doctype:
		frappe.throw(_("Campaign templates must use {0} personalization").format(personalization_doctype))
	from finbyzreach.consent import UNSUBSCRIBE_MISSING, email_has_unsubscribe
	if campaign.custom_subscription_topic != "Transactional" and not email_has_unsubscribe(snapshot.html):
		frappe.throw(_(UNSUBSCRIBE_MISSING), title=_("Unsubscribe link missing"))
	check_attachment_limit(campaign_attachment_files(campaign.name))
	from finbyzreach import ab_test
	ab_test.validate(campaign)
	return snapshot


def _schedule_campaign_internal(campaign_name):
    # Compatibility entry point for callers using the previous scheduler.
    from finbyzreach.campaign_preparation import process
    return process(campaign_name)


@frappe.whitelist(methods=["POST"])
def pause_campaign(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status not in ("Preparing Audience", "Scheduled", "Sending"):
		frappe.throw(_("Only a preparing, scheduled or sending campaign can be paused"))
	campaign.db_set("custom_broadcast_status", "Paused")
	return {"message": _("Campaign paused. Already queued emails may still be sent.")}


@frappe.whitelist(methods=["POST"])
def resume_campaign(campaign_name):
	campaign = frappe.get_doc("Campaign", campaign_name, for_update=True)
	campaign.check_permission("write")
	campaign.check_permission("email")
	if campaign.custom_broadcast_status != "Paused":
		frappe.throw(_("Only a paused campaign can be resumed"))
	from finbyzreach.campaign_preparation import STAGING
	if frappe.db.table_exists(STAGING) and frappe.db.count(STAGING, {"campaign": campaign.name}):
		campaign.db_set("custom_broadcast_status", "Preparing Audience")
		frappe.enqueue("finbyzreach.email_marketing.schedule_campaign", campaign_name=campaign.name,
			queue="long", enqueue_after_commit=True)
		return {"message": _("Audience preparation resumed")}
	planned_filters = {"campaign_name": campaign.name, "custom_delivery_status": "Planned"}
	if campaign.get("custom_ab_status") == "Testing":
		# EM-30: the rest of the audience keeps waiting for the winner.
		planned_filters["custom_ab_phase"] = ["!=", "Rest"]
	planned = frappe.get_all(
		"Email Campaign",
		filters=planned_filters,
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
	if campaign.custom_broadcast_status not in ("Preparing Audience", "Scheduled", "Sending", "Paused"):
		frappe.throw(_("This campaign cannot be cancelled"))
	recipient = frappe.qb.DocType("Email Campaign")
	(
		frappe.qb.update(recipient)
		.set(recipient.custom_delivery_status, "Cancelled")
		.set(recipient.status, "Completed")
		.where(recipient.campaign_name == campaign.name)
		.where(recipient.custom_delivery_status.isin(["Planned", "Processing"]))
	).run()
	from finbyzreach.campaign_preparation import STAGING
	frappe.db.delete(STAGING, {"campaign": campaign.name})
	frappe.db.set_value("Campaign", campaign.name, "custom_queued", 0, update_modified=False)
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
		if CLICK_METHOD in href or UNSUBSCRIBE_METHOD in href or "view_email" in href or urlparse(href).path == "/manage_subscriptions":
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
			"lead": recipient.recipient if recipient.email_campaign_for == "Lead" else None,
			"contact": recipient.recipient if recipient.email_campaign_for == "Contact" else recipient.get("custom_contact"),
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
	policy = email_policy(campaign.custom_subscription_topic)
	reason = consent_exclusion(recipient.custom_recipient_email, campaign.custom_subscription_topic, policy=policy)
	if reason:
		return reason
	if cint(policy.consent_required) and cint(recipient.custom_unsubscribed):
		return _("Recipient unsubscribed")

	if recipient.email_campaign_for == "Customer":
		from finbyzreach.customer_campaign import current_customer_exclusion
		return current_customer_exclusion(recipient, campaign)
	audience_doctype = recipient.email_campaign_for or "Lead"
	lead = frappe.db.get_value(
		audience_doctype,
		recipient.recipient,
		["unsubscribed", "status"] + (["disabled"] if audience_doctype == "Lead" else []),
		as_dict=True,
	)
	if not lead:
		return _("Lead unavailable")
	if cint(lead.disabled):
		return _("Lead disabled")
	if cint(policy.consent_required) and (cint(lead.unsubscribed)):
		return _("Lead unsubscribed")
	if cint(policy.consent_required) and (lead.status == "Do Not Contact"):
		return _("Do Not Contact")
	if cint(policy.consent_required) and (audience_doctype == "Lead" and recipient.recipient in _linked_unsubscribed_leads([recipient.recipient])):
		return _("Linked Contact unsubscribed")
	normalized_email = _normalized_email(recipient.custom_recipient_email)
	if cint(policy.consent_required) and (normalized_email in _globally_unsubscribed_emails([normalized_email])):
		return _("Globally unsubscribed")
	if cint(policy.consent_required) and ((recipient.recipient, normalized_email) in _reference_unsubscribed_pairs([recipient.recipient], audience_doctype)):
		return _("Unsubscribed from Lead emails")
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
	audience_doctype = recipient.email_campaign_for or "Lead"
	party = frappe.get_doc(audience_doctype, recipient.recipient)
	contact = (
		frappe.get_doc("Contact", recipient.custom_contact)
		if audience_doctype == "Customer"
		else party if audience_doctype == "Contact" else None
	)
	personalization_doctype = campaign.get("custom_personalization_doctype") or audience_doctype
	template_doc = contact if personalization_doctype == "Contact" else party
	preview_url = get_url(
		f"/view_email?{get_signed_params({'campaign_recipient': recipient.name})}"
	)
	compliance_urls = recipient_urls(recipient)
	from finbyzreach.consent import FOOTER_LABELS
	from finbyzreach.subscription_preferences import email_language
	footer_labels = FOOTER_LABELS.get(email_language(campaign.name)) or (_("Unsubscribe"), _("Email preference center"))
	from finbyzreach.ab_test import variant_content
	snapshot_subject, snapshot_html = variant_content(campaign, recipient)
	rendered = render_campaign_snapshot(
		snapshot_subject,
		snapshot_html,
		template_doc,
		extra_context={"email_preview_url": preview_url, "customer": party if audience_doctype == "Customer" else None, "contact": contact, **compliance_urls},
	)
	present_links = {str(link.get("href") or "") for link in BeautifulSoup(rendered.html, "html.parser").find_all("a")}
	html = decorate_campaign_links(rendered.html, campaign, recipient.name)
	missing_links = []
	if campaign.custom_subscription_topic != "Transactional" and compliance_urls["unsubscribe_url"] not in present_links:
		missing_links.append(
			f'<a href="{escape(compliance_urls["unsubscribe_url"], quote=True)}">'
			f'{escape(campaign.get("custom_unsubscribe_label") or footer_labels[0])}</a>'
		)
	if campaign.custom_subscription_topic != "Transactional" and compliance_urls["email_preference_center_url"] not in present_links:
		missing_links.append(
			f'<a href="{escape(compliance_urls["email_preference_center_url"], quote=True)}">'
			f'{escape(campaign.get("custom_preference_label") or footer_labels[1])}</a>'
		)
	if missing_links:
		footer = f'<div class="email-preferences" style="padding:20px;text-align:center;font-size:12px">{" &nbsp;|&nbsp; ".join(missing_links)}</div>'
		html = _insert_email_footer(html, footer)
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
			doctype=audience_doctype,
			name=party.name,
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
		if contact and audience_doctype == "Customer":
			communication.append("timeline_links", {"link_doctype": "Contact", "link_name": contact.name})
		communication.save(ignore_permissions=True)
	queue = frappe.sendmail(
		send_priority=0,
		recipients=[recipient.custom_recipient_email],
		sender=_sender(campaign),
		reply_to=campaign.custom_reply_to or None,
		subject=rendered.subject,
		content=delivery_html,
		reference_doctype=audience_doctype,
		reference_name=party.name,
		communication=communication.name,
		send_after=recipient.custom_scheduled_at,
		add_unsubscribe_link=0,
		unsubscribe_method=f"/api/method/{UNSUBSCRIBE_METHOD}",
		unsubscribe_params={"campaign_recipient": recipient.name},
		raw_html=campaign.custom_template_mode == "Visual",
		add_css=campaign.custom_template_mode != "Visual",
		attachments=_mail_attachments(campaign.name) or None,
	)
	if not queue:
		frappe.throw(_("Frappe did not create an Email Queue record"))
	from finbyzreach.consent import add_list_headers
	if campaign.custom_subscription_topic != "Transactional":
		add_list_headers(queue, compliance_urls["unsubscribe_url"])
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
	# Bound processing, not campaign size. A pass must finish before the next
	# scheduler tick and leave capacity for ordinary CRM email.
	if frappe.are_emails_muted() or cint(frappe.db.get_default("suspend_email_queue")):
		return
	limit = max(1, min(cint(frappe.conf.get("marketing_dispatch_limit")) or DEFAULT_DISPATCH_LIMIT, 1000))
	queue_limit = max(limit, cint(frappe.conf.get("marketing_pending_queue_limit")) or DEFAULT_PENDING_QUEUE_LIMIT)
	pending = frappe.db.count("Email Queue", {"status": ["in", ["Not Sent", "Partially Sent", "Sending"]]})
	limit = min(limit, max(0, queue_limit - pending))
	if not limit:
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
		limit=limit,
	)
	affected_campaigns = set()
	failures_by_campaign = Counter()
	attempts_by_campaign = Counter()
	halted_campaigns = set()
	locked_campaigns = {}
	for row in rows:
		if row.campaign_name in halted_campaigns:
			continue
		savepoint = f"email_broadcast_{hashlib.md5(row.name.encode()).hexdigest()[:16]}"
		frappe.db.savepoint(savepoint)
		try:
			# This scheduler pass is one transaction. Lock each Campaign once while
			# this bounded group is handed to Frappe Email Queue.
			campaign = locked_campaigns.get(row.campaign_name)
			if campaign is None:
				campaign = frappe.get_doc("Campaign", row.campaign_name, for_update=True)
				locked_campaigns[row.campaign_name] = campaign
			if campaign.custom_broadcast_status not in ("Scheduled", "Sending"):
				continue
			recipient = frappe.get_doc("Email Campaign", row.name, for_update=True)
			if recipient.custom_delivery_status != "Planned":
				continue
			attempts_by_campaign[row.campaign_name] += 1
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
			batch_count = max(1, attempts_by_campaign[row.campaign_name])
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
	if len(rows) == limit and pending + len(rows) < queue_limit:
		# Continue in another transaction instead of waiting a full scheduler
		# interval for each chunk of a large campaign.
		frappe.enqueue("finbyzreach.email_marketing.dispatch_due_marketing_batches", queue="long",
			enqueue_after_commit=True, job_id=f"reach-dispatch:{rows[-1].name}", deduplicate=True)



def sync_marketing_email_statuses():
	# Select outcomes that can advance, so 500 stalled queue entries cannot
	# indefinitely hide completed recipients behind them.
	recipient_table = frappe.qb.DocType("Email Campaign")
	queue_table = frappe.qb.DocType("Email Queue")
	queued_rows = (
		frappe.qb.from_(recipient_table)
		.left_join(queue_table).on(queue_table.name == recipient_table.custom_email_queue)
		.select(*[recipient_table[field] for field in (
			"name", "campaign_name", "recipient", "email_campaign_for", "custom_email_queue",
			"custom_communication", "custom_opened", "custom_delivery_status",
		)])
		.where(recipient_table.custom_delivery_status == "Queued")
		.where(recipient_table.custom_email_queue.isnotnull())
		.where(queue_table.status.isin(["Sent", "Error"]) | queue_table.name.isnull())
		.orderby(recipient_table.modified).orderby(recipient_table.name)
		.limit(500).run(as_dict=True)
	)
	# Frappe records an open by updating Communication directly with db.set_value;
	# that does not run document hooks.  Join only Communications already marked
	# read so old unopened messages never occupy or starve this bounded scan.
	opened_rows = frappe.db.sql(
		"""
			select
				ec.name, ec.campaign_name, ec.recipient, ec.email_campaign_for, ec.custom_email_queue,
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
	# Provider integrations may update Communication after Email Queue has already
	# reached Sent. Reconcile those later outcomes in bounded batches as well.
	feedback_rows = frappe.db.sql(
		"""
			select ec.name, ec.campaign_name, ec.recipient, ec.email_campaign_for, ec.custom_email_queue,
				ec.custom_communication, ec.custom_opened, ec.custom_delivery_status,
				comm.delivery_status as communication_delivery_status
			from `tabEmail Campaign` ec
			inner join `tabCommunication` comm on comm.name = ec.custom_communication
			where ec.custom_delivery_status in ('Queued', 'Sent')
				and comm.delivery_status in ('Bounced', 'Soft-Bounced', 'Marked As Spam')
			order by comm.modified asc, ec.name asc
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
	for row in feedback_rows:
		if row.name in rows_by_name:
			rows_by_name[row.name].communication_delivery_status = row.communication_delivery_status
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
				fields=["name", "read_by_recipient", "read_by_recipient_on", "delivery_status"],
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
		communication = communications_by_name.get(row.custom_communication)
		feedback_status = row.get("communication_delivery_status") or (
			communication.delivery_status if communication else None
		)
		updates.update(_feedback_delivery_updates(feedback_status))
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


def _feedback_delivery_updates(delivery_status):
	if delivery_status not in FEEDBACK_DELIVERY_STATUSES:
		return {}
	return {"status": "Completed", "custom_delivery_status": delivery_status}


def _queued_delivery_status_updates(recipient):
	if (
		getattr(recipient, "custom_delivery_status", None) != "Queued"
		or not getattr(recipient, "custom_email_queue", None)
	):
		return {}
	if recipient.custom_communication:
		feedback_status = frappe.db.get_value(
			"Communication", recipient.custom_communication, "delivery_status"
		)
		feedback_updates = _feedback_delivery_updates(feedback_status)
		if feedback_updates:
			return feedback_updates
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
	if frappe.db.get_value("Campaign", campaign_name, "custom_audience_doctype") == "Customer":
		from finbyzreach.finbyzreach.page.email_campaign_studio.email_campaign_studio import send_test
		campaign = frappe.get_doc("Campaign", campaign_name)
		campaign.check_permission("email")
		return send_test({
			"source_campaign": campaign.name,
			"audience_doctype": "Customer",
			"contact_mode": campaign.custom_contact_mode,
			"personalization_doctype": campaign.custom_personalization_doctype,
			"email_template": campaign.custom_email_template,
			"email_account": campaign.custom_email_account,
			"campaign_title": campaign.campaign_name,
			"subscription_topic": campaign.custom_subscription_topic,
			"content_topic": campaign.get("custom_content_topic"),
			"subject_override": campaign.custom_subject_override,
			"sender_name": campaign.custom_sender_name,
			"reply_to": campaign.custom_reply_to,
		}, recipient, sample_lead)
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
			preheader_override=campaign.get("custom_preheader_override"),
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
		attachments=_mail_attachments(campaign.name) or None,
	)
	return {"status": "queued", "email_queue": queue.name if queue else None}


@frappe.whitelist(methods=["GET"])
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
		mark_campaign_metrics_dirty(recipient.campaign_name)
		frappe.db.commit()
	frappe.local.response["type"] = "redirect"
	frappe.local.response["location"] = url


@frappe.whitelist(allow_guest=True, methods=["GET", "POST"])
def unsubscribe_marketing(**kwargs):
	from finbyzreach.subscription_preferences import signed_recipient, unsubscribe

	if not frappe.form_dict.get("campaign_recipient"):
		frappe.throw(_("Invalid unsubscribe link"), frappe.PermissionError)
	raw = frappe.safe_decode(getattr(frappe.request, "query_string", b""))
	recipient, email = signed_recipient(frappe.form_dict.campaign_recipient, raw)
	topic = frappe.db.get_value("Campaign", recipient.campaign_name, "custom_subscription_topic")
	if not topic:
		frappe.throw(_("This campaign has no subscription type"))
	unsubscribe(email, topic)
	_mark_campaign_recipient_unsubscribed(recipient)
	# GET requests are rolled back by Frappe's transaction finalizer unless committed.
	frappe.db.commit()
	frappe.respond_as_web_page(_("Unsubscribed"), _("You have been unsubscribed from {0}.").format(topic), indicator_color="green")


def _mark_campaign_recipient_unsubscribed(recipient):
	if cint(recipient.custom_unsubscribed):
		return
	updates = _queued_delivery_status_updates(recipient)
	updates.update({"custom_unsubscribed": 1, "custom_unsubscribed_on": now_datetime()})
	frappe.db.set_value("Email Campaign", recipient.name, updates, update_modified=False)
	if recipient.custom_communication:
		frappe.db.set_value("Communication", recipient.custom_communication, "delivery_status", "Recipient Unsubscribed", update_modified=False)
	_log_event("Unsubscribed", recipient, communication=recipient.custom_communication)
	refresh_campaign_metrics(recipient.campaign_name)

@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=10, seconds=600)
def update_subscription_preferences(campaign_recipient, email, selected_topics, visible_topics, signed_query_string=None, **kwargs):
	from finbyzreach.subscription_preferences import save_selection, signed_recipient

	recipient, verified_email = signed_recipient(campaign_recipient, signed_query_string)
	if email and not hmac.compare_digest(_normalized_email(email), verified_email):
		frappe.throw(_("Invalid email for this recipient"), frappe.PermissionError)
	selected = frappe.parse_json(selected_topics) if isinstance(selected_topics, str) else selected_topics
	visible = frappe.parse_json(visible_topics) if isinstance(visible_topics, str) else visible_topics
	if not isinstance(selected, list) or not isinstance(visible, list):
		frappe.throw(_("Invalid subscription selection"), frappe.ValidationError)
	save_selection(verified_email, selected, visible)
	current_type = frappe.db.get_value("Campaign", recipient.campaign_name, "custom_subscription_topic")
	if current_type and current_type not in selected:
		_mark_campaign_recipient_unsubscribed(recipient)
	return "success"


from frappe.email.doctype.email_queue.email_queue import QueueBuilder as _QueueBuilder
_original_get_unsubscribed_user_emails = _QueueBuilder.get_unsubscribed_user_emails


def get_unsubscribed_user_emails(self):
	"""Campaign eligibility is checked by email and purpose before queueing.

	The queue's legacy reference-level list is bypassed for these campaign rows;
	global opt-outs are checked in preview and again at dispatch time.
	"""
	if self._unsubscribe_method in (f"/api/method/{UNSUBSCRIBE_METHOD}", "/api/method/finbyzreach.subscription_preferences.unsubscribe_address"):
		return []
	return _original_get_unsubscribed_user_emails(self)


def _is_campaign_recipient_reply(communication, recipient):
	"""A delivery notice can reference the sent message but is not a person's reply."""
	recipient_email = _normalized_email(recipient.custom_recipient_email)
	return bool(recipient_email and _normalized_email(communication.sender) == recipient_email)


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
	if not _is_campaign_recipient_reply(doc, recipient):
		return
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


def mark_campaign_metrics_dirty(campaign_name):
    # One set member per campaign coalesces a burst of tracking requests.
    frappe.db.after_commit.add(lambda: frappe.cache.sadd(f"reach:dirty-metrics:{frappe.local.site}", campaign_name))


def flush_dirty_campaign_metrics():
    key = f"reach:dirty-metrics:{frappe.local.site}"
    for _ in range(50):
        name = frappe.cache.spop(key)
        if not name:
            break
        if isinstance(name, bytes):
            name = name.decode()
        # Every popped item must be restored if the worker transaction rolls
        # back, including items refreshed successfully before a later failure.
        frappe.db.after_rollback.add(lambda name=name: frappe.cache.sadd(key, name))
        try:
            refresh_campaign_metrics(name)
        except Exception:
            frappe.cache.sadd(key, name)
            raise
