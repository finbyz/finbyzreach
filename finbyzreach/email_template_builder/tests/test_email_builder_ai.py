from __future__ import annotations

import json
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase

from .. import ai
from ..ai import accept_ai_proposal, create_template_with_ai, generate_ai_rewrite, get_builder_ai_settings
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

	def test_coerces_unsupported_block_to_text(self):
		bad = _schema("1", "text")
		bad["sections"][0]["columns"][0]["blocks"][0]["type"] = "iframe"
		result = self._generate({"summary": "ok", "schema": bad})
		self.assertEqual(result["schema"]["sections"][0]["columns"][0]["blocks"][0]["type"], "text")

	def test_rejects_empty_blocks_schema(self):
		empty = _schema("1", "text")
		empty["sections"][0]["columns"][0]["blocks"] = []
		with self.assertRaises(frappe.exceptions.ValidationError):
			self._generate({"summary": "bad", "schema": empty})

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
			"frappe.get_doc", return_value=frappe._dict(agent_service=Service(), messages=[frappe._dict(content="hello {user_prompt}")])
		):
			ai._invoke_rewrite_agent("Test Rewrite Agent", "Rewrite it", {"current_schema": "{}"})

		for key in (
			"query",
			"user_prompt",
			"current_schema",
			"current_settings",
			"subject",
			"preheader",
			"reference_doctype",
			"block_types",
			"layouts",
			"available_images",
			"current_palette",
			"chat_history",
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

	def test_create_template_with_ai_creates_new_record_and_chat(self):
		generated_schema = _schema("1", "text")
		with patch.object(ai, "_settings", return_value=ENABLED_SETTINGS), patch.object(
			ai,
			"_invoke_rewrite_agent",
			return_value={
				"summary": "Brand new design",
				"change_notes": ["Created layout from prompt"],
				"subject": f"Welcome Test {frappe.generate_hash(length=4)}",
				"schema": generated_schema,
			},
		):
			result = create_template_with_ai(
				prompt="Create a welcoming email for new users",
				template_name=f"_Test New AI {frappe.generate_hash(length=6)}",
			)

		self.assertTrue(result.get("name"))
		self.assertIn("/builder?template=", result.get("route"))
		self.assertTrue(frappe.db.exists("Email Template", result["name"]))

		doc = frappe.get_doc("Email Template", result["name"])
		self.assertEqual(doc.custom_builder_mode, "Visual")
		self.assertIn("Hello there", doc.response_html)

		# Verify AI chat history was initialized
		chat = ai._get_saved_chat_history(result["name"])
		self.assertEqual(len(chat), 2)
		self.assertEqual(chat[0]["role"], "user")
		self.assertEqual(chat[1]["role"], "assistant")
		self.assertEqual(chat[1]["status"], "accepted")

		# Cleanup
		frappe.delete_doc("Email Template", result["name"], ignore_permissions=True, force=True)

	def test_schema_version_coerced_gracefully(self):
		for ver in (2, "1", "1.0", "v1", "2.0"):
			res = validate_schema({"version": ver, "settings": {}, "sections": []})
			self.assertEqual(res["version"], 1)

	def test_settings_coerced_gracefully(self):
		for bad_settings in ("default", "{}", None, [], True, 123):
			res = validate_schema({"version": 1, "settings": bad_settings, "sections": []})
			self.assertIsInstance(res["settings"], dict)
			self.assertEqual(res["settings"]["content_width"], 600)



class TestUnparsedCompletionRecovery(IntegrationTestCase):
	"""A strict structured-output parse must not lose a usable design.

	validate_schema coerces every field independently, so a completion the
	PydanticOutputParser rejects is still safe to use.
	"""

	def _exc(self, **kwargs):
		from langchain_core.exceptions import OutputParserException
		return OutputParserException(**kwargs)

	def test_recovers_json_from_llm_output(self):
		payload = '{"summary": "ok", "schema": {"version": 1, "sections": []}}'
		recovered = ai._recover_unparsed_completion(
			self._exc(error="bad", llm_output=payload)
		)
		self.assertEqual(json.loads(recovered)["summary"], "ok")

	def test_recovers_json_from_the_message_when_llm_output_is_absent(self):
		payload = '{"summary": "ok", "schema": {"version": 1}}'
		recovered = ai._recover_unparsed_completion(
			self._exc(error=f"Failed to parse DynamicModel from completion {payload}")
		)
		self.assertEqual(json.loads(recovered)["summary"], "ok")

	def test_returns_none_for_an_unrelated_exception(self):
		self.assertIsNone(ai._recover_unparsed_completion(ValueError("boom")))

	def test_returns_none_when_there_is_no_json_to_salvage(self):
		self.assertIsNone(
			ai._recover_unparsed_completion(self._exc(error="bad", llm_output="I refuse."))
		)

	def test_returns_none_for_malformed_json(self):
		self.assertIsNone(
			ai._recover_unparsed_completion(self._exc(error="bad", llm_output="{not json,,,}"))
		)
