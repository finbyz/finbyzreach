"""Header and footer: rows linked to a shared saved Header or Footer block.

An email can use a saved block of category Header or Footer. While the row is not customised it always
shows the current shared version, so a change to the saved block reaches the email when it is next opened
or saved. "Customise in this email only" cuts the link for that email; "Reset" reconnects it.
"""
from __future__ import annotations

import copy
import json

import frappe

SHARED_CATEGORIES = {"Header", "Footer", "CTA", "Social"}


def is_linked(section: dict) -> bool:
	return bool(
		section.get("saved_component")
		and section.get("saved_component_category") in SHARED_CATEGORIES
		and not section.get("component_customised")
	)


def _shared_definition(component_name: str, expected_category: str) -> dict | None:
	row = frappe.db.get_value(
		"Email Builder Component", component_name, ["definition_json", "category", "component_type", "enabled"], as_dict=True
	)
	if not row or not frappe.utils.cint(row.enabled) or row.component_type != "Section" or row.category != expected_category:
		return None
	try:
		payload = json.loads(row.definition_json or "{}")
	except ValueError:
		return None
	definition = payload.get("definition") if isinstance(payload.get("definition"), dict) else payload
	return definition if isinstance(definition, dict) and definition.get("columns") else None


def refresh_shared_sections(schema: dict) -> dict:
	"""Replace every linked Header or Footer row by the current shared version. Returns the schema to use."""
	from .schema import validate_schema

	changed = False
	sections = []
	for section in schema.get("sections") or []:
		if is_linked(section):
			definition = _shared_definition(section["saved_component"], section["saved_component_category"])
			if definition:
				fresh = copy.deepcopy(definition)
				fresh["id"] = section.get("id")
				fresh["saved_component"] = section["saved_component"]
				fresh["saved_component_category"] = section["saved_component_category"]
				fresh["component_customised"] = False
				if fresh != section:
					changed = True
				sections.append(fresh)
				continue
		sections.append(section)
	if not changed:
		return schema
	return validate_schema({**schema, "sections": sections})


def propagate_component_change(doc, method=None) -> None:
	"""EM-17: a changed shared Header/Footer/CTA/Social reaches every unsent e-mail still linked to it.

	Without this, linked rows refreshed only when an e-mail was opened in the builder, so an
	e-mail scheduled or used in a workflow kept sending the old section. Sent campaigns keep
	their frozen snapshot and do not change.
	"""
	if doc.get("component_type") != "Section" or doc.get("category") not in SHARED_CATEGORIES:
		return
	before = doc.get_doc_before_save()
	if before and before.get("definition_json") == doc.get("definition_json") and before.get("enabled") == doc.get("enabled"):
		return
	frappe.enqueue(
		"finbyzreach.email_template_builder.shared_sections.recompile_linked_templates",
		component=doc.name,
		queue="long",
		enqueue_after_commit=True,
		# Every committed revision needs a pass, including edits during a running job.
		job_id=f"shared-section:{doc.name}:{frappe.generate_hash(length=16)}",
	)


def recompile_linked_templates(component: str | None = None) -> list[str]:
	"""Recompile visual templates and masters whose linked rows use this saved section.

	With no component, every visual template and master is recompiled from its stored design,
	so compiler improvements (dark mode, Outlook markup, alt text) reach e-mails nobody re-saved.
	"""
	import hashlib

	from .compiler import compile_schema
	from .constants import BUILDER_TARGET_DOCTYPES
	from .schema import validate_schema

	updated = []
	needle = json.dumps(component) if component else ""
	for doctype in sorted(BUILDER_TARGET_DOCTYPES):
		meta = frappe.get_meta(doctype)
		if not meta.has_field("custom_builder_schema"):
			continue
		names = frappe.get_all(
			doctype,
			filters={"custom_builder_mode": "Visual", **({"custom_builder_schema": ["like", f"%{needle}%"]} if component else {})},
			pluck="name",
			limit_page_length=0,
		)
		for name in names:
			doc = frappe.get_doc(doctype, name, for_update=True)
			try:
				schema = validate_schema(doc.get("custom_builder_schema"))
				if component and not any(is_linked(section) and section.get("saved_component") == component for section in schema.get("sections") or []):
					continue
				compiled = compile_schema(refresh_shared_sections(schema), doc.get("custom_preheader_text") or "", normalized=True)
				if compiled["html"] == doc.get("response_html"):
					continue
				doc.custom_builder_schema = json.dumps(compiled["schema"], separators=(",", ":"))
				doc.custom_builder_content_hash = hashlib.sha256(str(compiled["html"]).encode()).hexdigest()
				doc.response_html = compiled["html"]
				doc.use_html = 1
				doc.flags.ignore_permissions = True
				doc.save()
				updated.append(f"{doctype}:{name}")
			except Exception:
				frappe.log_error(title=f"Visual e-mail {doctype} {name} not recompiled", message=frappe.get_traceback())
	return updated
