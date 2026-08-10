from __future__ import annotations

import json

import frappe
from frappe.model.document import Document

from ...compiler import compile_schema
from ...schema import validate_component


class EmailBuilderComponent(Document):
	def validate(self):
		definition = validate_component(self.definition_json)
		self.definition_json = json.dumps(definition, separators=(",", ":"))
		self.schema_version = 1
		if definition["component_type"] == "Section":
			schema = {"version": 1, "settings": {}, "sections": [definition["definition"]]}
		else:
			preview_id = frappe.generate_hash(length=10)
			schema = {
				"version": 1,
				"settings": {},
				"sections": [
					{
						"id": f"preview-{preview_id}",
						"layout": "1",
						"columns": [{"id": f"preview-column-{preview_id}", "blocks": [definition["definition"]]}],
					}
				],
			}
		self.preview_html = compile_schema(schema)["html"]
