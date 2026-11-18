"""EM-08: nine platforms (plus Website) with hosted PNG icons, which Gmail and Outlook can show."""
from __future__ import annotations

import os

from frappe.tests import IntegrationTestCase

from ..compiler import SOCIAL_PLATFORMS, compile_schema
from ..schema import validate_schema
from .test_email_template_builder import _schema

REQUIRED = ["LinkedIn", "Instagram", "Facebook", "YouTube", "X", "TikTok", "XING", "Pinterest", "WhatsApp"]


class SocialIconsTest(IntegrationTestCase):
	def test_all_nine_platforms_are_available(self):
		for name in REQUIRED:
			self.assertIn(name, SOCIAL_PLATFORMS)

	def test_every_icon_is_a_hosted_png_that_exists(self):
		folder = os.path.join(os.path.dirname(__file__), "..", "..", "public", "email_builder", "social")
		for name, meta in SOCIAL_PLATFORMS.items():
			self.assertTrue(meta["asset"].endswith(".png"), name)
			self.assertTrue(os.path.exists(os.path.join(folder, os.path.basename(meta["asset"]))), f"{name} icon file is missing")

	def test_a_social_block_with_every_platform_compiles_to_png_images(self):
		schema = _schema("1", "social")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"]["items"] = [{"platform": name, "href": "https://example.com/" + name.lower()} for name in REQUIRED]
		html = compile_schema(validate_schema(schema))["html"]
		for name in REQUIRED:
			self.assertIn(f"/social/{name.lower()}.png", html)
		self.assertNotIn(".svg", html)
		self.assertNotIn("<svg", html)

	def test_an_unknown_platform_still_falls_back_to_website(self):
		schema = _schema("1", "social")
		schema["sections"][0]["columns"][0]["blocks"][0]["content"]["items"] = [{"platform": "Myspace", "href": "https://example.com"}]
		self.assertIn("/social/website.png", compile_schema(validate_schema(schema))["html"])


class SocialIconColourTest(IntegrationTestCase):
	def _html(self, **content):
		schema = _schema("1", "social")
		block = schema["sections"][0]["columns"][0]["blocks"][0]
		block["content"].update(content)
		return compile_schema(validate_schema(schema))["html"], validate_schema(schema)["sections"][0]["columns"][0]["blocks"][0]["content"]

	def test_default_symbol_is_the_white_png_on_the_background_colour(self):
		html, _content = self._html()
		self.assertIn("/social/linkedin.png", html)
		self.assertNotIn("/files/social-icons/", html)

	def test_a_symbol_colour_gives_a_hosted_png_in_that_colour(self):
		import os
		import frappe
		html, content = self._html(icon_color="#FFD700")
		self.assertEqual(content["icon_color"], "#ffd700")
		self.assertIn("/files/social-icons/linkedin-ffd700.png", html)
		self.assertTrue(os.path.exists(frappe.get_site_path("public", "files", "social-icons", "linkedin-ffd700.png")))
		from PIL import Image
		pixel = Image.open(frappe.get_site_path("public", "files", "social-icons", "linkedin-ffd700.png")).convert("RGBA")
		colours = {p[:3] for p in pixel.getdata() if p[3] > 200}
		self.assertEqual(colours, {(255, 215, 0)})

	def test_no_background_shows_only_the_symbol_in_the_chosen_or_brand_colour(self):
		html, _c = self._html(icon_shape="none", icon_color="#111111")
		self.assertIn("/files/social-icons/linkedin-111111.png", html)
		self.assertNotIn("border-radius", html.split("linkedin-111111.png")[0].rsplit("<a ", 1)[-1])
		self.assertNotIn("background:", html.split("linkedin-111111.png")[0].rsplit("<a ", 1)[-1])
		brand, _c = self._html(icon_shape="none")
		self.assertIn("/files/social-icons/linkedin-0a66c2.png", brand)

	def test_an_invalid_symbol_colour_is_dropped(self):
		for bad in ("red;}", "javascript:1", "#12", "url(x)"):
			html, content = self._html(icon_color=bad)
			self.assertNotIn("icon_color", content, bad)
			self.assertIn("/social/linkedin.png", html)
