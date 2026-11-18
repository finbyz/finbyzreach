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
