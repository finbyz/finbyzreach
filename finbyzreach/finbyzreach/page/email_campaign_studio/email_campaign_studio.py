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
	get_url,
	now_datetime,
	nowdate,
	slug,
	strip_html,
	validate_email_address,
)
from frappe.utils.verified_command import get_signed_params

from finbyzreach.email_template_builder.api import _check_test_email_rate_limit
from finbyzreach.email_template_builder.services import (
	get_campaign_snapshot,
	render_campaign_snapshot,
)
from finbyzreach import email_marketing
from finbyzreach.segments import get_segment_filters


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
	return email_marketing._lead_names_from_filter_groups(filters_json)


def _audience_context(
	filters, exclude_filters=None, exclude_email_groups=None, require_filters=True,
	segment_name=None,
):
	def filter_payload(value):
		return value if isinstance(value, str) else json.dumps(value or [])

	segment_name = str(segment_name or "").strip()
	static_leads = None
	if segment_name:
		segment = frappe.get_doc("Reach Segment", segment_name)
		segment.check_permission("read")
		if segment.segment_type == "Static":
			static_leads = frappe.parse_json(segment.static_leads_json or "[]")
		else:
			filters = get_segment_filters(segment_name)["filters"]
	include_filters_json = email_marketing.validate_lead_filter_groups(
		filter_payload(filters), require_filters=require_filters
	)
	if exclude_filters:
		exclude_filters_json = email_marketing.validate_lead_filter_groups(
			filter_payload(exclude_filters)
		)
		exclude_leads = email_marketing._lead_names_from_filter_groups(exclude_filters_json)
	else:
		exclude_filters_json = "[]"
		exclude_leads = []
	email_groups = email_marketing.validate_excluded_email_groups(
		json.dumps(_parse_json_list(exclude_email_groups, _("blacklist email groups")))
	)
	return frappe._dict(
		include_filters_json=include_filters_json,
		exclude_filters_json=exclude_filters_json,
		email_groups=email_groups,
		include_leads=static_leads if static_leads is not None else _lead_names(include_filters_json),
		exclude_leads=_lead_names(exclude_filters_json),
		segment_name=segment_name,
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
			reason=row.get("custom_excluded_reason") or row.get("reason") or "",
		)
		for row in recipients
	]


def _clean_audience_search(search_text):
	return str(search_text or "").strip()[:140]


def _filter_resolved_by_search(resolved, search_text):
	search_text = _clean_audience_search(search_text)
	resolved = list(resolved or [])
	if not search_text or not resolved:
		return resolved, search_text

	lead_names = list(dict.fromkeys(row.lead for row in resolved if row.get("lead")))
	if not lead_names:
		return [], search_text

	pattern = f"%{search_text}%"
	matching_names = set(
		frappe.get_all(
			"Lead",
			filters=[["name", "in", lead_names]],
			or_filters=[
				["name", "like", pattern],
				["lead_name", "like", pattern],
				["company_name", "like", pattern],
				["email_id", "like", pattern],
			],
			pluck="name",
			limit=0,
		)
	)
	return [row for row in resolved if row.lead in matching_names], search_text


def _frozen_audience_query(campaign_name, search_text):
	recipient = frappe.qb.DocType("Email Campaign")
	lead = frappe.qb.DocType("Lead")
	query = (
		frappe.qb.from_(recipient)
		.left_join(lead)
		.on(lead.name == recipient.recipient)
		.where(recipient.campaign_name == campaign_name)
	)
	search_text = _clean_audience_search(search_text)
	if search_text:
		pattern = f"%{search_text}%"
		query = query.where(
			(recipient.recipient.like(pattern))
			| (recipient.custom_recipient_email.like(pattern))
			| (lead.lead_name.like(pattern))
			| (lead.company_name.like(pattern))
			| (lead.email_id.like(pattern))
		)
	return query, recipient, search_text


def _query_count(query, table):
	result = query.select(Count(table.name)).run()
	return cint(result[0][0]) if result else 0


def _preview_response(
	resolved,
	subscription_topic=None,
	eligible_page=1,
	eligible_page_length=8,
	excluded_page=1,
	search_text=None,
):
	resolved, search_text = _filter_resolved_by_search(resolved, search_text)
	reasons = Counter(row.reason for row in resolved if row.reason)
	eligible_names = [row.lead for row in resolved if row.eligible]
	excluded_names = [row.lead for row in resolved if not row.eligible]
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

	excluded_total_pages = (
		(len(excluded_names) + page_length - 1) // page_length if excluded_names else 0
	)
	exc_page = max(cint(excluded_page) or 1, 1)
	if excluded_total_pages:
		exc_page = min(exc_page, excluded_total_pages)
	exc_offset = (exc_page - 1) * page_length
	excluded_samples = _lead_preview_rows(
		excluded_names[exc_offset : exc_offset + page_length], page_length
	)
	resolved_by_lead = {row.lead: row for row in resolved}
	for sample in excluded_samples:
		sample.reason = resolved_by_lead[sample.name].reason

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
		"eligible_count": len(eligible_names),
		"excluded_count": len(excluded_names),
		"excluded_reasons": dict(reasons),
		"eligible_samples": samples,
		"eligible_page": page,
		"eligible_page_length": page_length,
		"eligible_total_pages": total_pages,
		"excluded_samples": excluded_samples,
		"excluded_page": exc_page,
		"excluded_total_pages": excluded_total_pages,
		"subscription_topic": subscription_topic or "",
		"topic_unsubscribed_count": len(topic_unsubscribed_names),
		"topic_unsubscribed_samples": topic_unsubscribed_samples,
		"topic_unsubscribed_more": max(
			0, len(topic_unsubscribed_names) - len(topic_unsubscribed_samples)
		),
		"search_text": search_text,
	}


def _frozen_preview_response(
	campaign,
	eligible_page=1,
	eligible_page_length=8,
	excluded_page=1,
	search_text=None,
):
	"""Return the scheduled recipient snapshot without recalculating live Lead filters."""
	page_length = min(
		max(cint(eligible_page_length) or 8, 1), MAX_AUDIENCE_HEALTH_PAGE_LENGTH
	)
	base_query, recipient, search_text = _frozen_audience_query(campaign.name, search_text)

	eligible_query = base_query.where(recipient.custom_batch_number > 0)
	actual_eligible_count = _query_count(eligible_query, recipient)
	eligible_count = actual_eligible_count if search_text else cint(campaign.custom_eligible_count)
	total_pages = (
		(actual_eligible_count + page_length - 1) // page_length
		if actual_eligible_count else 0
	)
	page = max(cint(eligible_page) or 1, 1)
	if total_pages:
		page = min(page, total_pages)
	offset = (page - 1) * page_length
	recipients = (
		eligible_query
		.select(recipient.recipient, recipient.custom_recipient_email)
		.orderby(recipient.custom_batch_number)
		.orderby(recipient.name)
		.offset(offset)
		.limit(page_length)
	).run(as_dict=True)

	excluded_query = base_query.where(recipient.custom_batch_number == 0)
	actual_excluded_count = _query_count(excluded_query, recipient)
	excluded_count = actual_excluded_count if search_text else cint(campaign.custom_excluded_count)
	excluded_total_pages = (
		(actual_excluded_count + page_length - 1) // page_length
		if actual_excluded_count else 0
	)
	exc_page = max(cint(excluded_page) or 1, 1)
	if excluded_total_pages:
		exc_page = min(exc_page, excluded_total_pages)
	exc_offset = (exc_page - 1) * page_length
	excluded_recipients = (
		excluded_query
		.select(
			recipient.recipient,
			recipient.custom_recipient_email,
			recipient.custom_excluded_reason,
		)
		.orderby(recipient.name)
		.offset(exc_offset)
		.limit(page_length)
	).run(as_dict=True)

	reason_rows = (
		excluded_query
		.where(recipient.custom_excluded_reason != "")
		.select(
			recipient.custom_excluded_reason,
			Count(recipient.name).as_("count"),
		)
		.groupby(recipient.custom_excluded_reason)
	).run(as_dict=True)
	reasons = {row.custom_excluded_reason: cint(row.count) for row in reason_rows}

	topic_reason = (
		_("Unsubscribed from topic {0}").format(campaign.custom_subscription_topic)
		if campaign.custom_subscription_topic
		else ""
	)
	topic_names = []
	topic_count = 0
	if topic_reason:
		topic_query = base_query.where(
			(recipient.custom_excluded_reason == topic_reason)
			| (recipient.custom_unsubscribed == 1)
		)
		topic_count = _query_count(topic_query, recipient)
		topic_names = (
			topic_query
			.select(
				recipient.recipient,
				recipient.custom_recipient_email,
				recipient.custom_excluded_reason,
			)
			.orderby(recipient.name)
			.limit(MAX_TOPIC_OPTOUT_SAMPLES + 1)
		).run(as_dict=True)

	candidate_count = (
		actual_eligible_count + actual_excluded_count
		if search_text
		else cint(campaign.custom_candidate_count)
	)
	return {
		"candidate_count": candidate_count,
		"eligible_count": eligible_count,
		"excluded_count": excluded_count,
		"excluded_reasons": reasons,
		"eligible_samples": _frozen_recipient_preview_rows(recipients, page_length),
		"eligible_page": page,
		"eligible_page_length": page_length,
		"eligible_total_pages": total_pages,
		"excluded_samples": _frozen_recipient_preview_rows(excluded_recipients, page_length),
		"excluded_page": exc_page,
		"excluded_total_pages": excluded_total_pages,
		"subscription_topic": campaign.custom_subscription_topic or "",
		"topic_unsubscribed_count": topic_count,
		"topic_unsubscribed_samples": _frozen_recipient_preview_rows(
			topic_names[:MAX_TOPIC_OPTOUT_SAMPLES], MAX_TOPIC_OPTOUT_SAMPLES
		),
		"topic_unsubscribed_more": max(
			0,
			topic_count - min(len(topic_names), MAX_TOPIC_OPTOUT_SAMPLES),
		),
		"search_text": search_text,
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
		"editable": (campaign.custom_broadcast_status or "Draft") == "Draft" and not campaign.custom_queued,
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
	segment_name=None,
	eligible_page=1,
	eligible_page_length=8,
	excluded_page=1,
	campaign_name=None,
	search_text=None,
):
	_check_permission("read")
	if campaign_name:
		campaign = frappe.get_doc("Campaign", campaign_name)
		campaign.check_permission("read")
		if (campaign.custom_broadcast_status or "Draft") != "Draft":
			return _frozen_preview_response(
				campaign, eligible_page, eligible_page_length, excluded_page, search_text
			)
	context = _audience_context(
		filters, exclude_filters, exclude_email_groups, segment_name=segment_name
	)
	return _preview_response(
		_resolved_studio_audience(context, subscription_topic),
		subscription_topic,
		eligible_page,
		eligible_page_length,
		excluded_page,
		search_text
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

	rendered = render_campaign_snapshot(
		snapshot.subject,
		snapshot.html,
		lead,
		extra_context={"email_preview_url": "#"},
	)
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
		segment_name=payload.get("segment_name"),
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
		campaign.db_set("custom_queued", 1)
		frappe.enqueue(
			"finbyzreach.email_marketing.schedule_campaign",
			campaign_name=campaign.name,
			queue="long",
			timeout=1500,
			now=frappe.flags.in_test
		)
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
	test_params = {"is_test": "1"}
	if campaign:
		test_params["campaign"] = campaign.name
	else:
		test_params["template"] = payload.get("email_template")
		if payload.get("subject_override"):
			test_params["subject_override"] = payload.get("subject_override")
	if lead and hasattr(lead, "name"):
		test_params["lead"] = lead.name
	preview_url = get_url(f"/view_email?{get_signed_params(test_params)}")

	rendered = render_campaign_snapshot(
		snapshot.subject,
		snapshot.html,
		lead,
		extra_context={"email_preview_url": preview_url},
	)
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
																														
