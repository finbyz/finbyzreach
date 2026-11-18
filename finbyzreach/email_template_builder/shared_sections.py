"""Header and footer: rows linked to a shared saved Header or Footer block.

An email can use a saved block of category Header or Footer. While the row is not customised it always
shows the current shared version, so a change to the saved block reaches the email when it is next opened
or saved. "Customise in this email only" cuts the link for that email; "Reset" reconnects it.
"""
from __future__ import annotations

import copy
import json

import frappe

SHARED_CATEGORIES = {"Header", "Footer"}


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
