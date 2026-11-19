"""EM-15: dark mode and Outlook handling in the compiled e-mail."""
from frappe.tests import IntegrationTestCase

from finbyzreach.email_template_builder.compiler import compile_schema
from finbyzreach.email_template_builder.schema import validate_schema


def _schema(**settings):
	return {
		"version": 1,
		"settings": settings,
		"sections": [{"id": "s1", "layout": "1", "columns": [{"id": "c1", "blocks": [
			{"id": "b1", "type": "text", "content": {"html": "<p>Hello</p>"}},
			{"id": "b2", "type": "button", "content": {"text": "Open", "href": "https://example.com"}},
		]}]}],
	}


class TestEmailDarkMode(IntegrationTestCase):
	def test_dark_mode_is_on_by_default(self):
		html = compile_schema(_schema())["html"]
		self.assertIn('name="color-scheme" content="light dark"', html)
		self.assertIn("@media (prefers-color-scheme:dark)", html)
		self.assertIn("[data-ogsc] .etb-page", html)
		self.assertIn("#0f172a", html)

	def test_default_text_colour_is_swapped_but_buttons_are_kept(self):
		html = compile_schema(_schema())["html"]
		self.assertIn('.etb-content [style^="color:#1f2937"]', html)
		self.assertIn(".etb-content a:not(.etb-btn)", html)
		self.assertIn('class="etb-btn"', html)

	def test_dark_mode_can_be_switched_off(self):
		html = compile_schema(_schema(dark_mode="off"))["html"]
		self.assertNotIn("prefers-color-scheme", html)
		self.assertNotIn("color-scheme", html)

	def test_dark_colours_are_validated_and_customisable(self):
		settings = validate_schema(_schema(dark_content_background="#101010", dark_text_color="not a colour"))["settings"]
		self.assertEqual(settings["dark_content_background"], "#101010")
		self.assertEqual(settings["dark_text_color"], "#e5e7eb")  # falls back to the documented default
		self.assertIn("#101010", compile_schema(_schema(dark_content_background="#101010"))["html"])

	def test_outlook_for_windows_gets_a_fixed_width_wrapper_and_button_padding(self):
		html = compile_schema(_schema())["html"]
		self.assertIn("<!--[if mso]>", html)
		self.assertIn('width="600"', html)
		self.assertIn("mso-padding-alt:12px 22px", html)
		self.assertIn("xmlns:v=", html)


class TestCodeBlockStyles(IntegrationTestCase):
	def test_background_shorthand_is_kept_and_unsafe_css_is_removed(self):
		from finbyzreach.email_template_builder.sanitizer import sanitize_code_html

		html = sanitize_code_html('<div style="background:#ff0000;position:absolute;text-transform:uppercase;color:#fff">x</div>')
		self.assertIn("background:#ff0000", html.replace(" ", ""))
		self.assertIn("text-transform", html)
		self.assertNotIn("position", html)
