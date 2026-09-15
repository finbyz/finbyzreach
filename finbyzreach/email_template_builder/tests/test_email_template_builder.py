from __future__ import annotations

import json
from copy import deepcopy
from unittest.mock import patch

import frappe
from frappe.tests import IntegrationTestCase
from frappe.utils import get_url

from ..api import _compiled_subject, _content_hash, _validate_reference_usage, attach_builder_image, create_visual_template, get_link_merge_fields, get_merge_fields, list_builder_images, list_components, list_revisions, load_builder, load_component, render_preview, render_revision_preview, restore_revision, save_builder, save_component, send_test_email, switch_to_raw_html
from ..compiler import compile_schema
from ..constants import BLOCK_TYPES, EMAIL_TEMPLATE_MASTER_DOCTYPE, LAYOUTS, MAX_COMPONENT_BYTES, MAX_METADATA_BYTES, MAX_SCHEMA_BYTES
from ..library import create_email_from_master
from ..schema import validate_schema
from ..targets import normalize_template_doctype


def _schema(layout, block_type):
	count = len(LAYOUTS[layout])
	content = {
		"text": {"html": '<p>Hello {{ first_name|default("Friend", true) }}</p>'},
		"image": {"src": "/files/example.png", "alt": "Example"},
		"button": {"text": "Open", "href": "https://example.com"},
		"divider": {"style": "dashed", "thickness": 2},
		"spacer": {"height": 20},
		"social": {"items": [{"platform": "LinkedIn", "href": "https://linkedin.com"}]},
		"preview_url": {"text": "View online"},
		"code": {"html": '<p style="color:#2563eb">Code</p>'},
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


def _email_template(name_prefix="_Test Builder Template", **values):
	name = f"{name_prefix} {frappe.generate_hash(length=8)}"
	base = {
		"doctype": "Email Template",
		"name": name,
		"subject": "Blank",
		"use_html": 1,
		"response_html": "",
		"custom_builder_mode": "Raw HTML",
	}
	base.update(values)
	return frappe.get_doc(base).insert(ignore_permissions=True)


def _image_file(file_name, *, is_private=0, attached_to_doctype=None, attached_to_name=None, file_size=None):
	# Frappe File validates and writes local content during insert. Supplying content
	# keeps image-library tests self-contained instead of pointing at missing /files paths.
	doc = frappe.get_doc(
		{
			"doctype": "File",
			"file_name": file_name,
			"content": b"email-builder-test-image",
			"is_private": is_private,
			"attached_to_doctype": attached_to_doctype,
			"attached_to_name": attached_to_name,
		}
	)
	doc.insert(ignore_permissions=True)
	if file_size is not None:
		frappe.db.set_value("File", doc.name, "file_size", file_size, update_modified=False)
		doc.reload()
	return doc


class TestEmailTemplateBuilder(IntegrationTestCase):
	def test_every_layout_and_block_compiles(self):
		for layout in LAYOUTS:
			for block_type in BLOCK_TYPES:
				with self.subTest(layout=layout, block_type=block_type):
					compiled = compile_schema(_schema(layout, block_type), "Preview text")
					self.assertIn("<table", compiled["html"])
					self.assertIn("Preview text", compiled["html"])
					self.assertEqual(compiled["schema"]["sections"][0]["layout"], layout)

	def test_schema_normalizes_defaults_and_is_json_safe(self):
		schema = validate_schema(_schema("1/3:2/3", "text"))
		self.assertEqual(schema["version"], 1)
		self.assertEqual(len(schema["sections"][0]["columns"]), 2)
		json.dumps(schema)

	def test_social_module_normalizes_and_compiles_display_controls(self):
		schema = _schema("1", "social")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"].update(
			{
				"display": "both",
				"icon_shape": "rounded",
				"icon_size": 28,
				"item_spacing": 14,
				"items": [
					{"platform": "LinkedIn", "href": "https://linkedin.com", "label": "Connect"},
					{"platform": "YouTube", "href": "https://youtube.com", "label": "Watch"},
				],
			}
		)
		block["style"] = {"align": "center", "font_color": "#123456"}
		compiled = compile_schema(schema)
		content = compiled["schema"]["sections"][0]["columns"][0]["blocks"][0]["content"]
		self.assertEqual(content["display"], "both")
		self.assertEqual(content["icon_shape"], "rounded")
		self.assertEqual(content["icon_size"], 28)
		self.assertEqual(content["item_spacing"], 14)
		self.assertEqual(content["items"][0]["label"], "Connect")
		self.assertIn("Connect", compiled["html"])
		self.assertIn("Watch", compiled["html"])
		self.assertIn("border-radius:6px", compiled["html"])
		self.assertIn("margin-right:14px", compiled["html"])
		self.assertIn("color:#123456", compiled["html"])
		self.assertIn("text-align:center", compiled["html"])

		block["content"]["display"] = "text"
		text_only = compile_schema(schema)
		self.assertNotIn("/assets/finbyzreach/email_builder/social/", text_only["html"])
		self.assertIn("Connect", text_only["plain_text"])

	def test_validated_schema_compiles_to_the_exact_same_output(self):
		"""Save/preview paths compile validated schemas without re-normalising them."""
		raw = _schema("1/2:1/2", "text")
		raw["settings"].update({"content_width": 730, "section_padding": "8px"})
		raw["sections"][0]["columns"][0]["blocks"][0]["style"] = {"padding": {"top": "6px", "bottom": "4px"}}
		validated = validate_schema(raw)
		from_raw = compile_schema(raw, "Preview")
		from_validated = compile_schema(validated, "Preview", normalized=True)
		self.assertEqual(from_validated["schema"], from_raw["schema"])
		self.assertEqual(from_validated["html"], from_raw["html"])
		self.assertEqual(from_validated["plain_text"], from_raw["plain_text"])

	def test_tokens_render_with_root_or_doc_context_and_escape_html(self):
		html = compile_schema(_schema("1", "text"))["html"]
		root = frappe.render_template(html, {"first_name": "<b>Root</b>"})
		doc = frappe.render_template(html, {"doc": {"first_name": "<i>Document</i>"}})
		frappe_dict_doc = frappe.render_template(html, {"doc": frappe._dict(first_name="Frappe context")})
		fallback = frappe.render_template(html, {})
		self.assertIn("&lt;b&gt;Root&lt;/b&gt;", root)
		self.assertIn("&lt;i&gt;Document&lt;/i&gt;", doc)
		self.assertIn("Frappe context", frappe_dict_doc)
		self.assertIn("Friend", fallback)
		self.assertNotIn("<b>Root</b>", root)

	def test_linked_tokens_render_from_the_declared_frappe_link(self):
		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = (
			'<p>{{ lead_owner.full_name|default("Team", true) }}</p>'
		)
		html = compile_schema(schema)["html"]
		rendered = frappe.render_template(
			html,
			{"doc": frappe._dict(doctype="Lead", lead_owner="Administrator")},
		)
		expected = frappe.db.get_value("User", "Administrator", "full_name") or "Team"
		self.assertIn(expected, rendered)

	def test_rich_text_preserves_content_lines_and_removes_accidental_blank_lines(self):
		schema = _schema("1", "text")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"]["html"] = "First line<div>Second line</div><div><br></div><div>Fourth line</div>"
		compiled = compile_schema(schema)
		normalized_html = compiled["schema"]["sections"][0]["columns"][0]["blocks"][0]["content"]["html"]
		self.assertIn("<div>Second line</div>", normalized_html)
		self.assertNotIn("<div><br></div>", normalized_html)
		self.assertIn("<div>Fourth line</div>", compiled["html"])

	def test_rich_text_trims_accidental_outer_contenteditable_blanks(self):
		schema = _schema("1", "text")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"]["html"] = "<p><br></p><p>Hello</p><div><br></div><p>World</p>"
		compiled = compile_schema(schema)
		normalized_html = compiled["schema"]["sections"][0]["columns"][0]["blocks"][0]["content"]["html"]
		self.assertEqual(normalized_html, '<p style="margin:0">Hello</p><p style="margin:0">World</p>')
		self.assertNotIn("<br>", compiled["html"])

	def test_rich_text_paragraphs_have_compact_explicit_email_spacing(self):
		schema = _schema("1", "text")
		compiled = compile_schema(schema)
		normalized_html = compiled["schema"]["sections"][0]["columns"][0]["blocks"][0]["content"]["html"]
		self.assertIn('style="margin:0"', normalized_html)

	def test_subject_tokens_render_for_both_core_context_shapes(self):
		subject = _compiled_subject('Hello {{ first_name|default("Friend", true) }}')
		self.assertLessEqual(len(subject), 140)
		self.assertEqual(frappe.render_template(subject, {"first_name": "Root"}), "Hello Root")
		self.assertEqual(frappe.render_template(subject, {"doc": {"first_name": "Document"}}), "Hello Document")
		self.assertEqual(frappe.render_template(subject, {}), "Hello Friend")
		self.assertRaises(frappe.ValidationError, _compiled_subject, "x" * 141)

	def test_invalid_merge_tokens_have_clear_validation_codes(self):
		cases = (
			("{{}}", "empty_dynamic_field"),
			("{{   }}", "empty_dynamic_field"),
			("{{ 123 }}", "invalid_dynamic_field_syntax"),
			("{{ first-name }}", "invalid_dynamic_field_syntax"),
			("{{ first_name|upper }}", "invalid_dynamic_field_syntax"),
			("{% if doc %}Hello{% endif %}", "unsupported_jinja"),
		)
		for token, code in cases:
			with self.subTest(token=token):
				frappe.local.response.pop("builder_validation", None)
				with self.assertRaises(frappe.ValidationError):
					_compiled_subject(f"Hello {token}")
				self.assertEqual(frappe.local.response.get("builder_validation", {}).get("code"), code)

	def test_invalid_merge_tokens_in_rich_text_are_rejected_before_compile(self):
		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<p>Hello {{ }}</p>"
		frappe.local.response.pop("builder_validation", None)
		with self.assertRaises(frappe.ValidationError):
			compile_schema(schema)
		self.assertEqual(frappe.local.response.get("builder_validation", {}).get("code"), "empty_dynamic_field")

	def test_visibility_rules_compile_as_jinja_with_table_row_display(self):
		schema = _schema("1", "text")
		schema["sections"][0]["visibility"] = {
			"device": "mobile",
			"match": "all",
			"conditions": [{"fieldname": "status", "operator": "equals", "value": "Open"}],
		}
		html = compile_schema(schema)["html"]
		self.assertIn("{% if", html)
		self.assertIn('<tr class="etb-mobile-only">', html)
		self.assertNotIn("<span><tr", html)
		self.assertIn("tr.etb-mobile-only{display:table-row!important}", html)
		self.assertIn("Hello", frappe.render_template(html, {"doc": {"status": "Open"}}))
		self.assertNotIn("Hello", frappe.render_template(html, {"doc": {"status": "Closed"}}))

	def test_visibility_rules_support_one_safe_link_field_level(self):
		schema = _schema("1", "text")
		schema["sections"][0]["visibility"] = {
			"device": "both",
			"match": "all",
			"conditions": [{"fieldname": "lead_owner.enabled", "operator": "equals", "value": "1"}],
		}
		_validate_reference_usage(schema, "", "", "Lead")
		html = compile_schema(schema)["html"]
		self.assertIn('ebv("lead_owner.enabled"', html)
		self.assertIn(
			"Hello",
			frappe.render_template(
				html,
				{"doc": frappe._dict(doctype="Lead", lead_owner="Administrator")},
			),
		)
		self.assertNotIn(
			"Hello",
			frappe.render_template(
				html,
				{"doc": frappe._dict(doctype="Lead", lead_owner="")},
			),
		)

	def test_section_responsive_layout_controls_compile(self):
		schema = _schema("1/2:1/2", "text")
		section = schema["sections"][0]
		section.update({"vertical_align": "middle", "mobile_stack": "reverse"})
		compiled = compile_schema(schema)
		self.assertEqual(compiled["schema"]["sections"][0]["mobile_stack"], "reverse")
		self.assertIn('class="etb-layout etb-stack-reverse"', compiled["html"])
		self.assertIn('class="etb-column"', compiled["html"])
		self.assertIn('valign="middle"', compiled["html"])

		section["mobile_stack"] = "none"
		no_stack_html = compile_schema(schema)["html"]
		self.assertIn('class="etb-layout etb-no-stack"', no_stack_html)
		self.assertNotIn('etb-mobile-layout', no_stack_html)

	def test_all_multi_column_layouts_compile_single_responsive_markup_without_duplicates(self):
		for layout, widths in LAYOUTS.items():
			if len(widths) == 1:
				continue
			with self.subTest(layout=layout, mode="stack"):
				schema = _schema(layout, "text")
				schema["settings"]["content_width"] = 900
				markers = []
				for index, column in enumerate(schema["sections"][0]["columns"]):
					marker = f"{layout}-column-{index}"
					markers.append(marker)
					column["blocks"][0]["content"] = {"html": f"<p>{marker}</p>"}

				html = compile_schema(schema)["html"]
				self.assertIn(".etb-stack .etb-column,.etb-stack-reverse .etb-column{display:block!important;width:100%!important;max-width:100%!important}", html)
				self.assertIn('class="etb-layout etb-stack"', html)
				self.assertNotIn('etb-mobile-layout', html)
				self.assertEqual(html.count('class="etb-column"'), len(widths))
				for marker in markers:
					self.assertEqual(html.count(marker), 1)

			with self.subTest(layout=layout, mode="reverse"):
				schema["sections"][0]["mobile_stack"] = "reverse"
				reverse_html = compile_schema(schema)["html"]
				self.assertIn('class="etb-layout etb-stack-reverse"', reverse_html)
				self.assertNotIn('etb-mobile-layout', reverse_html)
				for marker in markers:
					self.assertEqual(reverse_html.count(marker), 1)

			with self.subTest(layout=layout, mode="none"):
				schema["sections"][0]["mobile_stack"] = "none"
				no_stack_html = compile_schema(schema)["html"]
				self.assertIn('class="etb-layout etb-no-stack"', no_stack_html)
				self.assertNotIn('etb-mobile-layout', no_stack_html)
				for marker in markers:
					self.assertEqual(no_stack_html.count(marker), 1)

	def test_custom_column_widths_are_normalized_and_compiled(self):
		schema = _schema("1/3:1/3:1/3", "text")
		schema["sections"][0]["column_widths"] = [20, 35, 45]
		compiled = compile_schema(schema)
		self.assertEqual(compiled["schema"]["sections"][0]["column_widths"], [20.0, 35.0, 45.0])
		self.assertIn('width="20.000%"', compiled["html"])
		self.assertIn('width="35.000%"', compiled["html"])
		self.assertIn('width="45.000%"', compiled["html"])

	def test_custom_column_widths_reject_invalid_totals_and_bounds(self):
		schema = _schema("1/2:1/2", "text")
		schema["sections"][0]["column_widths"] = [20, 20]
		self.assertRaises(frappe.ValidationError, validate_schema, schema)
		schema["sections"][0]["column_widths"] = [2, 98]
		self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_column_styles_and_button_actions_are_email_safe(self):
		schema = _schema("1/2:1/2", "button")
		schema["sections"][0]["columns"][0]["style"] = {"background": "#ffeeee", "padding": {"top": "12px"}}
		schema["sections"][0]["columns"][0]["blocks"][0]["content"].update({"action": "email", "href": "hello@example.com"})
		compiled = compile_schema(schema)["html"]
		self.assertIn("background-color:#ffeeee", compiled)
		self.assertIn("mailto:hello@example.com", compiled)
		self.assertIn('bgcolor="#2563eb"', compiled)

	def test_resizable_components_compile_to_email_safe_styles(self):
		button = _schema("1", "button")
		button_block = button["sections"][0]["columns"][0]["blocks"][0]
		button_block["style"] = {"width": "55%", "align": "center", "button_padding_x": "30px", "button_padding_y": "14px"}
		button_html = compile_schema(button)["html"]
		self.assertIn("width:55%", button_html)
		self.assertIn('align="center"', button_html)
		self.assertIn("padding:14px 30px", button_html)

		image = _schema("1", "image")
		image_block = image["sections"][0]["columns"][0]["blocks"][0]
		image_block["style"] = {"width": "60%", "align": "right"}
		image_block["content"].update({"height": 240, "preserve_aspect_ratio": False})
		image_html = compile_schema(image)["html"]
		self.assertIn("width:60%", image_html)
		self.assertIn("height:240px", image_html)
		self.assertIn("text-align:right", image_html)
		self.assertIn("margin-left:auto", image_html)
		self.assertIn("margin-right:0", image_html)
		self.assertNotIn(' align="right"', image_html)
		self.assertNotIn(' align="left"', image_html)

		social = _schema("1", "social")
		social_block = social["sections"][0]["columns"][0]["blocks"][0]
		social_block["content"]["icon_size"] = 28
		social_block["style"] = {"color": "#0891b2"}
		social_html = compile_schema(social)["html"]
		self.assertIn("width:28px", social_html)
		self.assertIn("background:#0891b2", social_html)
		self.assertIn("LinkedIn", social_html)
		self.assertIn("/assets/finbyzreach/email_builder/social/linkedin.svg", social_html)
		self.assertIn("<img", social_html)
		self.assertNotIn("<svg", social_html)

	def test_every_block_type_preserves_resized_width(self):
		for block_type in BLOCK_TYPES:
			with self.subTest(block_type=block_type):
				schema = _schema("1", block_type)
				block = schema["sections"][0]["columns"][0]["blocks"][0]
				block["style"] = {"width": "63%", "align": "right"}
				compiled = compile_schema(schema)
				self.assertEqual(compiled["schema"]["sections"][0]["columns"][0]["blocks"][0]["style"]["width"], "63%")
				self.assertIn("width:63%", compiled["html"])

	def test_visual_styles_and_settings_are_present_in_compiled_html(self):
		schema = _schema("1", "text")
		schema["settings"].update({"link_decoration": "none", "section_padding": "7px"})
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["style"] = {
			"color": "#123456",
			"height": "80px",
			"border_width": "2px",
			"border_color": "#abcdef",
			"border_style": "dashed",
			"radius": "6px",
		}
		html = compile_schema(schema)["html"]
		for expected in (
			"color:#123456",
			"height:80px",
			"border-width:2px",
			"border-color:#abcdef",
			"border-style:dashed",
			"border-radius:6px",
			"padding:7px",
			".etb-content a{color:#2563eb;text-decoration:none}",
		):
			self.assertIn(expected, html)

		button = _schema("1", "button")
		button["sections"][0]["columns"][0]["blocks"][0]["style"] = {
			"border_width": "3px",
			"border_color": "#123456",
			"border_style": "dotted",
		}
		self.assertIn("border:3px dotted #123456", compile_schema(button)["html"])

	def test_image_alignment_background_and_divider_color_compile_consistently(self):
		image = _schema("1", "image")
		image_block = image["sections"][0]["columns"][0]["blocks"][0]
		image_block["style"] = {"background": "#971717", "align": "center", "width": "50%"}
		image_html = compile_schema(image)["html"]
		self.assertIn("background-color:#971717", image_html)
		self.assertIn("text-align:center", image_html)
		self.assertIn("margin-left:auto", image_html)
		self.assertIn("margin-right:auto", image_html)

		divider = _schema("1", "divider")
		divider_block = divider["sections"][0]["columns"][0]["blocks"][0]
		divider_block["style"] = {"border_color": "#ff0000", "width": "40%", "align": "right"}
		divider_html = compile_schema(divider)["html"]
		self.assertIn("border-top:2px dashed #ff0000", divider_html)
		self.assertEqual(divider_html.count("width:40%"), 1)
		self.assertIn("margin-left:auto", divider_html)
		self.assertIn("margin-right:0", divider_html)
		self.assertNotIn("text-align:right;width:40%", divider_html)

		divider_block["style"]["align"] = "center"
		center_divider_html = compile_schema(divider)["html"]
		self.assertIn("margin-left:auto", center_divider_html)
		self.assertIn("margin-right:auto", center_divider_html)

	def test_invalid_css_keywords_and_private_file_buttons_are_rejected(self):
		for path, value in (("padding", {"top": "auto"}), ("font_size", "auto"), ("width", "none")):
			with self.subTest(path=path):
				schema = _schema("1", "text")
				schema["sections"][0]["columns"][0]["blocks"][0]["style"] = {path: value}
				self.assertRaises(frappe.ValidationError, validate_schema, schema)

		button = _schema("1", "button")
		button["sections"][0]["columns"][0]["blocks"][0]["content"].update({"action": "file", "href": "/private/files/secret.pdf"})
		self.assertRaises(frappe.ValidationError, validate_schema, button)
		button["sections"][0]["columns"][0]["blocks"][0]["content"]["href"] = get_url("/private/files/secret.pdf")
		self.assertRaises(frappe.ValidationError, validate_schema, button)

		image = _schema("1", "image")
		image["sections"][0]["columns"][0]["blocks"][0]["content"]["src"] = get_url("/private/files/secret.png")
		self.assertRaises(frappe.ValidationError, validate_schema, image)

	def test_relative_recipient_urls_compile_as_absolute_urls(self):
		button = _schema("1", "button")
		button["sections"][0]["columns"][0]["blocks"][0]["content"].update({"action": "file", "href": "/files/guide.pdf"})
		compiled_button = compile_schema(button)
		self.assertIn(get_url("/files/guide.pdf"), compiled_button["html"])
		self.assertIn(get_url("/files/guide.pdf"), compiled_button["plain_text"])

		image = _schema("1", "image")
		image["sections"][0]["columns"][0]["blocks"][0]["content"].update(
			{"src": "/files/picture.png", "href": "/products"}
		)
		compiled_image = compile_schema(image)["html"]
		self.assertIn(get_url("/files/picture.png"), compiled_image)
		self.assertIn(get_url("/products"), compiled_image)

		for block_type in ("text", "code"):
			with self.subTest(block_type=block_type):
				schema = _schema("1", block_type)
				schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = '<a href="/account">Account</a>'
				self.assertIn(get_url("/account"), compile_schema(schema)["html"])

	def test_real_save_persists_exact_compiler_response_html_for_every_layout_and_block(self):
		sections = []
		for section_index, layout in enumerate(LAYOUTS):
			columns = []
			for column_index in range(len(LAYOUTS[layout])):
				blocks = []
				for block_index, block_type in enumerate(sorted(BLOCK_TYPES)):
					base = deepcopy(_schema("1", block_type)["sections"][0]["columns"][0]["blocks"][0])
					base["id"] = f"block-{section_index}-{column_index}-{block_index}"
					base["style"] = {"width": "80%", "align": "center", "color": "#123456"}
					blocks.append(base)
				columns.append({"id": f"column-{section_index}-{column_index}", "blocks": blocks})
			sections.append({"id": f"section-{section_index}", "layout": layout, "columns": columns})
		schema = {
			"version": 1,
			"settings": {"section_padding": "6px", "link_decoration": "none"},
			"sections": sections,
		}
		metadata = {"subject": "All builder cases", "preheader": "Exact response HTML", "reference_doctype": "Contact"}
		expected = compile_schema(schema, metadata["preheader"])
		name = f"_Test Builder Exact HTML {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		result = save_builder(template.name, str(template.modified), json.dumps(schema), json.dumps(metadata))
		template.reload()
		self.assertEqual(template.response_html, expected["html"])
		self.assertEqual(json.loads(template.custom_builder_schema), expected["schema"])
		self.assertEqual(template.custom_builder_content_hash, _content_hash(expected["html"]))
		self.assertEqual(result["content_hash"], _content_hash(template.response_html))
		self.assertEqual(result["bytes"], len(template.response_html.encode()))
		self.assertEqual(load_builder(template.name)["html"], template.response_html)
		self.assertEqual(template.get_formatted_response({"first_name": "Rendered"}), frappe.render_template(expected["html"], {"first_name": "Rendered"}))

	def test_margin_uses_email_safe_wrapper_table_spacing(self):
		schema = _schema("1", "text")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["style"] = {"margin": {"top": "8px", "right": "6px", "bottom": "4px", "left": "2px"}}
		html = compile_schema(schema)["html"]
		self.assertIn("padding:8px 6px 4px 2px", html)
		self.assertIn('<table role="presentation" width="100%"', html)

		section = _schema("1", "text")
		section["sections"][0]["style"] = {"margin": {"top": "12px", "right": "10px", "bottom": "8px", "left": "6px"}}
		section_html = compile_schema(section)["html"]
		self.assertIn("padding:12px 10px 8px 6px", section_html)

	def test_incomplete_drafts_save_with_structured_warnings(self):
		image = _schema("1", "image")
		image["sections"][0]["columns"][0]["blocks"][0]["content"] = {"src": "", "alt": ""}
		compiled_image = compile_schema(image)
		self.assertIn("missing_image", {issue["code"] for issue in compiled_image["issues"]})
		self.assertIn("missing_alt", {issue["code"] for issue in compiled_image["issues"]})
		self.assertEqual(sum(issue["code"] == "missing_image" for issue in compiled_image["issues"]), 1)

		button = _schema("1", "button")
		button["sections"][0]["columns"][0]["blocks"][0]["content"]["href"] = ""
		compiled_button = compile_schema(button)
		self.assertIn("missing_button_url", {issue["code"] for issue in compiled_button["issues"]})

	def test_restricted_code_rejects_active_content_and_unsafe_urls(self):
		for unsafe in (
			"<script>alert(1)</script>",
			'<p onclick="alert(1)">Click</p>',
			'<a href="javascript:alert(1)">Click</a>',
			'<img src="data:image/svg+xml,x">',
			"<iframe src='https://example.com'></iframe>",
		):
			with self.subTest(unsafe=unsafe):
				schema = _schema("1", "code")
				schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = unsafe
				self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_arbitrary_jinja_is_rejected_in_visual_mode(self):
		for value in ("{% for row in rows %}x{% endfor %}", "{{ frappe.get_all('User') }}", "{{ customer.name.first }}"):
			with self.subTest(value=value):
				schema = _schema("1", "text")
				schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = f"<p>{value}</p>"
				self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_unsafe_literal_urls_are_rejected(self):
		for href in ("javascript:alert(1)", "data:text/html,unsafe"):
			with self.subTest(href=href):
				schema = _schema("1", "button")
				schema["sections"][0]["columns"][0]["blocks"][0]["content"]["href"] = href
				self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_full_dynamic_link_is_filtered_to_safe_runtime_urls(self):
		schema = _schema("1", "button")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"]["href"] = '{{ website|default("https://example.com", true) }}'
		html = compile_schema(schema)["html"]
		self.assertIn("email_builder_safe_url", html)
		self.assertIn('href="https://safe.example/path"', frappe.render_template(html, {"website": "https://safe.example/path"}))
		self.assertIn('href="#"', frappe.render_template(html, {"website": "javascript:alert(1)"}))

	def test_dynamic_image_source_remains_rejected(self):
		schema = _schema("1", "image")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["src"] = "{{ image_url }}"
		self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_dynamic_url_path_fragment_is_encoded(self):
		schema = _schema("1", "button")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"]["href"] = "https://example.com/profile/{{ first_name }}"
		html = compile_schema(schema)["html"]
		rendered = frappe.render_template(html, {"first_name": "A B"})
		self.assertIn("https://example.com/profile/A%20B", rendered)

	def test_visual_save_requires_raw_overwrite_confirmation_and_uses_standard_fields(self):
		name = f"_Test Email Builder {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Manual subject",
				"use_html": 1,
				"response_html": "<p>Manual HTML</p>",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		schema = _schema("1", "text")
		metadata = {
			"subject": 'Hello {{ first_name|default("Friend", true) }}',
			"preheader": "Inbox preview",
			"reference_doctype": "Contact",
			"preview_document": "",
		}
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			str(template.modified),
			json.dumps(schema),
			json.dumps(metadata),
		)
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(schema),
			json.dumps(metadata),
			allow_overwrite_html=1,
		)
		template.reload()
		self.assertEqual(template.custom_builder_mode, "Visual")
		self.assertEqual(template.custom_builder_subject_source, metadata["subject"])
		self.assertIn('ebv("first_name"', template.subject)
		self.assertIn("class=\"etb-content\"", template.response_html)
		self.assertEqual(result["content_hash"], template.custom_builder_content_hash)
		self.assertTrue(result["revision"])

		frappe.db.set_value("Email Template", template.name, "response_html", "<p>Manual change after visual save</p>")
		template.reload()
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			str(template.modified),
			json.dumps(schema),
			json.dumps(metadata),
		)

	def test_raw_schema_size_is_checked_before_json_parse(self):
		oversized = "{" + " " * (MAX_SCHEMA_BYTES + 1)
		self.assertRaises(frappe.ValidationError, validate_schema, oversized)

	def test_reference_usage_tolerates_legacy_missing_visibility(self):
		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<p>Hello</p>"
		schema["sections"][0].pop("visibility", None)
		schema["sections"][0]["columns"][0]["blocks"][0].pop("visibility", None)
		_validate_reference_usage(schema, "", "", "")

	def test_revision_stores_html_bytes_and_list_excludes_compiled_html(self):
		name = f"_Test Builder Revision Bytes {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Visual", "preheader": "", "reference_doctype": "Contact"}),
		)
		revision = frappe.get_doc("Email Builder Revision", result["revision"])
		self.assertEqual(revision.html_bytes, len(revision.compiled_html.encode()))
		summaries = list_revisions(template.name)
		self.assertTrue(summaries)
		self.assertEqual(summaries[0]["html_bytes"], revision.html_bytes)
		self.assertNotIn("compiled_html", summaries[0])

	def test_builder_revision_is_immutable(self):
		name = f"_Test Email Builder Revision {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Visual", "preheader": "", "reference_doctype": "Contact"}),
		)
		revision = frappe.get_doc("Email Builder Revision", result["revision"])
		revision.save_note = "Changed"
		self.assertRaises(frappe.ValidationError, revision.save, ignore_permissions=True)

	def test_restore_revision_restores_exact_historical_response_html(self):
		name = f"_Test Builder Restore {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		metadata = {"subject": "First", "preheader": "Historical", "reference_doctype": "Contact"}
		first = save_builder(template.name, str(template.modified), json.dumps(_schema("1", "text")), json.dumps(metadata))
		first_revision = frappe.get_doc("Email Builder Revision", first["revision"])

		template.reload()
		second_schema = _schema("1", "button")
		save_builder(template.name, str(template.modified), json.dumps(second_schema), json.dumps({**metadata, "subject": "Second"}))
		template.reload()
		restore_revision(template.name, first_revision.name, str(template.modified))
		template.reload()
		self.assertEqual(template.response_html, first_revision.compiled_html)
		self.assertEqual(template.custom_builder_content_hash, _content_hash(first_revision.compiled_html))
		self.assertEqual(template.subject, _compiled_subject(first_revision.subject))

	def test_visual_save_requires_an_exact_template_version(self):
		name = f"_Test Builder Concurrency {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		metadata = json.dumps({"subject": "Safe", "preheader": "", "reference_doctype": "Contact"})
		self.assertRaises(frappe.ValidationError, save_builder, template.name, None, json.dumps(_schema("1", "text")), metadata)
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			"2000-01-01 00:00:00",
			json.dumps(_schema("1", "text")),
			metadata,
		)


	def test_second_editor_cannot_overwrite_a_newer_visual_save(self):
		name = f"_Test Builder Two Editors {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		shared_version = str(template.modified)
		metadata = json.dumps({"subject": "Two editors", "preheader": "", "reference_doctype": "Contact"})
		first_schema = _schema("1", "text")
		first_schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<p>First editor wins</p>"
		first = save_builder(template.name, shared_version, json.dumps(first_schema), metadata)
		template.reload()
		winning_html = template.response_html
		winning_schema = json.loads(template.custom_builder_schema)
		revision_count = frappe.db.count("Email Builder Revision", {"template": template.name})

		second_schema = _schema("1", "button")
		with self.assertRaises(frappe.TimestampMismatchError):
			save_builder(template.name, shared_version, json.dumps(second_schema), metadata)

		template.reload()
		self.assertEqual(template.response_html, winning_html)
		self.assertEqual(json.loads(template.custom_builder_schema), winning_schema)
		self.assertEqual(frappe.db.count("Email Builder Revision", {"template": template.name}), revision_count)
		self.assertEqual(first["content_hash"], template.custom_builder_content_hash)
	def test_visual_save_rejects_merge_fields_without_reference_when_validation_is_enabled(self):
		name = f"_Test Builder Reference {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		schema = _schema("1", "text")
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			str(template.modified),
			json.dumps(schema),
			json.dumps({"subject": "Hello {{ first_name }}", "preheader": "", "reference_doctype": "", "validate_dynamic_fields": True}),
		)

	def test_dynamic_field_validation_error_returns_invalid_field_list(self):
		name = f"_Test Builder Invalid Dynamic Fields {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		frappe.local.response.pop("builder_validation", None)
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Hello {{ definitely_missing_field }}", "preheader": "", "reference_doctype": "Contact", "validate_dynamic_fields": True}),
		)
		self.assertEqual(frappe.local.response["builder_validation"]["code"], "invalid_dynamic_fields")
		self.assertEqual(frappe.local.response["builder_validation"]["invalid_fields"], ["definitely_missing_field"])

	def test_generic_visual_save_allows_merge_fields_without_reference_when_validation_is_disabled(self):
		name = f"_Test Builder Generic Dynamic {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		schema = _schema("1", "text")
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(schema),
			json.dumps({"subject": "Hello {{ first_name }}", "preheader": "", "reference_doctype": "", "validate_dynamic_fields": False}),
		)
		template.reload()
		self.assertEqual(template.custom_reference_doctype, "")
		self.assertFalse(result["metadata"]["validate_dynamic_fields"])
		self.assertIn('ebv("first_name"', template.subject)

	def test_component_preview_handles_any_valid_block_id(self):
		definition = {
			"component_type": "Block",
			"category": "Content",
			"definition": {"id": "preview", "type": "text", "content": {"html": "<p>Reusable content</p>"}},
		}
		component = frappe.get_doc(
			{
				"doctype": "Email Builder Component",
				"component_name": f"_Test Component {frappe.generate_hash(length=8)}",
				"component_type": "Block",
				"category": "Content",
				"enabled": 1,
				"definition_json": json.dumps(definition),
			}
		).insert(ignore_permissions=True)
		self.assertIn("Reusable content", component.preview_html)
		self.assertEqual(component.schema_version, 1)

	def test_node_ids_and_css_values_cannot_inject_markup(self):
		schema = _schema("1", "text")
		schema["sections"][0]["id"] = 'bad" onclick="alert(1)'
		self.assertRaises(frappe.ValidationError, validate_schema, schema)

		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["style"] = {"font_family": "Arial; background:url(javascript:1)"}
		self.assertRaises(frappe.ValidationError, validate_schema, schema)

	def test_image_library_lists_and_attaches_public_images_only(self):
		name = f"_Test Builder Images {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Images",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Visual",
			}
		).insert(ignore_permissions=True)
		public_file = _image_file(f"builder-public-{frappe.generate_hash(length=5)}.png", file_size=1234)
		private_file = _image_file(f"builder-private-{frappe.generate_hash(length=5)}.png", is_private=1, file_size=4321)

		public_images = list_builder_images(template.name, scope="public", search="builder-public")
		self.assertTrue(any(row["name"] == public_file.name for row in public_images["rows"]))
		self.assertFalse(any(row["name"] == private_file.name for row in public_images["rows"]))

		attached = attach_builder_image(template.name, public_file.name)
		self.assertEqual(attached["file_url"], public_file.file_url)
		self.assertTrue(attached["is_attached_to_template"])
		template_images = list_builder_images(template.name, scope="template")
		self.assertTrue(any(row["file_url"] == public_file.file_url for row in template_images["rows"]))
		self.assertRaises(frappe.ValidationError, attach_builder_image, template.name, private_file.name)

	def test_builder_metadata_size_is_checked_before_json_parse(self):
		name = f"_Test Builder Metadata Limit {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		oversized_metadata = "{" + " " * (MAX_METADATA_BYTES + 1)
		self.assertRaises(
			frappe.ValidationError,
			save_builder,
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			oversized_metadata,
		)

	def test_load_builder_returns_safe_state_for_corrupt_visual_schema(self):
		name = f"_Test Builder Corrupt Schema {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Saved subject",
				"use_html": 1,
				"response_html": "<p>Existing HTML survives</p>",
				"custom_builder_mode": "Visual",
				"custom_builder_schema": "{broken",
			}
		).insert(ignore_permissions=True)
		state = load_builder(template.name)
		self.assertEqual(state["schema_status"], "invalid")
		self.assertFalse(state["can_save"])
		self.assertEqual(state["html"], "<p>Existing HTML survives</p>")
		self.assertEqual(state["schema"]["sections"], [])

	def test_preview_and_save_share_the_same_normalized_compile_path(self):
		name = f"_Test Builder Preview Save Parity {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		schema = _schema("1", "text")
		metadata = {"subject": "Hello {{ first_name }}", "preheader": "Preview", "reference_doctype": "Contact"}
		preview = render_preview(json.dumps(schema), json.dumps(metadata))
		result = save_builder(template.name, str(template.modified), json.dumps(schema), json.dumps(metadata))
		template.reload()
		self.assertEqual(json.loads(template.custom_builder_schema), result["schema"])
		self.assertIn("Hello", preview["plain_text"])
		self.assertEqual(template.response_html, compile_schema(result["schema"], metadata["preheader"], normalized=True)["html"])

	def test_component_load_returns_normalized_definition(self):
		component = {
			"component_name": f"_Test Component API {frappe.generate_hash(length=8)}",
			"component_type": "Block",
			"category": "Content",
			"definition": {"id": "component-api", "type": "text", "content": {"html": "<p>Saved</p>"}},
		}
		saved = save_component(json.dumps(component))
		loaded = load_component(saved["name"])
		self.assertEqual(loaded["definition"]["component_type"], "Block")
		self.assertEqual(loaded["definition"]["definition"]["type"], "text")
		self.assertIn("definition_json", loaded)

	def test_revision_preview_reports_schema_html_mismatch_without_loading_revision_list_html(self):
		name = f"_Test Builder Revision Mismatch {frappe.generate_hash(length=8)}"
		template = frappe.get_doc(
			{
				"doctype": "Email Template",
				"name": name,
				"subject": "Blank",
				"use_html": 1,
				"response_html": "",
				"custom_builder_mode": "Raw HTML",
			}
		).insert(ignore_permissions=True)
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Visual", "preheader": "", "reference_doctype": "Contact"}),
		)
		revision = frappe.get_doc("Email Builder Revision", result["revision"])
		original_html = revision.compiled_html
		frappe.db.set_value(
			"Email Builder Revision",
			revision.name,
			{
				"compiled_html": original_html.replace("Hello", "Legacy Hello", 1),
				"content_hash": _content_hash(original_html.replace("Hello", "Legacy Hello", 1)),
			},
			update_modified=False,
		)
		preview = render_revision_preview(template.name, revision.name)
		self.assertIn("revision_html_mismatch", {issue["code"] for issue in preview["issues"]})
		summary = list_revisions(template.name)[0]
		self.assertNotIn("compiled_html", summary)

	def test_invalid_api_payloads_do_not_corrupt_saved_template(self):
		template = _email_template(
			"_Test Builder Invalid Payload Safety",
			subject="Stable subject",
			response_html="<p>Stable HTML</p>",
			custom_builder_mode="Visual",
			custom_builder_content_hash=_content_hash("<p>Stable HTML</p>"),
		)
		original = frappe.get_doc("Email Template", template.name).as_dict()
		cases = (
			{"schema": "[]", "metadata": json.dumps({"subject": "Safe", "preheader": "", "reference_doctype": "Contact"})},
			{"schema": "{broken", "metadata": json.dumps({"subject": "Safe", "preheader": "", "reference_doctype": "Contact"})},
			{"schema": json.dumps(_schema("1", "text")), "metadata": "[]"},
			{"schema": json.dumps(_schema("1", "text")), "metadata": "{broken"},
		)
		for case in cases:
			with self.subTest(case=case):
				current = frappe.get_doc("Email Template", template.name)
				with self.assertRaises(frappe.ValidationError):
					save_builder(template.name, str(current.modified), case["schema"], case["metadata"])
				template.reload()
				self.assertEqual(template.response_html, original.response_html)
				self.assertEqual(template.subject, original.subject)
				self.assertEqual(template.custom_builder_content_hash, original.custom_builder_content_hash)

	@patch("finbyzreach.email_template_builder.api.frappe.sendmail")
	def test_send_test_email_matches_preview_compile_path_and_validates_recipient(self, sendmail):
		template = _email_template("_Test Builder Send Preview Parity", subject="Fallback subject")
		schema = _schema("1", "text")
		metadata = {
			"subject": 'Hello {{ first_name|default("Friend", true) }}',
			"preheader": "Inbox preview",
			"reference_doctype": "Contact",
		}
		preview = render_preview(json.dumps(schema), json.dumps(metadata))
		window_number = 987654322
		cache_key = frappe.cache.make_key(f"email-builder-test:{frappe.session.user}:{window_number}")
		frappe.cache.delete_value(cache_key, make_keys=False)
		with patch("finbyzreach.email_template_builder.api.time.time", return_value=window_number * 600):
			result = send_test_email(template.name, json.dumps(schema), json.dumps(metadata), recipient="builder-test@example.com")
		frappe.cache.delete_value(cache_key, make_keys=False)
		self.assertEqual(result["status"], "queued")
		sendmail.assert_called_once()
		kwargs = sendmail.call_args.kwargs
		self.assertEqual(kwargs["subject"], preview["subject"])
		self.assertIn("Friend", kwargs["content"])
		self.assertTrue(kwargs["raw_html"])
		self.assertEqual(kwargs["reference_doctype"], "Email Template")
		self.assertEqual(kwargs["reference_name"], template.name)

		for recipient in ("a@example.com,b@example.com", "not-an-email"):
			with self.subTest(recipient=recipient):
				with self.assertRaises(frappe.ValidationError):
					send_test_email(template.name, json.dumps(schema), json.dumps(metadata), recipient=recipient)

	def test_render_preview_uses_same_metadata_size_guard_as_save(self):
		oversized_metadata = "{" + " " * (MAX_METADATA_BYTES + 1)
		with self.assertRaises(frappe.ValidationError):
			render_preview(json.dumps(_schema("1", "text")), oversized_metadata)

	def test_component_payload_matrix_rejects_invalid_or_oversized_definitions(self):
		valid = {
			"component_name": f"_Test Component Matrix {frappe.generate_hash(length=8)}",
			"component_type": "Block",
			"category": "Content",
			"definition": {"id": "component-matrix", "type": "text", "content": {"html": "<p>OK</p>"}},
		}
		for invalid in (
			{**valid, "component_type": "Widget"},
			{**valid, "category": "Unknown"},
			{**valid, "definition": {"id": "x", "type": "unknown"}},
			[],
			"{" + " " * (MAX_COMPONENT_BYTES + 1),
		):
			with self.subTest(invalid=type(invalid).__name__ if not isinstance(invalid, dict) else invalid.get("component_type") or invalid.get("category")):
				payload = invalid if isinstance(invalid, str) else json.dumps(invalid)
				with self.assertRaises(frappe.ValidationError):
					save_component(payload)

		component = save_component(json.dumps(valid))
		frappe.db.set_value("Email Builder Component", component["name"], "enabled", 0)
		with self.assertRaises(frappe.ValidationError):
			load_component(component["name"])

	def test_image_library_paginates_and_attach_is_idempotent(self):
		template = _email_template("_Test Builder Image Pagination", custom_builder_mode="Visual")
		prefix = f"builder-page-{frappe.generate_hash(length=6)}"
		files = []
		for index in range(3):
			files.append(_image_file(f"{prefix}-{index}.png", file_size=100 + index))

		first_page = list_builder_images(template.name, scope="public", search=prefix, start=0, page_length=2)
		self.assertEqual(len(first_page["rows"]), 2)
		self.assertTrue(first_page["has_more"])
		second_page = list_builder_images(template.name, scope="public", search=prefix, start=first_page["next_start"], page_length=2)
		self.assertEqual(len(second_page["rows"]), 1)
		self.assertFalse(second_page["has_more"])

		first_attach = attach_builder_image(template.name, files[0].name)
		second_attach = attach_builder_image(template.name, files[0].name)
		self.assertEqual(first_attach["file_url"], second_attach["file_url"])
		self.assertEqual(
			frappe.db.count(
				"File",
				{
					"attached_to_doctype": "Email Template",
					"attached_to_name": template.name,
					"file_url": files[0].file_url,
					"is_private": 0,
				},
			),
			1,
		)

	def test_restore_revision_rejects_tampered_html_and_preserves_current_template(self):
		template = _email_template("_Test Builder Tampered Revision Restore")
		result = save_builder(
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Original", "preheader": "", "reference_doctype": "Contact"}),
		)
		revision = frappe.get_doc("Email Builder Revision", result["revision"])
		template.reload()
		current_html = template.response_html
		current_hash = template.custom_builder_content_hash
		frappe.db.set_value("Email Builder Revision", revision.name, "compiled_html", revision.compiled_html + "<!-- tampered -->", update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			restore_revision(template.name, revision.name, str(template.modified))
		template.reload()
		self.assertEqual(template.response_html, current_html)
		self.assertEqual(template.custom_builder_content_hash, current_hash)

	def test_reference_validation_can_be_disabled_but_record_conditions_still_compile(self):
		template = _email_template("_Test Builder Optional Dynamic Validation")
		schema = _schema("1", "text")
		schema["sections"][0]["visibility"] = {
			"device": "both",
			"match": "all",
			"conditions": [{"fieldname": "not_a_real_field", "operator": "equals", "value": "Yes"}],
		}
		metadata = {"subject": "Generic {{ not_a_real_field }}", "preheader": "", "validate_dynamic_fields": False}
		result = save_builder(template.name, str(template.modified), json.dumps(schema), json.dumps(metadata))
		template.reload()
		self.assertFalse(result["metadata"]["validate_dynamic_fields"])
		self.assertIn("not_a_real_field", template.response_html)
		self.assertEqual(template.custom_reference_doctype, "")

	def test_create_visual_template_initializes_visual_mode_and_rejects_duplicate(self):
		name = f"_Test Builder Created Visual {frappe.generate_hash(length=8)}"
		result = create_visual_template(name, subject='Welcome {{ first_name|default("Friend", true) }}')
		template = frappe.get_doc("Email Template", result["name"])
		self.assertEqual(template.custom_builder_mode, "Visual")
		self.assertEqual(template.use_html, 1)
		self.assertEqual(template.custom_builder_schema_version, 1)
		self.assertTrue(template.custom_builder_content_hash)
		self.assertIn('ebv("first_name"', template.subject)
		self.assertIn("/builder?template=", result["route"])
		with self.assertRaises(frappe.ValidationError):
			create_visual_template(name, subject="Duplicate")

	def test_master_is_directly_editable_and_creates_an_independent_email(self):
		master_name = f"_Test Builder Master {frappe.generate_hash(length=8)}"
		created = create_visual_template(
			master_name,
			subject="Reusable welcome",
			template_doctype=EMAIL_TEMPLATE_MASTER_DOCTYPE,
		)
		self.assertIn("template_doctype=Email%20Template%20Master", created["route"])

		master = frappe.get_doc(EMAIL_TEMPLATE_MASTER_DOCTYPE, master_name)
		result = save_builder(
			master.name,
			str(master.modified),
			json.dumps(_schema("1", "button")),
			json.dumps({"subject": "Master subject", "preheader": "Reusable", "reference_doctype": ""}),
			template_doctype=EMAIL_TEMPLATE_MASTER_DOCTYPE,
		)
		self.assertTrue(result["revision"])
		self.assertEqual(load_builder(master.name, EMAIL_TEMPLATE_MASTER_DOCTYPE)["template_doctype"], EMAIL_TEMPLATE_MASTER_DOCTYPE)
		self.assertEqual(
			frappe.db.get_value("Email Builder Revision", result["revision"], "template_doctype"),
			EMAIL_TEMPLATE_MASTER_DOCTYPE,
		)

		email_name = f"_Test Email From Master {frappe.generate_hash(length=8)}"
		copied = create_email_from_master(master.name, email_name, "Campaign subject")
		email = frappe.get_doc("Email Template", copied["name"])
		master.reload()
		self.assertEqual(email.custom_builder_schema, master.custom_builder_schema)
		self.assertEqual(email.response_html, master.response_html)
		self.assertEqual(email.custom_builder_subject_source, "Campaign subject")
		self.assertNotEqual(email.name, master.name)

	def test_builder_target_doctype_is_allowlisted(self):
		self.assertEqual(normalize_template_doctype(None), "Email Template")
		self.assertEqual(normalize_template_doctype(EMAIL_TEMPLATE_MASTER_DOCTYPE), EMAIL_TEMPLATE_MASTER_DOCTYPE)
		with self.assertRaises(frappe.PermissionError):
			normalize_template_doctype("User")

	def test_load_builder_reports_raw_manual_html_and_visual_conflict_state(self):
		raw = _email_template(
			"_Test Builder Raw State",
			subject="Raw subject",
			response_html="<p>Manual raw</p>",
			custom_builder_mode="Raw HTML",
		)
		raw_state = load_builder(raw.name)
		self.assertTrue(raw_state["has_manual_html"])
		self.assertTrue(raw_state["requires_overwrite_confirmation"])
		self.assertFalse(raw_state["html_conflict"])

		visual = _email_template("_Test Builder Visual Conflict")
		saved = save_builder(
			visual.name,
			str(visual.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Visual", "preheader": "", "reference_doctype": "Contact"}),
		)
		visual.reload()
		frappe.db.set_value("Email Template", visual.name, "response_html", "<p>Manual conflict</p>", update_modified=False)
		state = load_builder(visual.name)
		self.assertTrue(state["html_conflict"])
		self.assertTrue(state["requires_overwrite_confirmation"])
		self.assertEqual(state["content_hash"], saved["content_hash"])

	def test_switch_to_raw_html_preserves_visual_schema_and_requires_current_version(self):
		template = _email_template("_Test Builder Switch Raw")
		save_builder(
			template.name,
			str(template.modified),
			json.dumps(_schema("1", "button")),
			json.dumps({"subject": "Visual", "preheader": "", "reference_doctype": "Contact"}),
		)
		template.reload()
		visual_schema = template.custom_builder_schema
		with self.assertRaises(frappe.TimestampMismatchError):
			switch_to_raw_html(template.name, "2000-01-01 00:00:00")
		result = switch_to_raw_html(template.name, str(template.modified))
		template.reload()
		self.assertEqual(result["mode"], "Raw HTML")
		self.assertEqual(template.custom_builder_mode, "Raw HTML")
		self.assertEqual(template.custom_builder_schema, visual_schema)
		self.assertTrue(template.response_html)

	def test_get_merge_fields_excludes_unsafe_fieldtypes_and_includes_safe_scalars(self):
		fields = get_merge_fields("Contact")
		fieldnames = {row["fieldname"] for row in fields}
		fieldtypes = {row["fieldname"]: row["fieldtype"] for row in fields}
		self.assertIn("name", fieldnames)
		self.assertIn("first_name", fieldnames)
		self.assertNotIn("password", {value.lower() for value in fieldnames})
		self.assertFalse({"Table", "Password", "Code", "HTML"}.intersection(fieldtypes.values()))

	def test_link_merge_fields_expose_one_safe_related_level(self):
		root_fields = {row["fieldname"]: row for row in get_merge_fields("Lead")}
		self.assertEqual(root_fields["lead_owner"]["options"], "User")
		result = get_link_merge_fields("Lead", "lead_owner")
		self.assertEqual(result["target_doctype"], "User")
		fieldnames = {row["fieldname"] for row in result["fields"]}
		self.assertIn("lead_owner.full_name", fieldnames)
		self.assertIn("lead_owner.name", fieldnames)
		self.assertFalse(any(fieldname.count(".") > 1 for fieldname in fieldnames))

	def test_reference_validation_accepts_safe_linked_field_and_rejects_unknown_target(self):
		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<p>{{ lead_owner.full_name }}</p>"
		_validate_reference_usage(schema, "", "", "Lead")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<p>{{ lead_owner.not_a_field }}</p>"
		with self.assertRaises(frappe.ValidationError):
			_validate_reference_usage(schema, "", "", "Lead")

	def test_list_components_filters_enabled_category_and_paginates(self):
		prefix = f"_Test Component List {frappe.generate_hash(length=6)}"
		created = []
		for index, category in enumerate(("Content", "CTA", "Content")):
			created.append(
				save_component(
					json.dumps(
						{
							"component_name": f"{prefix} {index}",
							"component_type": "Block",
							"category": category,
							"enabled": 1,
							"definition": {"id": f"component-list-{index}", "type": "text", "content": {"html": f"<p>{index}</p>"}},
						}
					)
				)
			)
		frappe.db.set_value("Email Builder Component", created[1]["name"], "enabled", 0)
		rows = list_components(start=0, page_length=1, category="Content")
		self.assertEqual(len(rows), 1)
		self.assertEqual(rows[0]["category"], "Content")
		self.assertNotEqual(rows[0]["name"], created[1]["name"])
		self.assertLessEqual(len(list_components(start=0, page_length=500)), 50)

	def test_revision_retention_keeps_latest_twenty_changed_revisions(self):
		template = _email_template("_Test Builder Revision Retention")
		metadata = {"subject": "Retention", "preheader": "", "reference_doctype": "Contact"}
		for index in range(22):
			template.reload()
			schema = _schema("1", "text")
			schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = f"<p>Revision {index}</p>"
			save_builder(template.name, str(template.modified), json.dumps(schema), json.dumps(metadata))
		revisions = list_revisions(template.name, page_length=50)
		self.assertEqual(len(revisions), 20)
		self.assertEqual(revisions[0]["revision_number"], 22)
		self.assertEqual(revisions[-1]["revision_number"], 3)

	def test_revision_preview_and_restore_reject_cross_template_revision(self):
		first = _email_template("_Test Builder Cross Revision A")
		second = _email_template("_Test Builder Cross Revision B")
		result = save_builder(
			first.name,
			str(first.modified),
			json.dumps(_schema("1", "text")),
			json.dumps({"subject": "Cross", "preheader": "", "reference_doctype": "Contact"}),
		)
		second.reload()
		with self.assertRaises(frappe.ValidationError):
			render_revision_preview(second.name, result["revision"])
		with self.assertRaises(frappe.ValidationError):
			restore_revision(second.name, result["revision"], str(second.modified))

	def test_test_email_rate_limit_blocks_after_ten_attempts(self):
		template = _email_template("_Test Builder Rate Limit")
		schema = json.dumps(_schema("1", "text"))
		metadata = json.dumps({"subject": "Rate", "preheader": "", "reference_doctype": "Contact"})
		window_number = 987654321
		cache_key = frappe.cache.make_key(f"email-builder-test:{frappe.session.user}:{window_number}")
		frappe.cache.delete_value(cache_key, make_keys=False)
		with patch("finbyzreach.email_template_builder.api.time.time", return_value=window_number * 600), patch("finbyzreach.email_template_builder.api.frappe.sendmail"):
			for index in range(10):
				send_test_email(template.name, schema, metadata, recipient=f"rate-{index}@example.com")
			with self.assertRaises(frappe.RateLimitExceededError):
				send_test_email(template.name, schema, metadata, recipient="rate-over@example.com")
		frappe.cache.delete_value(cache_key, make_keys=False)

	def test_preview_url_block_is_hidden_without_preview_context_and_safe_with_context(self):
		schema = _schema("1", "preview_url")
		compiled = compile_schema(schema)
		without_context = frappe.render_template(compiled["html"], {})
		with_context = frappe.render_template(compiled["html"], {"email_preview_url": "https://example.com/preview?id=1"})
		unsafe_context = frappe.render_template(compiled["html"], {"email_preview_url": "javascript:alert(1)"})
		self.assertNotIn("View online", without_context)
		self.assertIn("https://example.com/preview?id=1", with_context)
		self.assertNotIn("javascript:alert", unsafe_context)
		self.assertIn('href="#"', unsafe_context)
