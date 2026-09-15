from __future__ import annotations

import json

import frappe
from frappe import _
from frappe.utils.jinja import validate_template

from .api import _compiled_subject, _content_hash, _require_designer
from .constants import EMAIL_TEMPLATE_DOCTYPE, EMAIL_TEMPLATE_MASTER_DOCTYPE
from .targets import builder_route
from .tokens import validate_semantic_tokens


COPY_FIELDS = (
	"use_html",
	"response_html",
	"response",
	"custom_builder_mode",
	"custom_builder_schema",
	"custom_builder_schema_version",
	"custom_builder_content_hash",
	"custom_preheader_text",
	"custom_builder_subject_source",
	"custom_reference_doctype",
	"custom_preview_document",
)


def _master(name: str, ptype: str = "read"):
	_require_designer()
	doc = frappe.get_doc(EMAIL_TEMPLATE_MASTER_DOCTYPE, name)
	doc.check_permission(ptype)
	return doc


def _copy_public_attachments(source, target) -> None:
	rows = frappe.get_all(
		"File",
		filters={
			"attached_to_doctype": source.doctype,
			"attached_to_name": source.name,
			"is_private": 0,
			"is_folder": 0,
		},
		fields=["file_name", "file_url", "folder", "content_hash"],
	)
	for row in rows:
		if frappe.db.exists(
			"File",
			{
				"attached_to_doctype": target.doctype,
				"attached_to_name": target.name,
				"file_url": row.file_url,
			},
		):
			continue
		frappe.get_doc(
			{
				"doctype": "File",
				"file_name": row.file_name,
				"file_url": row.file_url,
				"folder": row.folder or "Home/Attachments",
				"content_hash": row.content_hash,
				"is_private": 0,
				"attached_to_doctype": target.doctype,
				"attached_to_name": target.name,
			}
		).insert(ignore_permissions=True)


@frappe.whitelist(methods=["POST"])
def create_email_from_master(master_name, template_name, subject=None):
	master = _master(str(master_name or "").strip())
	if not master.enabled:
		frappe.throw(_("This master template is disabled"))
	frappe.has_permission(EMAIL_TEMPLATE_DOCTYPE, "create", throw=True)

	template_name = str(template_name or "").strip()[:140]
	if not template_name:
		frappe.throw(_("Email Template name is required"))
	if frappe.db.exists(EMAIL_TEMPLATE_DOCTYPE, template_name):
		frappe.throw(_("Email Template {0} already exists").format(frappe.bold(template_name)))

	subject_source = validate_semantic_tokens(
		str(subject or master.get("custom_builder_subject_source") or master.subject or template_name).strip()[:140]
	)
	compiled_subject = _compiled_subject(subject_source)
	validate_template(compiled_subject)

	values = {
		"doctype": EMAIL_TEMPLATE_DOCTYPE,
		"name": template_name,
		"subject": compiled_subject,
	}
	meta = frappe.get_meta(EMAIL_TEMPLATE_DOCTYPE)
	for fieldname in COPY_FIELDS:
		if meta.has_field(fieldname):
			values[fieldname] = master.get(fieldname)
	values["custom_builder_subject_source"] = subject_source

	doc = frappe.get_doc(values)
	doc.insert()
	_copy_public_attachments(master, doc)
	return {
		"name": doc.name,
		"master": master.name,
		"modified": doc.modified,
		"route": builder_route(doc.name, EMAIL_TEMPLATE_DOCTYPE),
	}


@frappe.whitelist(methods=["GET"])
def get_master_preview(master_name):
	master = _master(str(master_name or "").strip())
	return {
		"name": master.name,
		"subject": master.get("custom_builder_subject_source") or master.subject,
		"folder": master.folder or "",
		"thumbnail": master.thumbnail or "",
		"html": master.response_html if master.use_html else master.response,
		"mode": master.custom_builder_mode or "Raw HTML",
	}


@frappe.whitelist(methods=["POST"])
def create_master_from_email(template_name, master_name, folder=None):
	"""Create a new independently editable master from an existing Email Template."""
	_require_designer()
	source = frappe.get_doc(EMAIL_TEMPLATE_DOCTYPE, template_name)
	source.check_permission("read")
	frappe.has_permission(EMAIL_TEMPLATE_MASTER_DOCTYPE, "create", throw=True)
	master_name = str(master_name or "").strip()[:140]
	if not master_name:
		frappe.throw(_("Master template name is required"))
	if frappe.db.exists(EMAIL_TEMPLATE_MASTER_DOCTYPE, master_name):
		frappe.throw(_("Email Template Master {0} already exists").format(frappe.bold(master_name)))

	values = {
		"doctype": EMAIL_TEMPLATE_MASTER_DOCTYPE,
		"name": master_name,
		"subject": source.subject,
		"folder": folder or None,
		"enabled": 1,
	}
	for fieldname in COPY_FIELDS:
		values[fieldname] = source.get(fieldname)
	if not values.get("custom_builder_content_hash"):
		body = source.response_html if source.use_html else source.response
		values["custom_builder_content_hash"] = _content_hash(body or "")
	if values.get("custom_builder_schema"):
		json.loads(values["custom_builder_schema"])

	master = frappe.get_doc(values)
	master.insert()
	_copy_public_attachments(source, master)
	return {
		"name": master.name,
		"modified": master.modified,
		"route": builder_route(master.name, EMAIL_TEMPLATE_MASTER_DOCTYPE),
	}
