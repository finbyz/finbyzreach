"""Preference center design is rendered to anonymous visitors: only safe values may pass."""
import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach import preference_center as pc
from finbyzreach import subscription_preferences as prefs


class PreferenceCenterConfigTest(TestCase):
	def test_defaults_cover_every_language_and_text(self):
		config = pc.clean_config({})
		for lang in pc.LANGUAGES:
			for key in pc.PAGE_TEXTS + pc.MESSAGE_TEXTS:
				self.assertTrue(config["texts"][lang][key], (lang, key))
		self.assertEqual(config["order"], list(pc.SECTIONS))

	def test_unsafe_theme_values_are_dropped(self):
		config = pc.clean_config({"theme": {"primary": "red;background:url(x)", "font": "Comic Sans", "width": 9999,
			"radius": 500, "logo": "https://evil.example/logo.png"}})
		self.assertEqual(config["theme"]["primary"], pc.PRESETS["solar"]["primary"])
		self.assertEqual(config["theme"]["font"], "Inter")
		self.assertEqual(config["theme"]["width"], 560)
		self.assertEqual(config["theme"]["radius"], 24)
		self.assertEqual(config["theme"]["logo"], "")
		self.assertEqual(pc.clean_config({"theme": {"logo": "/files/logo.png"}})["theme"]["logo"], "/files/logo.png")

	def test_styles_are_clamped_and_named_colours_allowed(self):
		config = pc.clean_config({"styles": {"h": {"tag": "SCRIPT", "size": 400, "color": "url(x)", "align": "justify"},
			"s": {"tag": "H2", "size": 18, "color": "primary", "bold": True, "align": "center"}}})
		self.assertEqual(config["styles"]["h"], {**pc.DEFAULT_STYLES["h"], "size": 40})
		self.assertEqual(config["styles"]["s"], {"tag": "H2", "size": 18, "color": "primary", "bold": True, "align": "center"})

	def test_sections_custom_blocks_and_hidden(self):
		config = pc.clean_config({"order": ["types", "c2", "evil", "intro"], "custom": ["c2", "bad id"], "hidden": ["foot", "evil"],
			"texts": {"de": {"c2": "Extra", "h": "x" * 5000}}})
		self.assertEqual(config["custom"], ["c2"])
		self.assertEqual(config["order"], ["types", "c2", "intro", "topics", "buttons", "foot"])
		self.assertEqual(config["hidden"], ["foot"])
		self.assertEqual(config["texts"]["de"]["c2"], "Extra")
		self.assertEqual(config["texts"]["fr"]["c2"], "")
		self.assertEqual(len(config["texts"]["de"]["h"]), 2000)

	def test_broken_stored_design_falls_back_to_defaults(self):
		with patch.object(frappe.db, "get_single_value", return_value="{not json"), patch.object(frappe, "log_error"), \
				patch.object(frappe, "get_all", return_value=[]):
			self.assertEqual(pc.published_config()["texts"]["de"]["h"], pc.DEFAULT_TEXTS["de"]["h"])

	def test_page_context_resolves_css(self):
		config = pc.clean_config({"styles": {"h": {"color": "muted", "size": 20}}})
		ctx = pc.page_context(config, "fr")
		self.assertIn("font-size:20px", ctx["pc_css"]["h"])
		self.assertIn("color:#5d6875", ctx["pc_css"]["h"])
		self.assertEqual(ctx["text"]["h"], pc.DEFAULT_TEXTS["fr"]["h"])
		self.assertEqual(pc.page_context(config, "xx")["text"]["h"], pc.DEFAULT_TEXTS["de"]["h"])


class DoubleOptInCopyTest(TestCase):
	def test_message_in_each_language_and_escaped(self):
		with patch.object(prefs, "topic_label", return_value="<b>News</b>"):
			for lang, phrase in (("de", "bestätigen"), ("fr", "confirmer"), ("it", "Conferma"), ("en", "confirm")):
				subject, body = prefs.doi_message("News", "https://x.example/c?a=1&b=2", lang)
				self.assertIn(phrase.lower(), (subject + body).lower())
				self.assertIn("&lt;b&gt;News&lt;/b&gt;", body)
				self.assertIn("a=1&amp;b=2", body)
			self.assertEqual(prefs.doi_message("News", "u", "xx")[0], prefs.DOI_COPY["de"]["subject"])


class SubscribeAndConfirmPagesTest(TestCase):
	def test_each_page_has_complete_defaults(self):
		config = pc.clean_config({})
		for page in ("subscribe", "confirm"):
			spec = pc.PAGES[page]
			self.assertEqual(config[page]["order"], list(spec["sections"]))
			for lang in pc.LANGUAGES:
				for key in spec["page_texts"] + spec["message_texts"]:
					self.assertTrue(config[page]["texts"][lang][key], (page, lang, key))

	def test_required_sections_cannot_be_hidden(self):
		config = pc.clean_config({"subscribe": {"hidden": ["email", "buttons", "names", "legal"]}, "confirm": {"hidden": ["button", "foot"]}})
		self.assertEqual(config["subscribe"]["hidden"], ["names", "legal"])
		self.assertEqual(config["confirm"]["hidden"], ["foot"])

	def test_pages_are_independent_but_share_the_theme(self):
		config = pc.clean_config({"theme": {"primary": "#112233"}, "subscribe": {"texts": {"fr": {"h": "Inscription"}},
			"custom": ["c1"], "order": ["c1", "intro"], "styles": {"register": {"size": 18}}}})
		self.assertEqual(config["subscribe"]["texts"]["fr"]["h"], "Inscription")
		self.assertEqual(config["texts"]["fr"]["h"], pc.DEFAULT_TEXTS["fr"]["h"])
		self.assertEqual(config["confirm"]["custom"], [])
		ctx = pc.page_context(config, "fr", "subscribe")
		self.assertEqual(ctx["text"]["h"], "Inscription")
		self.assertEqual(ctx["sections"][:2], ["c1", "intro"])
		self.assertIn("font-size:18px", ctx["pc_css"]["register"])
		self.assertEqual(ctx["pc_theme"]["primary"], "#112233")
		self.assertEqual(pc.page_context(config, "de", "confirm")["text"]["button"], pc.CONFIRM_TEXTS["de"]["button"])

	def test_preview_requires_an_editor(self):
		with patch.object(frappe, "session", frappe._dict(user="Guest")):
			with self.assertRaises(frappe.PermissionError):
				pc.require_preview()
