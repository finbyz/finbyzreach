from __future__ import annotations

from copy import deepcopy

from frappe.tests import IntegrationTestCase

from ..design_defaults import apply_design_defaults, repair_text


def _doc(blocks, section_style=None):
	return {
		"version": 1,
		"settings": {},
		"sections": [
			{
				"id": "sec-1",
				"layout": "1",
				"style": section_style if section_style is not None else {},
				"columns": [{"id": "col-1", "style": {}, "blocks": blocks}],
			}
		],
	}


def _first_block(doc):
	return doc["sections"][0]["columns"][0]["blocks"][0]


class TestMergeTokenRepair(IntegrationTestCase):
	"""The agent writes ``{ doc.field }``; only ``{{ field }}`` resolves."""

	def test_single_brace_token_is_repaired(self):
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>Hi { doc.first_name }</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["tokens_repaired"], 1)
		self.assertIn("{{ first_name }}", _first_block(doc)["content"]["html"])

	def test_single_brace_without_doc_prefix_is_repaired(self):
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>Hi { first_name }</p>"}}])
		apply_design_defaults(doc)
		self.assertIn("{{ first_name }}", _first_block(doc)["content"]["html"])

	def test_doc_prefix_is_stripped_from_valid_token(self):
		"""``ebv`` reads a dotted name as a link path, so ``doc.`` never resolves."""
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>{{ doc.company }}</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["tokens_repaired"], 1)
		self.assertIn("{{ company }}", _first_block(doc)["content"]["html"])

	def test_link_path_token_is_left_alone(self):
		"""``{{ customer.email_id }}`` is a legitimate link path, not a mistake."""
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>{{ customer.email_id }}</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["tokens_repaired"], 0)
		self.assertIn("{{ customer.email_id }}", _first_block(doc)["content"]["html"])

	def test_scheme_prefixed_token_url_is_collapsed(self):
		"""``https://{{ x }}`` would double the scheme; the field holds a full URL."""
		doc = _doc([{"id": "b1", "type": "button", "content": {"text": "Go", "href": "https://{ doc.dashboard_link }"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["href"], "{{ dashboard_link }}")

	def test_mailto_prefixed_token_is_collapsed(self):
		doc = _doc([{"id": "b1", "type": "button", "content": {"text": "Mail", "href": "mailto:{ doc.support_email }"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["href"], "{{ support_email }}")

	def test_real_url_is_untouched(self):
		doc = _doc([{"id": "b1", "type": "button", "content": {"text": "Go", "href": "https://finbyz.com/pricing"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["tokens_repaired"], 0)
		self.assertEqual(_first_block(doc)["content"]["href"], "https://finbyz.com/pricing")

	def test_css_braces_are_not_mistaken_for_tokens(self):
		"""Inline CSS such as ``{color:#fff}`` must survive the repair pass."""
		html = '<p style="color:#fff">a</p>'
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": html}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["tokens_repaired"], 0)
		self.assertEqual(_first_block(doc)["content"]["html"], html)

	def test_repair_text_handles_subject_line(self):
		repaired, count = repair_text("Welcome { doc.first_name }!")
		self.assertEqual(repaired, "Welcome {{ first_name }}!")
		self.assertEqual(count, 1)


class TestAlignmentDefaults(IntegrationTestCase):
	"""The compiler defaults images and buttons to left; the agent never sets align."""

	def test_image_defaults_to_centered(self):
		doc = _doc([{"id": "b1", "type": "image", "style": {}, "content": {"src": "/files/a.png"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["style"]["align"], "center")

	def test_button_defaults_to_centered(self):
		doc = _doc([{"id": "b1", "type": "button", "style": {}, "content": {"text": "Go"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["style"]["align"], "center")

	def test_explicit_alignment_is_respected(self):
		doc = _doc([{"id": "b1", "type": "image", "style": {"align": "right"}, "content": {"src": "/files/a.png"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["style"]["align"], "right")

	def test_alignment_is_inherited_from_sibling_text(self):
		"""A left-aligned column should not have its button yanked to the centre."""
		doc = _doc([
			{"id": "b1", "type": "text", "content": {"html": '<p style="text-align:left">Body copy</p>'}},
			{"id": "b2", "type": "button", "style": {}, "content": {"text": "Go"}},
		])
		apply_design_defaults(doc)
		self.assertEqual(doc["sections"][0]["columns"][0]["blocks"][1]["style"]["align"], "left")

	def test_centered_sibling_text_centers_the_image(self):
		doc = _doc([
			{"id": "b1", "type": "text", "content": {"html": '<h3 style="text-align:center">Step 1</h3>'}},
			{"id": "b2", "type": "image", "style": {}, "content": {"src": "/files/a.png"}},
		])
		apply_design_defaults(doc)
		self.assertEqual(doc["sections"][0]["columns"][0]["blocks"][1]["style"]["align"], "center")

	def test_invalid_alignment_is_normalised(self):
		doc = _doc([{"id": "b1", "type": "button", "style": {"align": "middle"}, "content": {"text": "Go"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["style"]["align"], "center")

	def test_text_blocks_are_not_given_an_align(self):
		"""Text carries its own alignment in inline CSS; adding one would fight it."""
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>Body</p>"}}])
		apply_design_defaults(doc)
		self.assertNotIn("align", _first_block(doc).get("style", {}))


class TestSpacingDefaults(IntegrationTestCase):
	def test_section_without_padding_gets_insets(self):
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>a</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["sections_padded"], 1)
		self.assertEqual(doc["sections"][0]["style"]["padding"]["left"], "24px")

	def test_zeroed_padding_counts_as_unset(self):
		"""``validate_schema`` normalises absent padding to explicit zeros."""
		zeros = {"top": "0px", "right": "0px", "bottom": "0px", "left": "0px"}
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>a</p>"}}], section_style={"padding": zeros})
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["sections_padded"], 1)

	def test_authored_padding_is_respected(self):
		custom = {"top": "40px", "right": "8px", "bottom": "40px", "left": "8px"}
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>a</p>"}}], section_style={"padding": custom})
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["sections_padded"], 0)
		self.assertEqual(doc["sections"][0]["style"]["padding"], custom)

	def test_button_gets_vertical_breathing_room(self):
		doc = _doc([{"id": "b1", "type": "button", "style": {}, "content": {"text": "Go"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["buttons_padded"], 1)
		self.assertEqual(_first_block(doc)["style"]["padding"]["top"], "8px")


class TestSocialPlatformRepair(IntegrationTestCase):
	"""``_validate_block`` matches platforms exactly, collapsing misses to Website."""

	def _social(self, items):
		return _doc([{"id": "b1", "type": "social", "style": {}, "content": {"items": items}}])

	def test_platform_recovered_from_token_field_name(self):
		doc = self._social([{"platform": "Website", "href": "{{ facebook_link }}", "label": "Website"}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["social_fixed"], 1)
		self.assertEqual(_first_block(doc)["content"]["items"][0]["platform"], "Facebook")

	def test_lowercase_platform_is_corrected(self):
		doc = self._social([{"platform": "linkedin", "href": "https://linkedin.com/x", "label": ""}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["items"][0]["platform"], "LinkedIn")

	def test_twitter_maps_to_x(self):
		doc = self._social([{"platform": "Twitter", "href": "https://twitter.com/x", "label": ""}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["items"][0]["platform"], "X")

	def test_genuine_website_link_stays_website(self):
		doc = self._social([{"platform": "Website", "href": "https://finbyz.com", "label": "Website"}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["social_fixed"], 0)
		self.assertEqual(_first_block(doc)["content"]["items"][0]["platform"], "Website")


class TestPlaceholderDetection(IntegrationTestCase):
	def test_bracket_placeholder_is_flagged(self):
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>Welcome to [Your Company Name]</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertIn("[Your Company Name]", stats["placeholders"])

	def test_clean_copy_flags_nothing(self):
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": "<p>Welcome to Finbyz</p>"}}])
		stats = apply_design_defaults(doc)
		self.assertEqual(stats["placeholders"], [])


class TestIdempotence(IntegrationTestCase):
	def test_second_pass_changes_nothing(self):
		"""A rewrite re-submits an already-repaired schema; it must not drift."""
		doc = _doc([
			{"id": "b1", "type": "text", "content": {"html": "<p>Hi { doc.first_name }</p>"}},
			{"id": "b2", "type": "button", "style": {}, "content": {"text": "Go", "href": "https://{ doc.link }"}},
		])
		apply_design_defaults(doc)
		once = deepcopy(doc)
		stats = apply_design_defaults(doc)
		self.assertEqual(doc, once)
		self.assertEqual(stats["tokens_repaired"], 0)
		self.assertEqual(stats["alignments_set"], 0)
		self.assertEqual(stats["sections_padded"], 0)

	def test_malformed_schema_does_not_raise(self):
		for bad in (None, [], "text", {"sections": "nope"}, {"sections": [None, {"columns": [None]}]}):
			apply_design_defaults(bad)


class TestInlineAnchorHrefs(IntegrationTestCase):
	"""sanitize_rich_html rejects a bare token in an inline anchor href.

	Repairing the token without also restoring a literal scheme turned a
	merely-broken link into one that failed validation and took the whole
	generation with it.
	"""

	def test_repaired_inline_anchor_gets_a_scheme(self):
		doc = _doc([{"id": "b1", "type": "text",
		             "content": {"html": '<p><a href="{ doc.blog_link }">Blog</a></p>'}}])
		apply_design_defaults(doc)
		self.assertIn('href="https://{{ blog_link }}"', _first_block(doc)["content"]["html"])

	def test_anchor_that_already_has_a_scheme_is_untouched(self):
		html = '<p><a href="https://finbyz.com/blog">Blog</a></p>'
		doc = _doc([{"id": "b1", "type": "text", "content": {"html": html}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["html"], html)

	def test_relative_and_mailto_anchors_are_untouched(self):
		for href in ("/pricing", "#top", "mailto:hi@finbyz.com"):
			html = f'<p><a href="{href}">x</a></p>'
			doc = _doc([{"id": "b1", "type": "text", "content": {"html": html}}])
			apply_design_defaults(doc)
			self.assertEqual(_first_block(doc)["content"]["html"], html)

	def test_block_level_href_still_takes_a_bare_token(self):
		"""The opposite rule applies to a button's own href field."""
		doc = _doc([{"id": "b1", "type": "button",
		             "content": {"text": "Go", "href": "https://{ doc.dashboard_link }"}}])
		apply_design_defaults(doc)
		self.assertEqual(_first_block(doc)["content"]["href"], "{{ dashboard_link }}")
