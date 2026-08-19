from __future__ import annotations

import json

import frappe
from frappe import _

from finbyzreach import email_marketing


def _filters_for_segment(segment):
	if segment.segment_type == "Static":
		return []
	return frappe.parse_json(segment.filter_groups_json or "[]")


@frappe.whitelist(methods=["POST"])
def create_segment(segment_name, segment_type, filter_groups, exclude_filters="[]", exclude_email_groups="[]"):
	frappe.has_permission("Reach Segment", "create", throw=True)
	segment_name = str(segment_name or "").strip()[:140]
	if not segment_name:
		frappe.throw(_("Segment name is required"))
	if segment_type not in ("Active", "Static"):
		frappe.throw(_("Segment type must be Active or Static"))
	if frappe.db.exists("Reach Segment", segment_name):
		frappe.throw(_("A segment named {0} already exists").format(frappe.bold(segment_name)))

	filter_groups_json = email_marketing.validate_lead_filter_groups(
		filter_groups, require_filters=True
	)
	
	exclude_filters_json = exclude_filters
	exclude_email_groups_json = exclude_email_groups
	
	member_names = []
	if segment_type == "Static":
		include_leads = set(email_marketing._lead_names_from_filter_groups(filter_groups_json))
		exclude_leads = set()
		if exclude_filters_json and exclude_filters_json != "[]":
			exclude_leads.update(email_marketing._lead_names_from_filter_groups(exclude_filters_json))
		if exclude_email_groups_json and exclude_email_groups_json != "[]":
			exclude_emails = set()
			for group_name in email_marketing.validate_excluded_email_groups(exclude_email_groups_json):
				exclude_emails.update(email_marketing._email_group_addresses(group_name))
			if exclude_emails:
				excluded_by_email = frappe.get_all(
					"Lead",
					filters={"email_id": ("in", list(exclude_emails))},
					pluck="name",
					limit_page_length=0
				)
				exclude_leads.update(excluded_by_email)
		member_names = sorted(list(include_leads - exclude_leads))
		
	doc = frappe.get_doc(
		{
			"doctype": "Reach Segment",
			"segment_name": segment_name,
			"segment_type": segment_type,
			"filter_groups_json": filter_groups_json,
			"exclude_filters_json": exclude_filters_json,
			"exclude_email_groups_json": exclude_email_groups_json,
			"static_leads_json": json.dumps(member_names, separators=(",", ":")),
			"member_count": len(member_names),
		}
	).insert()
	return {"name": doc.name, "segment_type": doc.segment_type, "member_count": doc.member_count}


@frappe.whitelist()
def get_segment_filters(segment_name):
	segment = frappe.get_doc("Reach Segment", segment_name)
	segment.check_permission("read")
	filters = _filters_for_segment(segment)
	exclude_filters = []
	if segment.segment_type != "Static":
		exclude_filters = frappe.parse_json(segment.exclude_filters_json or "[]")
	return {
		"name": segment.name,
		"segment_type": segment.segment_type,
		"filters": filters,
		"exclude_filters": exclude_filters,
		"exclude_email_groups": frappe.parse_json(segment.exclude_email_groups_json or "[]"),
		"member_count": segment.member_count,
	}
