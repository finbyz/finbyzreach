"""EM-19: Campaign Studio sends to several segments and excludes whole segments."""
import json
from unittest import TestCase
from unittest.mock import patch

import frappe

from finbyzreach.finbyzreach.page.email_campaign_studio import email_campaign_studio as studio


def marker(name, kind="#REACH_SEGMENT#"):
	return [["Lead", "name", "in", [kind, name]]]


class StudioSegmentsTest(TestCase):
	def test_segment_name_list_accepts_json_list_and_single_name(self):
		self.assertEqual(studio._segment_name_list('["A", " B ", "A", ""]'), ["A", "B"])
		self.assertEqual(studio._segment_name_list(["C"]), ["C"])
		self.assertEqual(studio._segment_name_list("D"), ["D"])
		self.assertEqual(studio._segment_name_list(None or []), [])

	def test_split_segment_groups_separates_markers_from_rules(self):
		rule = [["Lead", "city", "=", "Bern"]]
		plain, names = studio.split_segment_groups([marker("A"), rule, marker("B", "#STATIC_SEGMENT#"), marker("A")])
		self.assertEqual(plain, [rule])
		self.assertEqual(names, ["A", "B"])

	def test_extra_and_excluded_segments_become_marker_groups(self):
		segment = lambda name, doctype: frappe._dict(name=name, exclude_email_groups_json="[]")
		with patch.object(studio, "_mailing_segment", side_effect=segment):
			context = studio._audience_context(
				[[["Lead", "city", "=", "Bern"]]], None, None, require_filters=False,
				audience_doctype="Lead", resolve_names=False,
				segment_names=["Installers", "Press"], exclude_segment_names=["Competitors"],
			)
		include = json.loads(context.include_filters_json)
		exclude = json.loads(context.exclude_filters_json)
		self.assertEqual(include[1:], [marker("Installers"), marker("Press")])
		self.assertEqual(exclude, [marker("Competitors")])

	def test_campaign_reload_restores_the_segment_fields(self):
		campaign = frappe._dict(
			custom_lead_filters_json=json.dumps([marker("Installers"), marker("Press")]),
			custom_exclude_filters_json=json.dumps([marker("Competitors"), [["Lead", "status", "=", "Do Not Contact"]]]),
		)
		fields = studio._campaign_audience_fields(campaign)
		self.assertEqual(fields["segment_name"], "Installers")
		self.assertEqual(fields["segment_names"], ["Press"])
		self.assertEqual(fields["exclude_segment_names"], ["Competitors"])
		self.assertEqual(fields["filters"], [])
		self.assertEqual(fields["exclude_filters"], [[["Lead", "status", "=", "Do Not Contact"]]])

	def test_archived_or_wrong_audience_segment_is_refused(self):
		doc = frappe._dict(name="Old", audience_doctype="Contact", archived=0, check_permission=lambda *_: None)
		with patch.object(frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.ValidationError):
				studio._mailing_segment("Old", "Lead")
		doc.update(audience_doctype="Lead", archived=1)
		with patch.object(frappe, "get_doc", return_value=doc):
			with self.assertRaises(frappe.ValidationError):
				studio._mailing_segment("Old", "Lead")
