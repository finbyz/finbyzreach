from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .. import ai
from ..ai import accept_ai_proposal, generate_ai_rewrite, get_builder_ai_settings
from ..constants import LAYOUTS
from ..schema import validate_schema


def _schema(layout="1", block_type="text"):
	count = len(LAYOUTS[layout])
	content = {
		"text": {"html": "<p>Hello there</p>"},
		"button": {"text": "Open", "href": "https://example.com"},
	}[block_type]
	return {
		"version": 1,
		"settings": {},
		"sections": [
			{
				"id": "section-1",
				"layout": layout,
				"columns": [
					{"id": f"column-{index}", "blocks": [{"id": f"block-{index}", "type": block_type, "content": content}]}
					for index in range(count)
				],
			}
		],
	}


def _two_section_schema():
	schema = _schema()
	first = schema["sections"][0]
	first["id"] = "section-a"
	first["columns"][0]["blocks"][0]["content"]["html"] = "<p>Keep this untouched</p>"
	second = _schema()["sections"][0]
	second["id"] = "section-b"
	second["columns"][0]["id"] = "column-b"
	second["columns"][0]["blocks"][0]["id"] = "block-b"
	second["columns"][0]["blocks"][0]["content"]["html"] = "<p>Rewrite me</p>"
	schema["sections"].append(second)
	return schema


def _email_template():
	name = f"_Test Builder AI {frappe.generate_hash(length=8)}"
	return frappe.get_doc(
		{
			"doctype": "Email Template",
			"name": name,
			"subject": "Blank",
			"use_html": 1,
			"response_html": "<p>original</p>",
			"custom_builder_mode": "Visual",
			"custom_builder_schema": json.dumps(_schema()),
		}
	).insert(ignore_permissions=True)


ENABLED_SETTINGS = frappe._dict(
	{"custom_enable_email_builder_ai": 1, "custom_email_builder_rewrite_agent": "Test Rewrite Agent"}
)


class TestEmailBuilderAI(IntegrationTestCase):
	def setUp(self):
		self.template = _email_template()

	def _generate(self, payload, prompt="Make it friendlier", metadata=None):
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS), patch.object(
			ai, "_invoke_rewrite_agent", return_value=payload
		):
			return generate_ai_rewrite(
				self.template.name,
				json.dumps(_schema()),
				metadata=metadata or {"subject": "Original subject", "preheader": ""},
				prompt=prompt,
			)

	def test_returns_validated_and_compiled_proposal(self):
		payload = {
			"summary": "Warmer tone",
			"schema": _schema("1", "text"),
			"subject": "A warmer subject",
			"change_notes": ["Softened the greeting"],
			"warnings": [],
		}
		result = self._generate(payload)
		self.assertEqual(result["summary"], "Warmer tone")
		self.assertEqual(result["metadata"]["subject"], "A warmer subject")
		self.assertIn("<", result["preview_html"])  # compiled HTML
		self.assertTrue(result["schema"]["sections"])  # normalized schema present
		self.assertIn("before_html", result)

	def test_accepts_json_string_with_code_fences(self):
		payload = "```json\n" + json.dumps({"summary": "ok", "schema": _schema("1", "text")}) + "\n```"
		result = self._generate(payload)
		self.assertEqual(result["summary"], "ok")
		self.assertTrue(result["schema"]["sections"])

	def test_rejects_unsupported_block(self):
		bad = _schema("1", "text")
		bad["sections"][0]["columns"][0]["blocks"][0]["type"] = "iframe"
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._generate({"summary": "bad", "schema": bad})

	def test_empty_prompt_is_rejected(self):
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._generate({"summary": "x", "schema": _schema()}, prompt="   ")

	def test_disabled_when_not_configured(self):
		with patch.object(ai, "_settings", return_value=frappe._dict()):
			with self.assertRaises(frappe.exceptions.ValidationError):
				generate_ai_rewrite(self.template.name, json.dumps(_schema()), prompt="Hi")

	def test_does_not_mutate_template(self):
		before = frappe.db.get_value("Email Template", self.template.name, "response_html")
		self._generate({"summary": "x", "schema": _schema("1", "text")})
		after = frappe.db.get_value("Email Template", self.template.name, "response_html")
		self.assertEqual(before, after)

	def test_settings_probe(self):
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS):
			probe = get_builder_ai_settings()
		self.assertTrue(probe["enabled"])
		self.assertTrue(probe["rewrite_configured"])

	def test_accept_proposal_is_safe_when_missing(self):
		# Unknown proposal id must not raise.
		self.assertEqual(accept_ai_proposal("does-not-exist")["ok"], False)

	def test_sanitizes_unsupported_tokens_instead_of_failing(self):
		bad = _schema("1", "text")
		bad["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = (
			'<p>Hi {{ get_name() }} {% if vip %}welcome{% endif %}</p>'
		)
		result = self._generate({"summary": "cleaned", "schema": bad})
		# Proposal succeeds (no hard crash) and flags the removal.
		self.assertTrue(result["schema"]["sections"])
		self.assertTrue(any("unsupported dynamic fields" in w.lower() for w in result["warnings"]))
		# The invalid dotted token must not survive into the compiled design.
		self.assertNotIn("get_name", json.dumps(result["schema"]))

	def test_preserves_valid_merge_tokens(self):
		good = _schema("1", "text")
		good["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = '<p>Hi {{ first_name }}</p>'
		result = self._generate({"summary": "kept", "schema": good})
		self.assertIn("{{ first_name }}", json.dumps(result["schema"]))

	def test_rewrite_agent_invoke_supplies_all_prompt_variables(self):
		calls = {}

		class Service:
			def invoke(self, **kwargs):
				calls.update(kwargs)
				return {"schema": _schema(), "summary": "ok"}

		with patch("frappe.db.exists", return_value=True), patch(
			"frappe.get_doc", return_value=frappe._dict(agent_service=Service())
		):
			ai._invoke_rewrite_agent("Test Rewrite Agent", "Rewrite it", {"current_schema": "{}"})

		for key in (
			"query",
			"user_prompt",
			"rewrite_scope",
			"target_section_id",
			"target_section",
			"current_schema",
			"current_settings",
			"subject",
			"preheader",
			"reference_doctype",
			"block_types",
			"layouts",
			"available_images",
			"current_palette",
		):
			self.assertIn(key, calls)

	def test_agent_context_exposes_existing_images_and_palette(self):
		schema = {
			"version": 1,
			"settings": {"content_background": "#0b5cff", "text_color": "#111827"},
			"sections": [
				{
					"id": "s1",
					"layout": "1",
					"columns": [
						{"id": "c1", "blocks": [{"id": "b1", "type": "image", "content": {"src": "/files/logo.png", "alt": "Logo"}}]}
					],
				}
			],
		}
		context = ai._agent_context(frappe._dict(), schema, {}, "x")
		self.assertIn("/files/logo.png", context["available_images"])
		self.assertIn("#0b5cff", context["current_palette"])

	def test_saved_component_reference_survives_validation(self):
		schema = _schema("1", "text")
		schema["sections"][0]["saved_component"] = "Hero Banner"
		validated = validate_schema(schema)
		self.assertEqual(validated["sections"][0]["saved_component"], "Hero Banner")

	def test_saved_component_absent_when_not_set(self):
		validated = validate_schema(_schema("1", "text"))
		self.assertNotIn("saved_component", validated["sections"][0])

	def test_sample_prompts_served_from_doctype(self):
		title = f"_Test Chip {frappe.generate_hash(length=6)}"
		frappe.get_doc(
			{"doctype": "Email Builder AI Prompt", "title": title, "prompt_type": "Sample", "enabled": 1, "prompt": "Do the thing"}
		).insert(ignore_permissions=True)
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS):
			probe = get_builder_ai_settings()
		titles = [row["title"] for row in probe["sample_prompts"]]
		self.assertIn(title, titles)
	def test_section_rewrite_replaces_only_selected_section(self):
		current = _two_section_schema()
		proposal_section = _schema()["sections"][0]
		proposal_section["id"] = "agent-new-id"
		proposal_section["columns"][0]["blocks"][0]["content"]["html"] = "<p>Rewritten selected row</p>"
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS), patch.object(
			ai, "_invoke_rewrite_agent", return_value={"summary": "Row updated", "schema": {"sections": [proposal_section]}}
		):
			result = generate_ai_rewrite(
				self.template.name,
				json.dumps(current),
				metadata={"subject": "Original subject", "preheader": "Original preview"},
				prompt="Improve selected row",
				scope="section",
				section_id="section-b",
			)

		self.assertEqual(result["scope"], "section")
		self.assertEqual(result["target_id"], "section-b")
		self.assertIn("Keep this untouched", result["schema"]["sections"][0]["columns"][0]["blocks"][0]["content"]["html"])
		self.assertEqual(result["schema"]["sections"][1]["id"], "section-b")
		self.assertIn("Rewritten selected row", result["schema"]["sections"][1]["columns"][0]["blocks"][0]["content"]["html"])
		self.assertEqual(result["metadata"]["subject"], "Original subject")
		self.assertEqual(result["metadata"]["preheader"], "Original preview")

	def test_section_rewrite_rejects_multiple_sections(self):
		current = _two_section_schema()
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS), patch.object(
			ai, "_invoke_rewrite_agent", return_value={"summary": "bad", "schema": {"sections": [_schema()["sections"][0], _schema()["sections"][0]]}}
		):
			with self.assertRaises(frappe.exceptions.ValidationError):
				generate_ai_rewrite(self.template.name, json.dumps(current), prompt="x", scope="section", section_id="section-b")

	def test_section_rewrite_requires_existing_section(self):
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS):
			with self.assertRaises(frappe.exceptions.ValidationError):
				generate_ai_rewrite(self.template.name, json.dumps(_schema()), prompt="x", scope="section", section_id="missing")

