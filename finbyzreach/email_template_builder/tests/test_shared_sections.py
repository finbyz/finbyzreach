"""Header and footer rows that follow a shared saved block until customised."""
from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .. import shared_sections
from ..schema import validate_schema
from .test_email_template_builder import _schema

SHARED = {"id": "x", "layout": "1", "columns": [{"id": "c", "blocks": [{"id": "b", "type": "text", "content": {"html": "<p>Shared header v2</p>"}}]}]}


def _component(**values):
	return frappe._dict({"definition_json": json.dumps({"definition": SHARED}), "category": "Header", "component_type": "Section", "enabled": 1, **values})


def _email(**section_values):
	schema = _schema("1", "text")
	schema["sections"][0].update({"saved_component": "Megasol header", "saved_component_category": "Header", **section_values})
	return validate_schema(schema)


def _texts(schema):
	return [block["content"].get("html") for section in schema["sections"] for column in section["columns"] for block in column["blocks"]]


class SharedSectionsTest(IntegrationTestCase):
	def test_the_link_and_the_customised_flag_survive_validation_only_for_header_and_footer(self):
		section = _email()["sections"][0]
		self.assertEqual((section["saved_component_category"], section["component_customised"]), ("Header", False))
		plain = _email(saved_component_category="Content")["sections"][0]
		self.assertNotIn("saved_component_category", plain)
		self.assertTrue(_email(component_customised=True)["sections"][0]["component_customised"])

	def test_a_linked_row_shows_the_current_shared_version(self):
		with patch.object(frappe.db, "get_value", return_value=_component()):
			schema = shared_sections.refresh_shared_sections(_email())
		self.assertEqual(len(_texts(schema)), 1)
		self.assertIn("Shared header v2", _texts(schema)[0])
		section = schema["sections"][0]
		self.assertEqual(section["saved_component"], "Megasol header")
		self.assertFalse(section["component_customised"])

	def test_a_customised_row_keeps_its_own_content(self):
		own = _texts(_email(component_customised=True))
		with patch.object(frappe.db, "get_value", return_value=_component()):
			schema = shared_sections.refresh_shared_sections(_email(component_customised=True))
		self.assertEqual(_texts(schema), own)
		self.assertFalse(any("Shared header v2" in (text or "") for text in _texts(schema)))

	def test_nothing_changes_when_the_shared_block_is_gone_disabled_or_another_category(self):
		own = _texts(_email())
		for row in (None, _component(enabled=0), _component(category="Footer"), _component(component_type="Block")):
			with patch.object(frappe.db, "get_value", return_value=row):
				self.assertEqual(_texts(shared_sections.refresh_shared_sections(_email())), own)

	def test_the_same_shared_row_twice_gets_unique_ids(self):
		schema = _email()
		schema["sections"].append({**json.loads(json.dumps(schema["sections"][0])), "id": "second"})
		with patch.object(frappe.db, "get_value", return_value=_component()):
			result = shared_sections.refresh_shared_sections(schema)
		ids = [node["id"] for section in result["sections"] for node in [section] + section["columns"]]
		self.assertEqual(len(ids), len(set(ids)))
