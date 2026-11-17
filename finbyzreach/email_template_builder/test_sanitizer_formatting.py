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
