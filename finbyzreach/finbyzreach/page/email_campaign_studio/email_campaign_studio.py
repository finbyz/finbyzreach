from __future__ import annotations

import json
import math
from collections import Counter
from datetime import timedelta
from email.utils import formataddr

import frappe
from frappe import _
from frappe.query_builder.functions import Count
from frappe.utils import (
	cint,
	get_datetime,
	now_datetime,
	nowdate,
	slug,
	strip_html,
	validate_email_address,
)

from finbyzreach.email_template_builder.api import _check_test_email_rate_limit
from finbyzreach.email_template_builder.services import (
	get_campaign_snapshot,
	render_campaign_snapshot,
)
from finbyzreach import email_marketing


MAX_EXCLUSION_LISTS = 50
MAX_TOPIC_OPTOUT_SAMPLES = 25
MAX_AUDIENCE_HEALTH_PAGE_LENGTH = 1000
EDITABLE_BROADCAST_STATUSES = {"", "Draft"}


def _check_permission(ptype="create"):
	frappe.has_permission("Campaign", ptype=ptype, throw=True)
	frappe.has_permission("Lead", ptype="read", throw=True)


def _time_string(value):
	if not value:
		return ""
	if hasattr(value, "strftime"):
		return value.strftime("%H:%M:%S")
	return str(value)


def _parse_payload(payload):
	try:
		payload = frappe.parse_json(payload or {})
	except (TypeError, ValueError):
		frappe.throw(_("Campaign data must contain valid JSON"))
	if not isinstance(payload, dict):
		frappe.throw(_("Campaign data must be an object"))
	return frappe._dict(payload)


def _parse_json_list(value, label):
	try:
		value = frappe.parse_json(value or [])
	except (TypeError, ValueError):
		frappe.throw(_("{0} must contain valid JSON").format(label))
	if not isinstance(value, list):
		frappe.throw(_("{0} must be a list").format(label))
	result = []
	for item in value:
		item = str(item or "").strip()
		if item and item not in result:
			result.append(item)
	if len(result) > MAX_EXCLUSION_LISTS:
		frappe.throw(_("Select no more than {0} {1}").format(MAX_EXCLUSION_LISTS, label))
	return result


def _lead_names(filters_json):
	filters = frappe.parse_json(filters_json)
	if not filters:
		return []
	names = frappe.get_list(
		"Lead",
		filters=filters,
		pluck="name",
		distinct=True,
		order_by="name asc",
		limit=0,
	)
	return names


def _audience_context(
	filters, exclude_filters=None, exclude_email_groups=None, require_filters=True
):
	def filter_payload(value):
		return value if isinstance(value, str) else json.dumps(value or [])

	include_filters_json = email_marketing.validate_lead_filters(
		filter_payload(filters), require_filters=require_filters
	)
	exclude_filters_json = email_marketing.validate_lead_filters(
		filter_payload(exclude_filters)
	)
	email_groups = email_marketing.validate_excluded_email_groups(
		json.dumps(_parse_json_list(exclude_email_groups, _("blacklist email groups")))
	)
	return frappe._dict(
		include_filters_json=include_filters_json,
		exclude_filters_json=exclude_filters_json,
		email_groups=email_groups,
		include_leads=_lead_names(include_filters_json),
		exclude_leads=_lead_names(exclude_filters_json),
	)


def _resolved_studio_audience(context, subscription_topic=None):
	if not context.include_leads and not frappe.parse_json(context.include_filters_json or "[]"):
		return []
	transient_campaign = frappe._dict(
		studio_include_leads=context.include_leads,
		studio_exclude_leads=context.exclude_leads,
		custom_lead_filters_json=context.include_filters_json,
		custom_exclude_filters_json=context.exclude_filters_json,
		custom_exclude_email_groups_json=frappe.as_json(context.email_groups),
		custom_subscription_topic=subscription_topic,
	)
	return email_marketing.resolve_campaign_audience(transient_campaign)


def _lead_preview_rows(lead_names, limit):
	lead_names = list(dict.fromkeys(lead_names))[:limit]
	if not lead_names:
		return []
	return frappe.get_list(
		"Lead",
		filters={"name": ["in", lead_names]},
		fields=["name", "lead_name", "company_name", "email_id"],
		order_by="lead_name asc",
		limit=limit,
	)


def _frozen_recipient_preview_rows(recipients, limit):
	recipients = list(recipients or [])[:limit]
	if not recipients:
		return []
	lead_names = [row.recipient for row in recipients]
	leads = frappe.get_list(
		"Lead",
		filters={"name": ["in", lead_names]},
		fields=["name", "lead_name", "company_name"],
		limit=limit,
	)
	leads_by_name = {row.name: row for row in leads}
	return [
		frappe._dict(
			name=row.recipient,
			lead_name=(leads_by_name.get(row.recipient) or {}).get("lead_name")
			or row.recipient,
			company_name=(leads_by_name.get(row.recipient) or {}).get("company_name"),
			email_id=row.custom_recipient_email or "",
		)
		for row in recipients
	]


def _preview_response(
	resolved, subscription_topic=None, eligible_page=1, eligible_page_length=8
):
	reasons = Counter(row.reason for row in resolved if row.reason)
	eligible_names = [row.lead for row in resolved if row.eligible]
	page_length = min(
		max(cint(eligible_page_length) or 8, 1), MAX_AUDIENCE_HEALTH_PAGE_LENGTH
	)
	total_pages = (
		(len(eligible_names) + page_length - 1) // page_length if eligible_names else 0
	)
	page = max(cint(eligible_page) or 1, 1)
	if total_pages:
		page = min(page, total_pages)
	offset = (page - 1) * page_length
	samples = _lead_preview_rows(eligible_names[offset : offset + page_length], page_length)
	topic_reason = (
		_("Unsubscribed from topic {0}").format(subscription_topic)
		if subscription_topic
		else None
	)
	topic_unsubscribed_names = [
		row.lead
		for row in resolved
		if topic_reason
		and (row.get("topic_unsubscribed") or row.reason == topic_reason)
	]
	topic_unsubscribed_samples = _lead_preview_rows(
		topic_unsubscribed_names, MAX_TOPIC_OPTOUT_SAMPLES
	)
	return {
		"candidate_count": len(resolved),
		"eligible_count": sum(1 for row in resolved if row.eligible),
		"excluded_count": sum(1 for row in resolved if not row.eligible),
		"excluded_reasons": dict(reasons),
		"eligible_samples": samples,
		"eligible_page": page,
		"eligible_page_length": page_length,
		"eligible_total_pages": total_pages,
		"subscription_topic": subscription_topic or "",
		"topic_unsubscribed_count": len(topic_unsubscribed_names),
		"topic_unsubscribed_samples": topic_unsubscribed_samples,
		"topic_unsubscribed_more": max(
			0, len(topic_unsubscribed_names) - len(topic_unsubscribed_samples)
		),
	}


def _frozen_preview_response(campaign, eligible_page=1, eligible_page_length=8):
	"""Return the scheduled recipient snapshot instead of recalculating live Lead filters."""
	page_length = min(
		max(cint(eligible_page_length) or 8, 1), MAX_AUDIENCE_HEALTH_PAGE_LENGTH
	)
	eligible_count = cint(campaign.custom_eligible_count)
	total_pages = (eligible_count + page_length - 1) // page_length if eligible_count else 0
	page = max(cint(eligible_page) or 1, 1)
	if total_pages:
		page = min(page, total_pages)
	offset = (page - 1) * page_length
	recipients = frappe.get_all(
		"Email Campaign",
		filters={
			"campaign_name": campaign.name,
			"custom_batch_number": [">", 0],
		},
		fields=["recipient", "custom_recipient_email"],
		order_by="custom_batch_number asc, name asc",
		start=offset,
		page_length=page_length,
	)
	reason_rows = frappe.get_all(
		"Email Campaign",
		filters={
			"campaign_name": campaign.name,
			"custom_batch_number": 0,
			"custom_excluded_reason": ["is", "set"],
		},
		fields=["custom_excluded_reason", {"COUNT": "name", "as": "count"}],
		group_by="custom_excluded_reason",
		limit=0,
	)
	reasons = {row.custom_excluded_reason: cint(row.count) for row in reason_rows}
	topic_reason = (
		_("Unsubscribed from topic {0}").format(campaign.custom_subscription_topic)
		if campaign.custom_subscription_topic
		else ""
	)
	topic_names = []
	topic_count = 0
	if topic_reason:
		recipient_table = frappe.qb.DocType("Email Campaign")
		topic_count = cint(
			(
				frappe.qb.from_(recipient_table)
				.select(Count(recipient_table.name))
				.where(recipient_table.campaign_name == campaign.name)
				.where(
					(recipient_table.custom_excluded_reason == topic_reason)
					| (recipient_table.custom_unsubscribed == 1)
				)
			).run()[0][0]
		)
		topic_names = frappe.get_all(
			"Email Campaign",
			filters={
				"campaign_name": campaign.name,
			},
			or_filters={
				"custom_excluded_reason": topic_reason,
				"custom_unsubscribed": 1,
			},
			fields=["recipient", "custom_recipient_email"],
			order_by="custom_unsubscribed desc, name asc",
			limit=MAX_TOPIC_OPTOUT_SAMPLES + 1,
		)
	return {
		"candidate_count": cint(campaign.custom_candidate_count),
		"eligible_count": eligible_count,
		"excluded_count": cint(campaign.custom_excluded_count),
		"excluded_reasons": reasons,
		"eligible_samples": _frozen_recipient_preview_rows(recipients, page_length),
		"eligible_page": page,
		"eligible_page_length": page_length,
		"eligible_total_pages": total_pages,
		"subscription_topic": campaign.custom_subscription_topic or "",
		"topic_unsubscribed_count": topic_count,
		"topic_unsubscribed_samples": _frozen_recipient_preview_rows(
			topic_names[:MAX_TOPIC_OPTOUT_SAMPLES], MAX_TOPIC_OPTOUT_SAMPLES
		),
		"topic_unsubscribed_more": max(
			0,
			topic_count
			- min(len(topic_names), MAX_TOPIC_OPTOUT_SAMPLES),
		),
		"frozen": 1,
		"broadcast_status": campaign.custom_broadcast_status,
	}


def _campaign_for_studio(campaign_name):
	if not campaign_name:
		return None
	campaign = frappe.get_doc("Campaign", campaign_name)
	campaign.check_permission("read")
	start_on = get_datetime(campaign.custom_start_on) if campaign.custom_start_on else None
	return {
		"name": campaign.name,
		"campaign_title": campaign.campaign_name or campaign.name,
		"broadcast_status": campaign.custom_broadcast_status or "Draft",
		"editable": (campaign.custom_broadcast_status or "Draft") == "Draft",
		"email_template": campaign.custom_email_template,
		"subject_override": campaign.custom_subject_override,
		"subscription_topic": campaign.custom_subscription_topic,
		"email_account": campaign.custom_email_account,
		"sender_name": campaign.custom_sender_name,
		"reply_to": campaign.custom_reply_to,
		"filters": frappe.parse_json(campaign.custom_lead_filters_json or "[]"),
		"exclude_filters": frappe.parse_json(campaign.custom_exclude_filters_json or "[]"),
		"exclude_email_groups": frappe.parse_json(campaign.custom_exclude_email_groups_json or "[]"),
		"start_date": start_on.strftime("%Y-%m-%d") if start_on else "",
		"start_time": start_on.strftime("%H:%M:%S") if start_on else "",
		"batch_size": campaign.custom_batch_size or 100,
		"repeat_every": campaign.custom_repeat_every or 1,
		"repeat_unit": campaign.custom_repeat_unit or "Hours",
		"restrict_sending_window": cint(campaign.custom_restrict_sending_window),
		"window_start": _time_string(campaign.custom_window_start),
		"window_end": _time_string(campaign.custom_window_end),
		"enable_open_tracking": cint(campaign.custom_enable_open_tracking),
		"enable_click_tracking": cint(campaign.custom_enable_click_tracking),
		"utm_source": campaign.custom_utm_source or "newsletter",
		"utm_medium": campaign.custom_utm_medium or "email",
		"send_monday": cint(campaign.custom_send_monday),
		"send_tuesday": cint(campaign.custom_send_tuesday),
		"send_wednesday": cint(campaign.custom_send_wednesday),
		"send_thursday": cint(campaign.custom_send_thursday),
		"send_friday": cint(campaign.custom_send_friday),
		"send_saturday": cint(campaign.custom_send_saturday),
		"send_sunday": cint(campaign.custom_send_sunday),
	}


@frappe.whitelist()
def get_bootstrap(campaign_name=None):
	campaign_name = str(campaign_name or "").strip()
	_check_permission("read" if campaign_name else "create")
	accounts = frappe.get_list(
		"Email Account",
		filters={"enable_outgoing": 1},
		fields=["name", "email_id", "default_outgoing"],
		order_by="default_outgoing desc, modified desc",
		limit=100,
	)
	email_groups = frappe.get_list(
		"Email Group",
		fields=["name", "title"],
		order_by="title asc",
		limit=500,
	)
	start = now_datetime() + timedelta(minutes=5)
	return {
		"start_date": nowdate(),
		"start_time": start.strftime("%H:%M:%S"),
		"email_accounts": [
			{
				"value": account.name,
				"label": strip_html(account.email_id or account.name),
				"description": strip_html(account.name),
			}
			for account in accounts
		],
		"email_groups": [
			{"value": group.name, "label": strip_html(group.title or group.name)}
			for group in email_groups
		],
		"default_email_account": accounts[0].name if accounts else "",
		"default_test_recipient": frappe.session.user if "@" in frappe.session.user else "",
		"campaign": _campaign_for_studio(campaign_name),
	}


@frappe.whitelist(methods=["POST"])
def preview_audience(
	filters=None,
	exclude_filters=None,
	exclude_email_groups=None,
	subscription_topic=None,
	eligible_page=1,
	eligible_page_length=8,
	campaign_name=None,
):
	_check_permission("read")
	if campaign_name:
		campaign = frappe.get_doc("Campaign", campaign_name)
		campaign.check_permission("read")
		if (campaign.custom_broadcast_status or "Draft") != "Draft":
			return _frozen_preview_response(
				campaign, eligible_page, eligible_page_length
			)
	context = _audience_context(filters, exclude_filters, exclude_email_groups)
	return _preview_response(
		_resolved_studio_audience(context, subscription_topic),
		subscription_topic,
		eligible_page,
		eligible_page_length,
	)


@frappe.whitelist(methods=["POST"])
def preview_email(payload=None, sample_lead=None):
	"""Render a safe, non-sending preview using current draft or frozen campaign content."""
	_check_permission("read")
	payload = _parse_payload(payload)
	lead = frappe.get_doc("Lead", sample_lead)
	lead.check_permission("read")
	source_campaign = str(payload.get("source_campaign") or "").strip()
	campaign = None
	if source_campaign:
		campaign = frappe.get_doc("Campaign", source_campaign)
		campaign.check_permission("read")
	frozen = bool(campaign and campaign.custom_broadcast_status != "Draft")
	if frozen and not (
		campaign.custom_snapshot_subject and campaign.custom_snapshot_html
	):
		frappe.throw(_("The frozen campaign content is unavailable. This campaign cannot be previewed safely."))
	if frozen:
		snapshot = frappe._dict(
			mode=campaign.custom_template_mode or "Standard",
			subject=campaign.custom_snapshot_subject,
			preheader=campaign.custom_snapshot_preheader or "",
			html=campaign.custom_snapshot_html,
		)
		campaign_title = campaign.campaign_name or campaign.name
		utm_source = campaign.custom_utm_source or "newsletter"
		utm_medium = campaign.custom_utm_medium or "email"
		utm_campaign = campaign.custom_utm_campaign or slug(campaign_title)
	else:
		snapshot = get_campaign_snapshot(
			_required(payload, "email_template", _("Email Template")),
			payload.get("subject_override"),
		)
		campaign_title = str(payload.get("campaign_title") or _("Email Preview")).strip()
		utm_source = str(payload.get("utm_source") or "newsletter").strip()
		utm_medium = str(payload.get("utm_medium") or "email").strip()
		utm_campaign = slug(campaign_title)

	rendered = render_campaign_snapshot(snapshot.subject, snapshot.html, lead)
	preheader = ""
	if snapshot.get("preheader"):
		preheader = render_campaign_snapshot(
			snapshot.preheader, snapshot.preheader, lead
		).subject
	tracking_context = frappe._dict(
		custom_enable_click_tracking=0,
		custom_utm_source=utm_source,
		custom_utm_medium=utm_medium,
		custom_utm_campaign=utm_campaign,
	)
	html = email_marketing.decorate_campaign_links(
		rendered.html, tracking_context, "studio-preview", track_clicks=0
	)
	return {
		"subject": rendered.subject,
		"preheader": preheader,
		"html": html,
		"mode": snapshot.mode,
		"sample_lead": lead.name,
		"sample_lead_label": lead.lead_name or lead.name,
		"frozen": cint(frozen),
	}


def _required(payload, fieldname, label):
	value = payload.get(fieldname)
	if value in (None, "", []):
		frappe.throw(_("{0} is required").format(label))
	return value


def _default_if_blank(value, default):
	return default if value in (None, "") else value


def _ensure_utm_campaign(campaign_name):
	"""Create the UTM Campaign that ERPNext's Campaign controller expects to exist.

	Campaign.after_insert / on_change resolve ``UTM Campaign`` by campaign name via
	frappe.get_doc and only construct it inside an ``except DoesNotExistError`` branch.
	get_doc records the "... not found" message before raising, so the swallowed
	exception surfaces as a phantom error client-side. Ensuring the record exists first
	makes the lookup succeed; after_insert then simply reuses it. UTM Campaign is named
	by the user with no mandatory fields, so the name alone is enough.
	"""
	if not campaign_name or frappe.db.exists("UTM Campaign", campaign_name):
		return
	utm = frappe.new_doc("UTM Campaign")
	utm.name = campaign_name
	utm.insert(ignore_permissions=True)


def _campaign_values(payload, context, require_ready=True, preview=None):
	start_date = (
		_required(payload, "start_date", _("Start Date"))
		if require_ready
		else payload.get("start_date")
	)
	start_time = (
		_required(payload, "start_time", _("Start Time"))
		if require_ready
		else payload.get("start_time")
	)
	def ready_value(fieldname, label):
		return _required(payload, fieldname, label) if require_ready else payload.get(fieldname)

	batch_size = cint(_default_if_blank(payload.get("batch_size"), 100))
	values = {
		"doctype": "Campaign",
		"campaign_name": str(_required(payload, "campaign_title", _("Campaign Title"))).strip()[:140],
		"custom_broadcast_status": "Draft",
		"custom_email_template": ready_value("email_template", _("Email Template")),
		"custom_subject_override": str(payload.get("subject_override") or "").strip()[:140],
		"custom_subscription_topic": ready_value("subscription_topic", _("Subscription Topic")),
		"custom_email_account": ready_value("email_account", _("Email Account")),
		"custom_sender_name": str(payload.get("sender_name") or "").strip()[:140],
		"custom_reply_to": str(payload.get("reply_to") or "").strip(),
		"custom_lead_filters_json": context.include_filters_json,
		"custom_exclude_filters_json": context.exclude_filters_json,
		"custom_exclude_email_groups_json": frappe.as_json(context.email_groups),
		"custom_start_on": f"{start_date} {start_time}" if start_date and start_time else None,
		"custom_batch_size": batch_size,
		"custom_repeat_every": cint(_default_if_blank(payload.get("repeat_every"), 1)),
		"custom_repeat_unit": _default_if_blank(payload.get("repeat_unit"), "Hours"),
		"custom_restrict_sending_window": cint(payload.get("restrict_sending_window")),
		"custom_window_start": payload.get("window_start"),
		"custom_window_end": payload.get("window_end"),
		"custom_enable_open_tracking": cint(payload.get("enable_open_tracking", 1)),
		"custom_enable_click_tracking": cint(payload.get("enable_click_tracking", 1)),
		"custom_utm_source": str(payload.get("utm_source") or "newsletter").strip()[:140],
		"custom_utm_medium": str(payload.get("utm_medium") or "email").strip()[:140],
		"custom_send_monday": cint(payload.get("send_monday")),
		"custom_send_tuesday": cint(payload.get("send_tuesday")),
		"custom_send_wednesday": cint(payload.get("send_wednesday")),
		"custom_send_thursday": cint(payload.get("send_thursday")),
		"custom_send_friday": cint(payload.get("send_friday")),
		"custom_send_saturday": cint(payload.get("send_saturday")),
		"custom_send_sunday": cint(payload.get("send_sunday")),
	}
	if preview is not None:
		eligible_count = cint(preview.get("eligible_count"))
		values.update(
			{
				"custom_candidate_count": cint(preview.get("candidate_count")),
				"custom_eligible_count": eligible_count,
				"custom_excluded_count": cint(preview.get("excluded_count")),
				"custom_batch_count": math.ceil(eligible_count / batch_size) if batch_size > 0 else 0,
			}
		)
	return values


@frappe.whitelist(methods=["POST"])
def create_campaign(payload=None, launch="schedule"):
	launch = str(launch or "").strip().lower()
	if launch not in ("schedule", "draft"):
		frappe.throw(_("Launch action must be schedule or draft"))
	payload = _parse_payload(payload)
	source_campaign = str(payload.get("source_campaign") or "").strip()
	_check_permission("write" if source_campaign else "create")
	require_ready = launch == "schedule"
	context = _audience_context(
		payload.get("filters"),
		payload.get("exclude_filters"),
		payload.get("exclude_email_groups"),
		require_filters=require_ready,
	)
	preview = _preview_response(
		_resolved_studio_audience(context, payload.get("subscription_topic")),
		payload.get("subscription_topic"),
	)
	if require_ready and not preview["eligible_count"]:
		frappe.throw(_("No eligible recipients remain after filters and blacklists"))

	values = _campaign_values(payload, context, require_ready=require_ready, preview=preview)
	# ERPNext's Campaign.after_insert/on_change fetch the matching "UTM Campaign" with
	# frappe.get_doc and only build it inside an `except DoesNotExistError` branch. Because
	# get_doc appends a "... not found" message to the log before raising, that swallowed
	# exception leaks a phantom error to the client even though the save succeeds. Creating
	# the UTM Campaign up front makes the lookup succeed so nothing is ever thrown.
	_ensure_utm_campaign(values["campaign_name"])
	if source_campaign:
		campaign = frappe.get_doc("Campaign", source_campaign)
		campaign.check_permission("write")
		if (campaign.custom_broadcast_status or "Draft") not in EDITABLE_BROADCAST_STATUSES:
			frappe.throw(_("Only draft campaigns can be edited in Studio. Delivery history is immutable."))
		for fieldname, value in values.items():
			if fieldname != "doctype":
				campaign.set(fieldname, value)
		campaign.save()
	else:
		campaign = frappe.get_doc(values).insert()
	if launch == "schedule":
		email_marketing.schedule_campaign(campaign.name)
		status = "Scheduled"
	else:
		status = "Draft"

	return {
		"campaign": campaign.name,
		"created": not bool(source_campaign),
		"status": status,
		"preview": preview,
		"route": ["Form", "Campaign", campaign.name],
	}


@frappe.whitelist(methods=["POST"])
def send_test(payload=None, recipient=None, sample_lead=None):
	_check_permission("email")
	payload = _parse_payload(payload)
	source_campaign = str(payload.get("source_campaign") or "").strip()
	campaign = None
	if source_campaign:
		campaign = frappe.get_doc("Campaign", source_campaign)
		campaign.check_permission("email")
	recipient = str(recipient or "").strip()
	validate_email_address(recipient, throw=True)
	if any(character in recipient for character in (",", ";", "\n", "\r")):
		frappe.throw(_("Send a test to one email address at a time"))
	test_topic = (
		campaign.custom_subscription_topic
		if campaign and campaign.custom_broadcast_status != "Draft"
		else payload.get("subscription_topic")
	)
	exclusion_reason = email_marketing.test_recipient_exclusion(recipient, test_topic)
	if exclusion_reason:
		frappe.throw(
			_("Test email blocked by recipient suppression: {0}").format(exclusion_reason)
		)
	_check_test_email_rate_limit()

	frozen = bool(campaign and campaign.custom_broadcast_status != "Draft")
	if frozen and not (
		campaign.custom_snapshot_subject and campaign.custom_snapshot_html
	):
		frappe.throw(_("The frozen campaign content is unavailable. A test email cannot be sent safely."))
	account_name = (
		campaign.custom_email_account
		if frozen
		else _required(payload, "email_account", _("Email Account"))
	)
	account = frappe.get_doc("Email Account", account_name)
	account.check_permission("read")
	if not cint(account.enable_outgoing):
		frappe.throw(_("Email Account {0} is not enabled for outgoing mail").format(account_name))
	lead = frappe.get_doc("Lead", sample_lead)
	lead.check_permission("read")
	if frozen:
		snapshot = frappe._dict(
			mode=campaign.custom_template_mode or "Standard",
			subject=campaign.custom_snapshot_subject,
			html=campaign.custom_snapshot_html,
		)
	else:
		snapshot = get_campaign_snapshot(
			_required(payload, "email_template", _("Email Template")),
			payload.get("subject_override"),
		)
	rendered = render_campaign_snapshot(snapshot.subject, snapshot.html, lead)
	tracking_context = frappe._dict(
		custom_enable_click_tracking=0,
		custom_utm_source=str(
			(campaign.custom_utm_source if frozen else payload.get("utm_source"))
			or "newsletter"
		).strip(),
		custom_utm_medium=str(
			(campaign.custom_utm_medium if frozen else payload.get("utm_medium")) or "email"
		).strip(),
		custom_utm_campaign=(
			campaign.custom_utm_campaign
			if frozen
			else slug(_required(payload, "campaign_title", _("Campaign Title")))
		),
	)
	html = email_marketing.decorate_campaign_links(
		rendered.html, tracking_context, "studio-test", track_clicks=0
	)
	reply_to = str(
		(campaign.custom_reply_to if frozen else payload.get("reply_to")) or ""
	).strip()
	if reply_to:
		validate_email_address(reply_to, throw=True)
	sender_name = str(
		(campaign.custom_sender_name if frozen else payload.get("sender_name")) or ""
	).strip()
	sender = formataddr((sender_name, account.email_id)) if sender_name else account.email_id
	queue = frappe.sendmail(
		recipients=[recipient],
		sender=sender,
		reply_to=reply_to or None,
		subject=f"[TEST] {rendered.subject}",
		content=html,
		reference_doctype="Lead",
		reference_name=lead.name,
		raw_html=snapshot.mode == "Visual",
		add_css=snapshot.mode != "Visual",
		add_unsubscribe_link=0,
	)
	return {"status": "queued", "email_queue": queue.name if queue else None}
																														