"""An SMS button in an email opens a small page of ours, because Gmail and Outlook ignore sms: links."""
from __future__ import annotations

from frappe.tests import IntegrationTestCase

from ...www.open_sms import sms_targets
from ..compiler import compile_schema, sms_landing_url
from ..schema import validate_schema
from .test_button_actions import _button


def _html(action, href):
	return compile_schema(validate_schema(_button(action, href)))["html"]


class SmsButtonTest(IntegrationTestCase):
	def test_the_button_points_to_the_landing_page_with_number_and_text(self):
		url = sms_landing_url("sms:+41791234567?body=Hello there")
		self.assertTrue(url.endswith("/open_sms?to=%2B41791234567&body=Hello%20there"))
		html = _html("sms", "+41791234567?body=Hello%20there")
		self.assertIn("/open_sms?to=%2B41791234567&amp;body=Hello%20there", html)
		self.assertNotIn('href="sms:', html)

	def test_a_button_without_text_has_only_the_number(self):
		self.assertTrue(sms_landing_url("sms:+41 79 123 45 67").endswith("/open_sms?to=%2B41%2079%20123%2045%2067"))

	def test_a_merge_field_number_is_filled_in_for_each_recipient(self):
		html = _html("sms", "{{ mobile_no }}")
		self.assertIn("/open_sms?to=", html)
		self.assertIn("mobile_no", html)
		self.assertIn("urlencode", html)

	def test_phone_and_email_buttons_are_not_changed(self):
		self.assertIn('href="tel:+41441234567"', _html("telephone", "+41441234567"))
		self.assertIn('href="mailto:info@megasol.ch"', _html("email", "info@megasol.ch"))

	def test_the_landing_page_builds_android_and_iphone_links(self):
		target = sms_targets("+41 79 123 45 67", "Hello there")
		self.assertTrue(target["valid"])
		self.assertEqual(target["android"], "sms:+41791234567?body=Hello%20there")
		self.assertEqual(target["ios"], "sms:+41791234567&body=Hello%20there")
		self.assertEqual(sms_targets("+41791234567", "")["android"], "sms:+41791234567")

	def test_the_landing_page_refuses_bad_numbers_and_links_in_the_text(self):
		for bad in ("", "abc", "+41791234567; DROP", "javascript:1", "1" * 60):
			self.assertEqual(sms_targets(bad, "Hi"), {"valid": False}, bad)
		self.assertEqual(sms_targets("+41791234567", "Call http://evil.example now")["body"], "")
		self.assertEqual(len(sms_targets("+41791234567", "x" * 900)["body"]), 300)
