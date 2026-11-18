"""EM-03: superscript, subscript and strikethrough survive saving a text block."""
from unittest import TestCase

from finbyzreach.email_template_builder.sanitizer import sanitize_rich_html


class RichTextFormattingTest(TestCase):
	def test_superscript_subscript_and_strike_are_kept(self):
		html = sanitize_rich_html("<p>Area 400 m<sup>2</sup>, CO<sub>2</sub>, <strike>CHF 90</strike> <s>old</s></p>")
		for tag in ("<sup>2</sup>", "<sub>2</sub>", "<strike>CHF 90</strike>", "<s>old</s>"):
			self.assertIn(tag, html)

	def test_scripts_are_still_removed(self):
		html = sanitize_rich_html('<p>Hi<sup onclick="alert(1)">x</sup><script>alert(1)</script></p>')
		self.assertNotIn("onclick", html)
		self.assertNotIn("<script", html)


class SavedBlockNameTest(TestCase):
	def test_duplicate_block_name_gets_a_clear_message(self):
		from unittest.mock import patch
		import frappe
		from finbyzreach.email_template_builder import api
		new_doc = frappe._dict(name=None, save=lambda: None)
		with patch.object(api, "_require_designer"), patch.object(api, "validate_component", return_value={"component_type": "x", "category": "y"}), \
				patch.object(frappe, "has_permission", return_value=True), patch.object(frappe, "new_doc", return_value=new_doc), \
				patch.object(frappe.db, "get_value", return_value="Footer - DE"):
			with self.assertRaises(frappe.ValidationError) as caught:
				api.save_component({"component_name": "Footer - DE"})
		self.assertIn("already exists", str(caught.exception))
