from __future__ import annotations

from urllib.parse import quote

import frappe
from frappe import _

from .constants import (
	BUILDER_TARGET_DOCTYPES,
	EMAIL_TEMPLATE_DOCTYPE,
)


def normalize_template_doctype(template_doctype: str | None = None) -> str:
	doctype = str(template_doctype or EMAIL_TEMPLATE_DOCTYPE).strip()
	if doctype not in BUILDER_TARGET_DOCTYPES:
		frappe.throw(_("Unsupported email builder document type"), frappe.PermissionError)
	return doctype


def builder_route(name: str, template_doctype: str | None = None) -> str:
	doctype = normalize_template_doctype(template_doctype)
	params = f"template={quote(str(name), safe='')}"
	if doctype != EMAIL_TEMPLATE_DOCTYPE:
		params += f"&template_doctype={quote(doctype, safe='')}"
	return f"/builder?{params}"


def target_reference_filters(template_doctype: str, template_name: str) -> dict:
	return {
		"template_doctype": normalize_template_doctype(template_doctype),
		"template": template_name,
	}


def reference_matches(reference, template_doctype: str, template_name: str) -> bool:
	doctype = normalize_template_doctype(template_doctype)
	reference_doctype = reference.get("template_doctype") or EMAIL_TEMPLATE_DOCTYPE
	return reference_doctype == doctype and reference.get("template") == template_name
