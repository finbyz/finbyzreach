"""EM-14: fonts for heading 1 to 3 and paragraphs, set once for the whole email."""
from __future__ import annotations

from frappe.tests import IntegrationTestCase

from ..compiler import apply_typography, compile_schema
from ..schema import validate_schema
from .test_email_template_builder import _schema


class TypographyTest(IntegrationTestCase):
	def test_headings_and_paragraphs_get_their_own_fonts(self):
		settings = {"h1_font_family": "Georgia, serif", "h1_font_size": "32px", "h1_font_weight": "700", "p_font_size": "15px"}
		out = apply_typography("<h1>Title</h1><h2>Sub</h2><p>Body</p>", settings)
		self.assertIn('<h1 style="font-family:Georgia, serif;font-size:32px;font-weight:700">Title</h1>', out)
		self.assertIn("<h2>Sub</h2>", out)
		self.assertIn('<p style="font-size:15px">Body</p>', out)

	def test_a_font_set_on_the_text_itself_wins(self):
		out = apply_typography('<p style="font-size:20px;color:red">Hi</p>', {"p_font_size": "15px", "p_font_weight": "bold"})
		self.assertIn("font-size:20px", out)
		self.assertNotIn("font-size:15px", out)
		self.assertIn("font-weight:bold", out)
		self.assertIn("color:red", out)

	def test_merge_tokens_and_other_tags_are_left_alone(self):
		html = '<p>Hello {{ first_name|default("Friend", true) }} <b>now</b> {% if a > b %}x{% endif %}</p>'
		out = apply_typography(html, {"p_font_size": "15px"})
		self.assertIn('{{ first_name|default("Friend", true) }}', out)
		self.assertIn("{% if a > b %}", out)
		self.assertIn("<b>now</b>", out)

	def test_nothing_changes_when_no_fonts_are_set(self):
		html = "<h1>Title</h1><p>Body</p>"
		self.assertEqual(apply_typography(html, {}), html)

	def test_only_valid_values_are_kept_when_the_email_is_validated(self):
		schema = _schema("1", "text")
		schema["settings"] = {
			"h1_font_family": "Georgia, serif", "h1_font_size": "28px", "h1_font_weight": "700",
			"h2_font_family": "x;}</style><script>", "h2_font_size": "huge", "h2_font_weight": "heavy", "h3_font_size": "0px", "p_font_weight": "",
		}
		settings = validate_schema(schema)["settings"]
		self.assertEqual((settings["h1_font_family"], settings["h1_font_size"], settings["h1_font_weight"]), ("Georgia, serif", "28px", "700"))
		for key in ("h2_font_family", "h2_font_size", "h2_font_weight", "h3_font_size", "p_font_weight"):
			self.assertNotIn(key, settings)

	def test_a_compiled_text_block_carries_the_heading_font(self):
		schema = _schema("1", "text")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["html"] = "<h2>Offer</h2><p>Text</p>"
		schema["settings"] = {"h2_font_family": "Georgia, serif", "h2_font_size": "24px"}
		html = compile_schema(validate_schema(schema))["html"]
		self.assertIn("<h2 style=\"font-family:Georgia, serif;font-size:24px\">Offer</h2>", html)
