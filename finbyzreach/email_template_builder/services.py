from __future__ import annotations

import hashlib
import json
import re

import frappe
from frappe import _
from frappe.utils.jinja import validate_template

from .tokens import compile_attribute, compile_tokens, validate_semantic_tokens
from .targets import normalize_template_doctype


PREHEADER_STYLE = "display:none;max-height:0;overflow:hidden;opacity:0;color:transparent;"
_PREHEADER_RE = re.compile(r'<div style="' + re.escape(PREHEADER_STYLE) + r'">.*?</div>', re.S)
_BODY_RE = re.compile(r"<body\b[^>]*>", re.I)


def _with_preheader(html: str, override: str) -> str:
	"""EM-26: put the campaign preview text into the sent HTML as the hidden preheader.

	The template HTML is precompiled with the template's own preheader (or none), so an
	override only in the snapshot metadata never reached the inbox.
	"""
	block = f'<div style="{PREHEADER_STYLE}">{compile_attribute(str(override).strip())}</div>'
	if _PREHEADER_RE.search(html):
		return _PREHEADER_RE.sub(lambda _match: block, html, count=1)
	body = _BODY_RE.search(html)
	if body:
		return html[: body.end()] + block + html[body.end() :]
	return block + html


def get_campaign_snapshot(
	template_name: str,
	subject_override: str | None = None,
	check_permission: bool = True,
	template_doctype: str | None = None,
	preheader_override: str | None = None,
) -> frappe._dict:
	"""Return send-ready source directly from a saved builder target."""
	template_doctype = normalize_template_doctype(template_doctype)
	template = frappe.get_doc(template_doctype, template_name)
	if check_permission:
		template.check_permission("read")
	meta = frappe.get_meta(template_doctype)
	mode = template.get("custom_builder_mode") if meta.has_field("custom_builder_mode") else "Standard"
	reference_doctype = (
		template.get("custom_reference_doctype") if meta.has_field("custom_reference_doctype") else ""
	) or ""
	preheader = template.get("custom_preheader_text") if meta.has_field("custom_preheader_text") else ""
	if str(preheader_override or "").strip():
		# EM-26: preview text chosen for this campaign only; the template keeps its own.
		preheader = compile_tokens(validate_semantic_tokens(str(preheader_override).strip()), "ebt")
	html = template.response_html if template.use_html else template.response
	if str(preheader_override or "").strip() and str(html or "").strip():
		html = _with_preheader(html, preheader_override)
	if subject_override:
		subject = compile_tokens(validate_semantic_tokens(subject_override), "ebt")
	else:
		subject = template.subject

	if not str(subject or "").strip():
		frappe.throw(_("The selected template has no subject"))
	if not str(html or "").strip():
		frappe.throw(_("The selected template has no email content"))
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


def render_campaign_snapshot(
	subject: str, html: str, lead=None, extra_context: dict | None = None
) -> frappe._dict:
	"""Render saved builder/Jinja source with the same context shape as Builder preview.

	``extra_context`` is merged into the Jinja context *after* the lead fields so callers
	can inject send-time variables (e.g. ``email_preview_url``) without altering the
	core lead-context logic.
	"""
	if isinstance(lead, str) and frappe.db.exists("Lead", lead):
		lead = frappe.get_doc("Lead", lead)
	if hasattr(lead, "as_dict"):
		values = frappe._dict(lead.as_dict())
	elif isinstance(lead, dict):
		values = frappe._dict(lead)
	else:
		values = frappe._dict()
	context = frappe._dict({**values, "doc": values, **(extra_context or {})})
	return frappe._dict(
		subject=frappe.render_template(subject, context),
		html=frappe.render_template(html, context),
	)
