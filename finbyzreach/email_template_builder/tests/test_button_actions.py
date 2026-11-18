"""EM-06: button actions (URL, email, public file, phone, SMS) and the full-width option."""
from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from ..compiler import compile_schema
from ..schema import validate_schema


def _button(action, href, full_width=False):
	return {"version": 1, "settings": {}, "sections": [{"id": "s", "layout": "1", "columns": [{"id": "c", "blocks": [
		{"id": "b", "type": "button", "content": {"text": "Go", "action": action, "href": href, "full_width": full_width}}]}]}]}


def _href(action, href):
	return validate_schema(_button(action, href))["sections"][0]["columns"][0]["blocks"][0]["content"]["href"]


class ButtonActionsTest(IntegrationTestCase):
	def test_each_action_builds_its_link(self):
		self.assertEqual(_href("url", "megasol.ch"), "https://megasol.ch")
		self.assertEqual(_href("email", "info@megasol.ch"), "mailto:info@megasol.ch")
		self.assertEqual(_href("telephone", "+41 44 123 45 67"), "tel:+41441234567")
		self.assertEqual(_href("telephone", "(044) 123-45-67"), "tel:0441234567")
		self.assertEqual(_href("sms", "+41791234567"), "sms:+41791234567")
		self.assertEqual(_href("file", "/files/a.pdf"), "/files/a.pdf")

	def test_an_sms_link_needs_a_real_number_and_may_prefill_the_message(self):
		self.assertEqual(_href("sms", "sms:+41791234567"), "sms:+41791234567")
		self.assertEqual(_href("sms", "+41791234567?body=Hello%20there"), "sms:+41791234567?body=Hello%20there")
		self.assertEqual(_href("sms", "+41791234567?body=Hello there, please call me"), "sms:+41791234567?body=Hello there, please call me")
		self.assertEqual(_href("sms", "{{ mobile_no }}"), "sms:{{ mobile_no }}")
		for bad in ("abc", "sms:abc", "sms:hello world", "+41791234567?body=<script>"):
			self.assertEqual(_href("sms", bad), "#", bad)

	def test_a_phone_link_needs_a_real_number(self):
		self.assertEqual(_href("telephone", "tel:+41441234567"), "tel:+41441234567")
		for bad in ("abc", "tel:abc"):
			self.assertEqual(_href("telephone", bad), "#", bad)

	def test_unsafe_or_wrong_values_never_become_live_links(self):
		self.assertEqual(_href("url", "javascript:alert(1)"), "#")
		self.assertEqual(_href("email", "not an email"), "#")

	def test_private_files_are_refused(self):
		with self.assertRaises(frappe.ValidationError):
			_href("file", "/private/files/a.pdf")

	def test_full_width_makes_the_button_fill_the_row(self):
		wide = compile_schema(validate_schema(_button("url", "https://megasol.ch", True)))["html"]
		narrow = compile_schema(validate_schema(_button("url", "https://megasol.ch", False)))["html"]
		self.assertIn('align="left" width="100%"', wide)
		self.assertNotIn('align="left" width="100%"', narrow)
