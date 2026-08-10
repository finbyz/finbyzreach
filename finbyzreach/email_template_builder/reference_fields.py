from __future__ import annotations

import frappe
from frappe.model import get_permitted_fields


REFERENCE_EXCLUDED_FIELDS = {
	"Section Break",
	"Column Break",
	"Tab Break",
	"Table",
	"Table MultiSelect",
	"Password",
	"HTML",
	"Code",
	"Attach Image",
}


def _is_safe_field(df) -> bool:
	return bool(
		df
		and df.fieldname
		and df.fieldtype not in REFERENCE_EXCLUDED_FIELDS
		and not df.hidden
		and not df.is_virtual
	)


def permitted_reference_fields(doctype: str) -> set[str]:
	"""Return scalar fields the current user may use for personalization."""
	meta = frappe.get_meta(doctype)
	permitted = set(get_permitted_fields(doctype, ignore_virtual=True))
	fields = {"name"}
	fields.update(df.fieldname for df in meta.fields if df.fieldname in permitted and _is_safe_field(df))
	return fields


def reference_field_rows(doctype: str, *, prefix: str = "") -> list[dict]:
	"""Return safe, readable field metadata for a personalization picker."""
	meta = frappe.get_meta(doctype)
	permitted = permitted_reference_fields(doctype)
	rows = [
		{
			"fieldname": f"{prefix}.name" if prefix else "name",
			"label": frappe._("ID"),
			"fieldtype": "Data",
			"options": "",
		}
	]
	rows.extend(
		{
			"fieldname": f"{prefix}.{df.fieldname}" if prefix else df.fieldname,
			"label": df.label or df.fieldname,
			"fieldtype": df.fieldtype,
			# Link options identify the related DocType. Select-like options
			# provide useful value metadata to the condition/token UI.
			"options": (df.options or "")
			if df.fieldtype in {"Link", "Select", "Autocomplete", "MultiSelect"}
			else "",
		}
		for df in meta.fields
		if df.fieldname in permitted and _is_safe_field(df)
	)
	return rows


def link_target_doctype(reference_doctype: str, link_fieldname: str, *, require_permission: bool = True) -> str:
	"""Validate one static Frappe Link and return its target DocType."""
	if "." in str(link_fieldname or ""):
		return ""
	if require_permission and link_fieldname not in permitted_reference_fields(reference_doctype):
		return ""
	df = frappe.get_meta(reference_doctype).get_field(link_fieldname)
	if not _is_safe_field(df) or df.fieldtype != "Link":
		return ""
	target = str(df.options or "").strip()
	if not target or not frappe.db.exists("DocType", target):
		return ""
	if require_permission and not frappe.has_permission(target, "read"):
		return ""
	return target


def is_permitted_reference_path(reference_doctype: str, field_path: str) -> bool:
	"""Allow a root field or one explicitly declared Link traversal."""
	parts = str(field_path or "").split(".")
	if len(parts) == 1:
		return parts[0] in permitted_reference_fields(reference_doctype)
	if len(parts) != 2:
		return False
	link_fieldname, target_fieldname = parts
	target = link_target_doctype(reference_doctype, link_fieldname)
	return bool(target and target_fieldname in permitted_reference_fields(target))


def resolve_linked_value(source_doctype: str, field_path: str, source: dict):
	"""Resolve a validated one-level Link path while rendering an email.

	Permissions are enforced when the template is authored/saved. Rendering can
	run in a queue worker under a different user, so this runtime guard validates
	the DocField relationship and safe scalar target field without depending on
	the worker's role set.
	"""
	parts = str(field_path or "").split(".")
	if len(parts) != 2:
		return None, False
	link_fieldname, target_fieldname = parts
	source_df = frappe.get_meta(source_doctype).get_field(link_fieldname)
	if not _is_safe_field(source_df) or source_df.fieldtype != "Link":
		return None, False
	target_doctype = str(source_df.options or "").strip()
	if not target_doctype or not frappe.db.exists("DocType", target_doctype):
		return None, False
	target_name = source.get(link_fieldname)
	if not target_name:
		return None, True
	if target_fieldname == "name":
		return target_name, True
	target_df = frappe.get_meta(target_doctype).get_field(target_fieldname)
	if not _is_safe_field(target_df):
		return None, False
	return frappe.db.get_value(target_doctype, target_name, target_fieldname), True
