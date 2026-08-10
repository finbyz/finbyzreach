from __future__ import annotations

import hashlib
import json

import frappe
from frappe import _
from frappe.utils.jinja import validate_template

from .tokens import compile_tokens, validate_semantic_tokens


def get_campaign_snapshot(template_name: str, subject_override: str | None = None) -> frappe._dict:
	"""Return send-ready source directly from a saved Email Template."""
	template = frappe.get_doc("Email Template", template_name)
	template.check_permission("read")
	meta = frappe.get_meta("Email Template")
	mode = template.get("custom_builder_mode") if meta.has_field("custom_builder_mode") else "Standard"
	reference_doctype = (
		template.get("custom_reference_doctype") if meta.has_field("custom_reference_doctype") else ""
	) or ""
	preheader = template.get("custom_preheader_text") if meta.has_field("custom_preheader_text") else ""
	html = template.response_html if template.use_html else template.response
	if subject_override:
		subject = compile_tokens(validate_semantic_tokens(subject_override), "ebt")
	else:
		subject = template.subject

	if not str(subject or "").strip():
		frappe.throw(_("The selected Email Template has no subject"))
	if not str(html or "").strip():
		frappe.throw(_("The selected Email Template has no email content"))
	validate_template(subject)
	validate_template(html)

	snapshot_payload = {
		"mode": mode or "Standard",
		"reference_doctype": reference_doctype,
		"subject": subject,
		"preheader": preheader or "",
		"html": html,
	}
	return frappe._dict(
		template=template.name,
		**snapshot_payload,
		content_hash=hashlib.sha256(
			json.dumps(snapshot_payload, sort_keys=True, ensure_ascii=False).encode()
		).hexdigest(),
	)


def render_campaign_snapshot(subject: str, html: str, lead) -> frappe._dict:
	"""Render saved builder/Jinja source with the same context shape as Builder preview."""
	if isinstance(lead, str):
		lead = frappe.get_doc("Lead", lead)
	values = frappe._dict(lead.as_dict())
	context = frappe._dict({**values, "doc": values})
	return frappe._dict(
		subject=frappe.render_template(subject, context),
		html=frappe.render_template(html, context),
	)
